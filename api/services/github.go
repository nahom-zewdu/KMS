// services/github.go
// Package services implements the GitHubIngestService for processing GitHub webhook events.
// It validates event data, sanitizes content, and delegates to CoreIngestService for storage
// and publishing. Supports edge cases like invalid delivery IDs and empty content.

package services

import (
	"context"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

// GitHubIngest implements the GitHubIngestService interface for GitHub event ingestion.
type GitHubIngest struct {
	coreIngest domain.CoreIngestService // Shared ingestion service
}

// NewGitHubIngest creates a new GitHubIngest service with the provided CoreIngestService.
// Args:
//
//	coreIngest: CoreIngestService for storage and publishing.
//
// Returns:
//
//	GitHubIngestService implementation.
func NewGitHubIngest(coreIngest domain.CoreIngestService) domain.GitHubIngestService {
	return &GitHubIngest{coreIngest: coreIngest}
}

// IngestGitHubEvent validates and processes GitHub webhook events, delegating to CoreIngestService.
// It ensures the source is 'github', validates content and delivery ID, and handles edge cases.
// Args:
//
//	ctx: Context for cancellation and timeouts.
//	req: IngestRequest with source, event_type, content, payload, record_id, created_at.
//
// Returns:
//
//	error if validation or ingestion fails.
func (g *GitHubIngest) IngestGitHubEvent(ctx context.Context, req domain.IngestRequest) error {
	start := time.Now()
	// Validate source
	if req.Source != "github" {
		log.Printf("RecordID: %s - Invalid GitHub ingest source: %s in %.3fs", req.RecordID, req.Source, time.Since(start).Seconds())
		return fmt.Errorf("invalid source for GitHub ingest: %s", req.Source)
	}

	// Validate content
	content := strings.TrimSpace(req.Content)
	if content == "" {
		log.Printf("RecordID: %s - Empty GitHub content in %.3fs", req.RecordID, time.Since(start).Seconds())
		return fmt.Errorf("empty content for GitHub ingest")
	}

	// Validate delivery ID (must be non-empty and match X-GitHub-Delivery format)
	if req.RecordID == "" || !strings.Contains(req.RecordID, "-") {
		log.Printf("RecordID: %s - Invalid GitHub delivery ID in %.3fs", req.RecordID, time.Since(start).Seconds())
		return fmt.Errorf("invalid GitHub delivery ID: %s", req.RecordID)
	}

	// Validate event type
	if req.EventType != "push" && req.EventType != "pull_request" && req.EventType != "issues" {
		log.Printf("RecordID: %s - Unsupported event type %s in %.3fs", req.RecordID, req.EventType, time.Since(start).Seconds())
		return fmt.Errorf("unsupported event type: %s", req.EventType)
	}

	// Delegate to CoreIngestService
	err := g.coreIngest.Ingest(ctx, req)
	if err != nil {
		log.Printf("RecordID: %s - Failed to ingest GitHub event in %.3fs: %v", req.RecordID, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to ingest GitHub event: %v", err)
	}

	log.Printf("RecordID: %s - Successfully ingested GitHub event (%s) in %.3fs", req.RecordID, req.EventType, time.Since(start).Seconds())
	return nil
}

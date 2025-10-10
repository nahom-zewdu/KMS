// services/github.go
package services

import (
	"context"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

// GitHubIngest handles GitHub-specific event ingestion.
type GitHubIngest struct {
	coreIngest domain.CoreIngestService
}

// NewGitHubIngest creates a new GitHubIngest service.
func NewGitHubIngest(coreIngest domain.CoreIngestService) domain.GitHubIngestService {
	return &GitHubIngest{coreIngest: coreIngest}
}

// IngestGitHubEvent processes GitHub webhook events and delegates to CoreIngestService.
func (g *GitHubIngest) IngestGitHubEvent(ctx context.Context, req domain.IngestRequest) error {
	start := time.Now()
	if req.Source != "github" {
		log.Printf("RecordID: %s - Invalid GitHub ingest source: %s", req.RecordID, req.Source)
		return fmt.Errorf("invalid source for GitHub ingest: %s", req.Source)
	}

	// Validate content
	if strings.TrimSpace(req.Content) == "" {
		log.Printf("RecordID: %s - Empty GitHub content in %.3fs", req.RecordID, time.Since(start).Seconds())
		return fmt.Errorf("empty content for GitHub ingest")
	}

	// Validate RecordID (must match X-GitHub-Delivery format)
	if !strings.Contains(req.RecordID, "-") {
		log.Printf("RecordID: %s - Invalid GitHub delivery ID in %.3fs", req.RecordID, time.Since(start).Seconds())
		return fmt.Errorf("invalid GitHub delivery ID: %s", req.RecordID)
	}

	err := g.coreIngest.Ingest(ctx, req)
	if err != nil {
		log.Printf("RecordID: %s - Failed to ingest GitHub event in %.3fs: %v", req.RecordID, time.Since(start).Seconds(), err)
		return err
	}
	log.Printf("RecordID: %s - Successfully ingested GitHub event in %.3fs", req.RecordID, time.Since(start).Seconds())
	return nil
}

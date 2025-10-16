// services/slack.go
// Package services implements the SlackIngestService for processing Slack webhook events.
// It validates event data, sanitizes content, and delegates to CoreIngestService for storage
// and publishing. Supports edge cases like empty content and invalid event types.

package services

import (
	"context"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

// SlackIngest handles Slack-specific event ingestion, validating events before delegating to CoreIngestService.
type SlackIngest struct {
	coreIngest domain.CoreIngestService // Shared ingestion service
}

// NewSlackIngest creates a new SlackIngest service with the provided CoreIngestService.
// Args:
//
//	coreIngest: CoreIngestService for storage and publishing.
//
// Returns:
//
//	SlackIngestService implementation.
func NewSlackIngest(coreIngest domain.CoreIngestService) domain.SlackIngestService {
	return &SlackIngest{coreIngest: coreIngest}
}

// IngestSlackEvent validates and processes Slack webhook events, delegating to CoreIngestService.
// It ensures the source is 'slack', validates content, record_id (event_ts), and event_type.
// Args:
//
//	ctx: Context for cancellation and timeouts.
//	req: IngestRequest with source, event_type, content, payload, record_id, created_at.
//
// Returns:
//
//	error if validation or ingestion fails.
func (s *SlackIngest) IngestSlackEvent(ctx context.Context, req domain.IngestRequest) error {
	start := time.Now()
	// Validate source
	if req.Source != "slack" {
		log.Printf("RecordID: %s - Invalid Slack ingest source: %s in %.3fs", req.RecordID, req.Source, time.Since(start).Seconds())
		return fmt.Errorf("invalid source for Slack ingest: %s", req.Source)
	}

	// Validate content
	content := strings.TrimSpace(req.Content)
	if content == "" {
		log.Printf("RecordID: %s - Empty Slack content in %.3fs", req.RecordID, time.Since(start).Seconds())
		return fmt.Errorf("empty content for Slack ingest")
	}

	// Validate record_id (event_ts format, e.g., 1760533260.035849)
	if req.RecordID == "" || !strings.Contains(req.RecordID, ".") {
		log.Printf("RecordID: %s - Invalid Slack event_ts in %.3fs", req.RecordID, time.Since(start).Seconds())
		return fmt.Errorf("invalid Slack event_ts: %s", req.RecordID)
	}

	// Validate event type
	if req.EventType != "message" && req.EventType != "app_mention" {
		log.Printf("RecordID: %s - Unsupported event type %s in %.3fs", req.RecordID, req.EventType, time.Since(start).Seconds())
		return fmt.Errorf("unsupported event type: %s", req.EventType)
	}

	// Delegate to CoreIngestService
	err := s.coreIngest.Ingest(ctx, req)
	if err != nil {
		log.Printf("RecordID: %s - Failed to ingest Slack event (%s) in %.3fs: %v", req.RecordID, req.EventType, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to ingest Slack event: %v", err)
	}

	log.Printf("RecordID: %s - Successfully ingested Slack event (%s) in %.3fs", req.RecordID, req.EventType, time.Since(start).Seconds())
	return nil
}

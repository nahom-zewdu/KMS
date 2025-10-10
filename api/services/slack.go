// services/slack.go
package services

import (
	"context"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

// SlackIngest handles Slack-specific event ingestion.
type SlackIngest struct {
	coreIngest domain.CoreIngestService
}

// NewSlackIngest creates a new SlackIngest service.
func NewSlackIngest(coreIngest domain.CoreIngestService) domain.SlackIngestService {
	return &SlackIngest{coreIngest: coreIngest}
}

// IngestSlackEvent processes Slack events and delegates to CoreIngestService.
func (s *SlackIngest) IngestSlackEvent(ctx context.Context, req domain.IngestRequest) error {
	start := time.Now()
	if req.Source != "slack" {
		log.Printf("RecordID: %s - Invalid Slack ingest source: %s", req.RecordID, req.Source)
		return fmt.Errorf("invalid source for Slack ingest: %s", req.Source)
	}

	// Validate content
	if strings.TrimSpace(req.Content) == "" {
		log.Printf("RecordID: %s - Empty Slack content in %.3fs", req.RecordID, time.Since(start).Seconds())
		return fmt.Errorf("empty content for Slack ingest")
	}

	err := s.coreIngest.Ingest(ctx, req)
	if err != nil {
		log.Printf("RecordID: %s - Failed to ingest Slack event in %.3fs: %v", req.RecordID, time.Since(start).Seconds(), err)
		return err
	}
	log.Printf("RecordID: %s - Successfully ingested Slack event in %.3fs", req.RecordID, time.Since(start).Seconds())
	return nil
}

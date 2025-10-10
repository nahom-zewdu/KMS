// services/core.go
package services

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
)

// CoreIngest implements the CoreIngestService for shared ingestion logic.
type CoreIngest struct {
	storage domain.StoragePort
	redis   domain.RedisStream
}

// NewCoreIngest creates a new CoreIngest service.
func NewCoreIngest(storage domain.StoragePort, redis domain.RedisStream) domain.CoreIngestService {
	return &CoreIngest{
		storage: storage,
		redis:   redis,
	}
}

// Ingest stores an event in Supabase and publishes it to a Redis stream.
func (c *CoreIngest) Ingest(ctx context.Context, req domain.IngestRequest) error {
	start := time.Now()
	// Ensure record ID is unique
	recordID := req.RecordID
	if recordID == "" {
		recordID = uuid.New().String()
	}
	// Default to unknown source if not specified
	if req.Source == "" {
		req.Source = "unknown"
	}
	// Default to current time if not provided
	if req.CreatedAt.IsZero() {
		req.CreatedAt = time.Now().UTC()
	}

	// Store in Supabase raw_data table
	err := c.storage.Insert(ctx, "raw_data", map[string]interface{}{
		"id":         recordID,
		"source":     req.Source,
		"content":    req.Content,
		"record_id":  recordID,
		"created_at": req.CreatedAt.Format(time.RFC3339),
	})
	if err != nil {
		log.Printf("RecordID: %s - Failed to store %s raw_data in %.3fs: %v", recordID, req.Source, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to store %s raw_data: %v", req.Source, err)
	}
	log.Printf("RecordID: %s - Stored %s raw_data in %.3fs", recordID, req.Source, time.Since(start).Seconds())

	// Publish to source-specific Redis stream
	streamName := req.Source + "_jobs" // e.g., slack_jobs, github_jobs
	err = c.redis.Publish(ctx, streamName, domain.JobPayload{
		ID:        "*",
		RecordID:  recordID,
		Source:    req.Source,
		Content:   req.Content,
		CreatedAt: req.CreatedAt.Format(time.RFC3339),
	})
	if err != nil {
		log.Printf("RecordID: %s - Failed to publish to %s in %.3fs: %v", recordID, streamName, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to publish to %s: %v", streamName, err)
	}
	log.Printf("RecordID: %s - Published to %s in %.3fs", recordID, streamName, time.Since(start).Seconds())

	return nil
}

// services/core.go
// Package services implements the CoreIngestService for shared ingestion logic across Slack and GitHub.
// It stores raw event payloads in Supabase (events table), summarized content (raw_data), and publishes
// to Redis streams for Python processing. It ensures idempotency using delivery_id, handles edge cases
// (large payloads, duplicates), and maintains compatibility with existing Slack features.

package services

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
)

// CoreIngest implements the CoreIngestService interface for shared ingestion logic.
type CoreIngest struct {
	storage domain.StoragePort // Supabase storage
	redis   domain.RedisStream // Redis stream publisher
}

// NewCoreIngest creates a new CoreIngest service with the provided storage and Redis dependencies.
// Args:
//
//	storage: Supabase storage interface for inserting/querying data.
//	redis: Redis stream interface for publishing events.
//
// Returns:
//
//	CoreIngestService implementation.
func NewCoreIngest(storage domain.StoragePort, redis domain.RedisStream) domain.CoreIngestService {
	return &CoreIngest{
		storage: storage,
		redis:   redis,
	}
}

// Ingest stores an event in Supabase (events, raw_data) and publishes to a Redis stream.
// It validates the source, ensures idempotency using delivery_id, and handles large payloads.
// Args:
//
//	ctx: Context for cancellation and timeouts.
//	req: IngestRequest with source, event_type, content, payload, record_id, and created_at.
//
// Returns:
//
//	error if validation, storage, or publishing fails.
func (c *CoreIngest) Ingest(ctx context.Context, req domain.IngestRequest) error {
	start := time.Now()
	// Use provided record ID (e.g., Slack event_ts)
	if req.RecordID == "" {
		log.Printf("RecordID: <none> - Empty record ID in %.3fs", time.Since(start).Seconds())
		return fmt.Errorf("record_id cannot be empty")
	}
	log.Printf("RecordID: %s - Starting ingestion for %s event (%s)", req.RecordID, req.Source, req.EventType)

	// Validate source
	if req.Source != "slack" && req.Source != "github" {
		log.Printf("RecordID: %s - Invalid source %s in %.3fs", req.RecordID, req.Source, time.Since(start).Seconds())
		return fmt.Errorf("invalid source: %s, must be 'slack' or 'github'", req.Source)
	}

	// Sanitize content
	content := strings.TrimSpace(strings.ReplaceAll(req.Content, "\n", " "))
	if content == "" {
		log.Printf("RecordID: %s - Empty content after sanitization in %.3fs", req.RecordID, time.Since(start).Seconds())
		return fmt.Errorf("content cannot be empty")
	}

	// Default to current time if not provided
	if req.CreatedAt.IsZero() {
		req.CreatedAt = time.Now().UTC()
	}

	// Truncate payload if too large (e.g., push with >20 commits)
	truncated := false
	payload := req.Payload
	if req.EventType == "push" {
		if commits, ok := payload["commits"].([]interface{}); ok && len(commits) > 20 {
			truncated = true
			payload["commits"] = commits[:20]
			log.Printf("RecordID: %s - Truncated commits to 20 for %s event", req.RecordID, req.EventType)
		}
	}

	// Marshal payload for storage
	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		log.Printf("RecordID: %s - Failed to marshal payload in %.3fs: %v", req.RecordID, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to marshal payload: %v", err)
	}

	// Check for duplicate delivery (idempotency)
	existing, err := c.storage.Query(ctx, "events", map[string]interface{}{"delivery_id": req.RecordID})
	if err != nil {
		log.Printf("RecordID: %s - Failed to check duplicate delivery in %.3fs: %v", req.RecordID, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to check duplicate delivery: %v", err)
	}
	if len(existing) > 0 {
		log.Printf("RecordID: %s - Duplicate delivery detected, skipping ingestion", req.RecordID)
		return nil
	}

	// Store raw payload in events table
	eventID := uuid.New().String()
	err = c.storage.Insert(ctx, "events", map[string]interface{}{
		"id":          eventID,
		"source":      req.Source,
		"event_type":  req.EventType,
		"payload":     string(payloadBytes),
		"delivery_id": req.RecordID,
		"processed":   false,
		"truncated":   truncated,
		"created_at":  req.CreatedAt.Format(time.RFC3339),
	})
	if err != nil {
		log.Printf("RecordID: %s - Failed to insert into events in %.3fs: %v", req.RecordID, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to insert into events: %v", err)
	}
	log.Printf("RecordID: %s - Stored %s event (%s) in events table in %.3fs", req.RecordID, req.Source, req.EventType, time.Since(start).Seconds())

	// Store summarized content in raw_data
	err = c.storage.Insert(ctx, "raw_data", map[string]interface{}{
		"id":         uuid.New().String(),
		"source":     req.Source,
		"content":    content,
		"record_id":  req.RecordID,
		"event_id":   eventID,
		"created_at": req.CreatedAt.Format(time.RFC3339),
	})
	if err != nil {
		log.Printf("RecordID: %s - Failed to store %s raw_data in %.3fs: %v", req.RecordID, req.Source, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to store %s raw_data: %v", req.Source, err)
	}
	log.Printf("RecordID: %s - Stored %s raw_data in %.3fs", req.RecordID, req.Source, time.Since(start).Seconds())

	// Create a separate context with timeout for publishing
	publishCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Publish to Redis stream
	streamName := req.Source + "_jobs"
	err = c.redis.Publish(publishCtx, streamName, domain.JobPayload{
		ID:        "*",
		RecordID:  req.RecordID,
		Source:    req.Source,
		EventType: req.EventType,
		Content:   content,
		Payload:   payload, // Pass raw map for Python
		CreatedAt: req.CreatedAt.Format(time.RFC3339),
	})
	if err != nil {
		log.Printf("RecordID: %s - Failed to publish to %s in %.3fs: %v", req.RecordID, streamName, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to publish to %s: %v", streamName, err)
	}
	log.Printf("RecordID: %s - Published to %s in %.3fs", req.RecordID, streamName, time.Since(start).Seconds())

	return nil
}

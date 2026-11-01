// services/core.go
// Package services implements shared Slack and GitHub ingestion logic.
// Event data and jobs are persisted atomically; a separate dispatcher publishes
// the outbox to Redis at least once.

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
	storage domain.StoragePort
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
func NewCoreIngest(storage domain.StoragePort, _ domain.RedisStream) domain.CoreIngestService {
	return &CoreIngest{
		storage: storage,
	}
}

// Ingest transactionally stores the event, raw data, and an outbox record.
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

	companyID := req.CompanyID
	companyID = strings.TrimSpace(companyID)
	if companyID == "" || strings.EqualFold(companyID, "default") {
		log.Printf("RecordID: %s - Missing company ID in %.3fs", req.RecordID, time.Since(start).Seconds())
		return fmt.Errorf("company_id must resolve to a real company")
	}

	eventID := uuid.New().String()
	event := map[string]interface{}{
		"id":          eventID,
		"source":      req.Source,
		"event_type":  req.EventType,
		"payload":     json.RawMessage(payloadBytes),
		"delivery_id": req.RecordID,
		"company_id":  companyID,
		"processed":   false,
		"truncated":   truncated,
		"created_at":  req.CreatedAt.Format(time.RFC3339),
	}

	rawData := map[string]interface{}{
		"id":         uuid.New().String(),
		"source":     req.Source,
		"content":    content,
		"record_id":  req.RecordID,
		"event_id":   eventID,
		"company_id": companyID,
		"created_at": req.CreatedAt.Format(time.RFC3339),
	}

	outbox, ok := c.storage.(domain.IngestionOutboxRepository)
	if !ok {
		return fmt.Errorf("storage does not support transactional ingestion outbox")
	}
	err = outbox.PersistIngestion(ctx, event, rawData, domain.JobPayload{
		ID:        "*",
		RecordID:  req.RecordID,
		Source:    req.Source,
		EventType: req.EventType,
		Content:   content,
		CompanyID: companyID,
		Payload:   payload, // Pass raw map for Python
		CreatedAt: req.CreatedAt.Format(time.RFC3339),
	})
	if err != nil {
		log.Printf("RecordID: %s - Failed to persist ingestion and outbox atomically in %.3fs: %v", req.RecordID, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to persist ingestion and outbox: %w", err)
	}
	log.Printf("RecordID: %s - Persisted event, raw data, and outbox in %.3fs", req.RecordID, time.Since(start).Seconds())

	return nil
}

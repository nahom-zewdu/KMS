// repository/ingest.go
package repository

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

// IngestRepository implements the IngestRepository interface for Supabase storage.
type IngestRepository struct {
	storage domain.StoragePort
}

// NewIngestRepository creates a new IngestRepository.
func NewIngestRepository(storage domain.StoragePort) domain.IngestRepository {
	return &IngestRepository{storage: storage}
}

// IngestRepo stores a JobPayload in the Supabase raw_data table.
func (r *IngestRepository) IngestRepo(ctx context.Context, data domain.JobPayload) error {
	start := time.Now()
	if data.RecordID == "" {
		log.Printf("RecordID: <none> - Empty record ID in %.3fs", time.Since(start).Seconds())
		return fmt.Errorf("empty record ID for ingest")
	}
	if data.Source != "slack" && data.Source != "github" {
		log.Printf("RecordID: %s - Invalid source: %s in %.3fs", data.RecordID, data.Source, time.Since(start).Seconds())
		return fmt.Errorf("invalid source for ingest: %s", data.Source)
	}
	if data.Content == "" {
		log.Printf("RecordID: %s - Empty content in %.3fs", data.RecordID, time.Since(start).Seconds())
		return fmt.Errorf("empty content for ingest")
	}

	err := r.storage.Insert(ctx, "raw_data", map[string]interface{}{
		"id":         data.RecordID,
		"source":     data.Source,
		"content":    data.Content,
		"record_id":  data.RecordID,
		"created_at": data.CreatedAt,
	})
	if err != nil {
		log.Printf("RecordID: %s - Failed to insert %s raw_data in %.3fs: %v", data.RecordID, data.Source, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to insert %s raw_data: %v", data.Source, err)
	}
	log.Printf("RecordID: %s - Successfully inserted %s raw_data in %.3fs", data.RecordID, data.Source, time.Since(start).Seconds())
	return nil
}

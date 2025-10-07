package repository

import (
	"context"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
)

type IngestRepository struct {
	storage domain.StoragePort
}

func NewIngestRepository(storage domain.StoragePort) domain.IngestRepository {
	return &IngestRepository{storage: storage}
}

func (sr *IngestRepository) IngestRepo(ctx context.Context, job domain.JobPayload) error {

	insertPayload := map[string]interface{}{
		"id":        uuid.New().String(),
		"source":    job.Source,
		"content":   job.Content,
		"record_id": job.RecordID,
		"entity_id": func() interface{} {
			if job.EntityID == "" {
				return nil
			}
			return job.EntityID
		}(),
		"created_at": job.CreatedAt,
	}

	return sr.storage.Insert(ctx, "raw_data", insertPayload)
}

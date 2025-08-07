package repository

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
)

type SlackRepo struct {
	storage domain.StoragePort
}

func NewSlackRepo(storage domain.StoragePort) domain.SlackRepository {
	return &SlackRepo{storage: storage}
}

func (sr *SlackRepo) IngestRepo(ctx context.Context, data domain.IngestRequest) error {
	id := uuid.New().String()
	now := time.Now().UTC()

	insertPayload := map[string]interface{}{
		"id":      id,
		"source":  data.Source,
		"content": data.Content,
		"entity_id": func() interface{} {
			if data.EntityID == "" {
				return nil
			}
			return data.EntityID
		}(),
		"created_at": now,
	}

	return sr.storage.Insert(ctx, "raw_data", insertPayload)
}

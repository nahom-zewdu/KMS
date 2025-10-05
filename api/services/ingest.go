package services

import (
	"context"
	"log"
	"time"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
)

type IngestService struct {
	repo  domain.IngestRepository
	redis domain.RedisStream
}

func NewIngestService(repo domain.IngestRepository, redis domain.RedisStream) domain.IngestService {
	return &IngestService{
		repo:  repo,
		redis: redis,
	}
}

func (ss *IngestService) IngestService(ctx context.Context, data domain.IngestRequest) error {
	var job domain.JobPayload

	job.ID = "*"
	job.RecordID = uuid.New().String()
	job.Source = data.Source
	job.Content = data.Content

	if data.EntityID != "" {
		job.EntityID = data.EntityID
	}
	job.CreatedAt = time.Now().UTC().Format(time.RFC3339)

	err := ss.repo.IngestRepo(ctx, job)
	if err != nil {
		return err
	}

	err = ss.redis.Publish(ctx, "slack_jobs", job)
	if err != nil {
		log.Printf("Redis publish failed, but data stored in Supabase: %v", err)
		return err
	}

	return nil
}

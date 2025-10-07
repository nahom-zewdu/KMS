package services

import (
	"context"
	"log"
	"time"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/redis/go-redis/v9"
)

type IngestService struct {
	repo  domain.IngestRepository
	redis *redis.Client
}

func NewIngestService(repo domain.IngestRepository, redis *redis.Client) domain.IngestService {
	return &IngestService{
		repo:  repo,
		redis: redis,
	}
}

func (ss *IngestService) IngestService(ctx context.Context, data domain.IngestRequest) error {
	job := domain.JobPayload{
		ID:        "*",
		RecordID:  uuid.New().String(),
		Source:    data.Source,
		Content:   data.Content,
		EntityID:  data.EntityID,
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	}

	// Insert to Supabase
	err := ss.repo.IngestRepo(ctx, job)
	if err != nil {
		log.Printf("Failed to ingest to Supabase: %v", err)
		return err
	}

	// Publish to slack_jobs
	maxRetries := 3
	backoff := 500 * time.Millisecond
	for attempt := 1; attempt <= maxRetries; attempt++ {
		if ctx.Err() != nil {
			log.Printf("Attempt %d: Context canceled before publishing to slack_jobs: %v", attempt, ctx.Err())
			return ctx.Err()
		}
		err = ss.redis.XAdd(ctx, &redis.XAddArgs{
			Stream: "slack_jobs",
			ID:     "*",
			Values: map[string]interface{}{
				"record_id":  job.RecordID,
				"source":     job.Source,
				"content":    job.Content,
				"created_at": job.CreatedAt,
			},
		}).Err()
		if err == nil {
			log.Printf("Successfully published to slack_jobs")
			return nil
		}
		log.Printf("Attempt %d: Failed to publish to slack_jobs: %v", attempt, err)
		if attempt == maxRetries {
			log.Printf("Failed to publish to slack_jobs after %d attempts, but data stored in Supabase", maxRetries)
			return nil // Allow ingestion to succeed
		}
		time.Sleep(backoff)
		backoff *= 2
	}
	return nil
}

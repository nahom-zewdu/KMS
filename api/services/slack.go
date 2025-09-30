package services

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
)

type SlackService struct {
	repo  domain.SlackRepository
	redis domain.RedisStream
}

func NewSlackService(repo domain.SlackRepository, redis domain.RedisStream) domain.SlackService {
	return &SlackService{
		repo:  repo,
		redis: redis,
	}
}

func (ss *SlackService) IngestService(ctx context.Context, data domain.IngestRequest) error {
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
		return err
	}

	return nil
}

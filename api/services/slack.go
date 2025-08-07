package services

import (
	"context"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type SlackService struct {
	repo domain.SlackRepository
}

func NewSlackService(repo domain.SlackRepository) domain.SlackService {
	return &SlackService{
		repo: repo,
	}
}

func (ss *SlackService) IngestService(ctx context.Context, data domain.IngestRequest) error {

	err := ss.repo.IngestRepo(ctx, data)
	if err != nil {
		return err
	}

	return nil
}

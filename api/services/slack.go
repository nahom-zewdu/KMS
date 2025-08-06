package services

import (
	"context"

	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/nahom-zewdu/kMS/api/repository"
)

type SlackService struct {
	repo repository.SlackRepo
}

func NewSlackService(repo repository.SlackRepo) domain.SlackService {
	return &SlackService{
		repo: repo,
	}
}

func (ss *SlackService) GetMessage(ctx context.Context, id string) (*domain.SlackMessage, error) {

	message, err := ss.repo.GetMessage(ctx, id)
	if err != nil {
		return nil, err
	}
	if message != nil {
		return message, nil
	}

	return nil, nil
}

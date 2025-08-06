package repository

import (
	"context"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type SlackRepo struct {
	message domain.SlackMessage
}

func NewSlackRepo(message domain.SlackMessage) domain.SlackRepository {
	return &SlackRepo{
		message: message,
	}
}

func (sr *SlackRepo) GetMessage(ctx context.Context, id string) (*domain.SlackMessage, error) {

	if sr.message.ID == id {
		return &sr.message, nil
	}

	return nil, nil
}

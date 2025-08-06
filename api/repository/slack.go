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
	message := domain.SlackMessage{
		ID:      id,
		UserID:  "user123",
		Text:    "This is a sample message",
		Channel: "general",
	}

	return &message, nil

}

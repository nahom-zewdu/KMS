package domain

import (
	"context"
)

type SlackMessage struct {
	ID      string `json:"id"`
	UserID  string `json:"user_id"`
	Text    string `json:"text"`
	Channel string `json:"channel"`
}

type SlackRepository interface {
	GetMessage(ctx context.Context, id string) (*SlackMessage, error)
}

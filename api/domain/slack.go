package domain

import (
	"context"
)

type SlackEvent struct {
	Token     string       `json:"token"`
	TeamID    string       `json:"team_id"`
	APIAppID  string       `json:"api_app_id"`
	Event     SlackMessage `json:"event"`
	Type      string       `json:"type"`
	EventID   string       `json:"event_id"`
	EventTime int64        `json:"event_time"`
}

type SlackMessage struct {
	ClientMsgID string `json:"client_msg_id"`
	Type        string `json:"type"`
	Text        string `json:"text"`
	User        string `json:"user"`
	Ts          string `json:"ts"`
	Channel     string `json:"channel"`
	EventTs     string `json:"event_ts"`
}

type IngestRequest struct {
	Source   string `json:"source" binding:"required,oneof=slack"`
	Content  string `json:"content" binding:"required"`
	EntityID string `json:"entity_id,omitempty"`
}

type SlackRepository interface {
	IngestRepo(ctx context.Context, data JobPayload) error
}

type IngestService interface {
	IngestService(ctx context.Context, data IngestRequest) error
}

// New interface for Slack Bot Service
type SlackBotService interface {
	HandleEvent(ctx context.Context, teamID, channel, threadTs, query string) error
}

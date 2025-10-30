// domain/slack.go
package domain

import "context"

// SlackEvent represents a Slack webhook event payload.
type SlackEvent struct {
	Token     string       `json:"token"`
	TeamID    string       `json:"team_id"`
	APIAppID  string       `json:"api_app_id"`
	Event     SlackMessage `json:"event"`
	Type      string       `json:"type"`
	EventID   string       `json:"event_id"`
	EventTime int64        `json:"event_time"`
}

// SlackMessage represents a Slack message event.
type SlackMessage struct {
	ClientMsgID string `json:"client_msg_id"`
	Type        string `json:"type"`
	Text        string `json:"text"`
	User        string `json:"user"`
	Ts          string `json:"ts"`
	Channel     string `json:"channel"`
	EventTs     string `json:"event_ts"`
	ThreadTs    string `json:"thread_ts"`
}

// SlackIngestService defines the interface for ingesting Slack events.
type SlackIngestService interface {
	IngestSlackEvent(ctx context.Context, req IngestRequest) error
}

// SlackBotService defines the interface for Slack bot interactions.
type SlackBotService interface {
	HandleEvent(ctx context.Context, teamID, channel, threadTs, query, eventTs string) error
	GetBotID() string
}

package models

type SlackMessage struct {
	ID      string `json:"id"`
	UserID  string `json:"user_id"`
	Text    string `json:"text"`
	Channel string `json:"channel"`
}

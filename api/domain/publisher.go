package domain

import "context"

type JobPayload struct {
	ID        string `json:"id"`
	RecordID  string `json:"record_id" binding:"required"`
	Source    string `json:"source" binding:"required,oneof=slack"`
	Content   string `json:"content" binding:"required"`
	EntityID  string `json:"entity_id,omitempty"`
	CreatedAt string `json:"created_at" binding:"required"`
}

type Publisher interface {
	Publish(ctx context.Context, stream string, payload JobPayload) error
}

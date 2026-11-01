package domain

import "context"

type IngestionOutboxRecord struct {
	ID      string
	Payload JobPayload
}

type IngestionOutboxRepository interface {
	PersistIngestion(ctx context.Context, event, rawData map[string]interface{}, job JobPayload) error
	ClaimIngestionOutbox(ctx context.Context, workerID string, limit int) ([]IngestionOutboxRecord, error)
	MarkIngestionOutboxPublished(ctx context.Context, id, workerID string) error
	FailIngestionOutbox(ctx context.Context, id, workerID, failure string) error
}

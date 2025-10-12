// domain/domain.go

package domain

import (
	"context"
	"time"
)

// IngestRequest represents a request to ingest an event from any source.
type IngestRequest struct {
	Source    string    `json:"source" binding:"required,oneof=slack github jira"`
	Content   string    `json:"content" binding:"required"`
	RecordID  string    `json:"record_id" binding:"required"`
	CreatedAt time.Time `json:"created_at"`
}

// JobPayload represents the data published to Redis streams.
type JobPayload struct {
	ID        string `json:"id"`
	RecordID  string `json:"record_id" binding:"required"`
	Source    string `json:"source" binding:"required,oneof=slack github jira"`
	Content   string `json:"content" binding:"required"`
	CreatedAt string `json:"created_at" binding:"required"`
}

// CoreIngestService defines the interface for shared ingestion logic (Supabase storage, Redis publishing).
type CoreIngestService interface {
	Ingest(ctx context.Context, req IngestRequest) error
}

// RedisStream defines the interface for Redis stream and caching operations.
type RedisStream interface {
	Publish(ctx context.Context, stream string, payload JobPayload) error
	CacheGet(ctx context.Context, key string) (string, error)
	CacheSet(ctx context.Context, key, value string, ttl time.Duration) error
	Subscribe(ctx context.Context, channel string) (<-chan string, error)
}

// StoragePort defines the interface for storage operations (Supabase).
type StoragePort interface {
	Insert(ctx context.Context, table string, data map[string]interface{}) error
	QueryKnowledgeGraphSupabase(ctx context.Context, query string) (string, error)
}

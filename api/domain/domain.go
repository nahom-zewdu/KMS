// domain/domain.go
package domain

import (
	"context"
	"time"
)

// IngestRequest represents a request to ingest an event from any source.
type IngestRequest struct {
	Source    string                 `json:"source" binding:"required,oneof=slack github"`
	EventType string                 `json:"event_type" binding:"required"` // e.g., push, pull_request
	Content   string                 `json:"content" binding:"required"`
	Payload   map[string]interface{} `json:"payload"` // Raw JSON payload
	RecordID  string                 `json:"record_id" binding:"required"`
	CreatedAt time.Time              `json:"created_at"`
}

// JobPayload represents the data published to Redis streams.
type JobPayload struct {
	ID        string                 `json:"id"`
	RecordID  string                 `json:"record_id" binding:"required"`
	Source    string                 `json:"source" binding:"required,oneof=slack github"`
	EventType string                 `json:"event_type" binding:"required"`
	Content   string                 `json:"content" binding:"required"`
	Payload   map[string]interface{} `json:"payload"` // Raw JSON payload
	CreatedAt string                 `json:"created_at" binding:"required"`
}

// Contribution represents metrics for a PERSON in a PROJECT.
type Contribution struct {
	ID          string    `json:"id"`
	PersonName  string    `json:"person_name"`
	RepoName    string    `json:"repo_name"`
	CommitCount int       `json:"commit_count"`
	PrCount     int       `json:"pr_count"`
	IssueCount  int       `json:"issue_count"`
	BusFactor   float64   `json:"bus_factor"`
	UpdatedAt   time.Time `json:"updated_at"`
}

// CoreIngestService defines the interface for shared ingestion logic.
type CoreIngestService interface {
	Ingest(ctx context.Context, req IngestRequest) error
}

// RedisStream defines the interface for Redis operations.
type RedisStream interface {
	Publish(ctx context.Context, stream string, payload JobPayload) error
	CacheGet(ctx context.Context, key string) (string, error)
	CacheSet(ctx context.Context, key, value string, ttl time.Duration) error
	Subscribe(ctx context.Context, channel string) (<-chan string, error)
}

// StoragePort defines the interface for storage operations.
type StoragePort interface {
	Insert(ctx context.Context, table string, data map[string]interface{}) error
	Query(ctx context.Context, table string, filter map[string]interface{}) ([]map[string]interface{}, error)
	QueryKnowledgeGraphSupabase(ctx context.Context, query string) (string, error)
}

// MetricsService defines the interface for metrics computation.
type MetricsService interface {
	UpdateContributions(ctx context.Context, req IngestRequest) error
	CalculateBusFactor(ctx context.Context, repoName string) (float64, error)
}

// PlaybookService defines the interface for generating onboarding playbooks.
type PlaybookService interface {
	GeneratePlaybook(ctx context.Context, role string, employeeName string) (string, error)
}

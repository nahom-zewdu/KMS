package domain

import "context"

type StoragePort interface {
	Insert(ctx context.Context, table string, data map[string]interface{}) error
	QueryKnowledgeGraphSupabase(ctx context.Context, query string) (string, error)
}

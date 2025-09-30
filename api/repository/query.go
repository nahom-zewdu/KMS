package repository

import (
	"context"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type QueryRepository struct {
	redis   domain.RedisStream
	storage domain.StoragePort
}

func NewQueryRepository(redis domain.RedisStream, storage domain.StoragePort) domain.QueryRepository {
	return &QueryRepository{
		redis:   redis,
		storage: storage,
	}
}

func (qr *QueryRepository) QueryKnowledgeGraph(ctx context.Context, query string) (string, error) {
	cache, err := qr.redis.CacheGet(ctx, query)
	if err == nil {
		return cache, nil
	}

	result, err := qr.storage.QueryKnowledgeGraphSupabase(ctx, query)
	if err != nil {
		return "", err
	}

	// Cache the result for future queries
	_ = qr.redis.CacheSet(ctx, query, result, 60*5) // Cache for 5 minutes

	return result, nil

}

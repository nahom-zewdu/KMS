// repository/query.go
package repository

import (
	"context"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

// QueryRepository implements the QueryRepository interface for knowledge graph queries.
type QueryRepository struct {
	redis   domain.RedisStream
	storage domain.StoragePort
}

// NewQueryRepository creates a new QueryRepository.
func NewQueryRepository(redis domain.RedisStream, storage domain.StoragePort) domain.QueryRepository {
	return &QueryRepository{
		redis:   redis,
		storage: storage,
	}
}

// QueryKnowledgeGraph retrieves an answer from the knowledge graph, using Redis cache or Supabase.
func (r *QueryRepository) QueryKnowledgeGraph(ctx context.Context, query string) (string, error) {
	start := time.Now()
	if strings.TrimSpace(query) == "" {
		log.Printf("QueryID: <none> - Empty query in %.3fs", time.Since(start).Seconds())
		return "", fmt.Errorf("empty query provided")
	}

	// Generate cache key
	cacheKey := fmt.Sprintf("query:%s", strings.ToLower(strings.TrimSpace(query)))

	// Check Redis cache
	cachedAnswer, err := r.redis.CacheGet(ctx, cacheKey)
	if err == nil && cachedAnswer != "" {
		log.Printf("QueryID: %s - Cache hit in %.3fs", query, time.Since(start).Seconds())
		return cachedAnswer, nil
	}
	log.Printf("QueryID: %s - Cache miss in %.3fs: %v", query, time.Since(start).Seconds(), err)

	// Query Supabase knowledge graph
	answer, err := r.storage.QueryKnowledgeGraphSupabase(ctx, query)
	if err != nil {
		log.Printf("QueryID: %s - Failed to query Supabase in %.3fs: %v", query, time.Since(start).Seconds(), err)
		return "", fmt.Errorf("failed to query knowledge graph: %v", err)
	}
	if answer == "" {
		log.Printf("QueryID: %s - No answer found in Supabase in %.3fs", query, time.Since(start).Seconds())
		return "", fmt.Errorf("no answer found for query: %s", query)
	}

	// Cache answer in Redis (TTL 1 hour)
	err = r.redis.CacheSet(ctx, cacheKey, answer, time.Hour)
	if err != nil {
		log.Printf("QueryID: %s - Failed to cache answer in %.3fs: %v", query, time.Since(start).Seconds(), err)
		// Continue despite cache failure
	}
	log.Printf("QueryID: %s - Cached answer in %.3fs", query, time.Since(start).Seconds())

	log.Printf("QueryID: %s - Successfully queried knowledge graph in %.3fs, answer: %s", query, time.Since(start).Seconds(), answer)
	return answer, nil
}

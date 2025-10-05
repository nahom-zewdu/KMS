package repository

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/redis/go-redis/v9"
)

type RedisStream struct {
	client *redis.Client
}

func NewRedisStream(client *redis.Client) domain.RedisStream {
	return &RedisStream{client: client}
}

func (rs *RedisStream) Publish(ctx context.Context, stream string, job domain.JobPayload) error {
	values := map[string]interface{}{
		"record_id":  job.RecordID,
		"source":     job.Source,
		"content":    job.Content,
		"created_at": job.CreatedAt,
	}
	if job.EntityID != "" {
		values["entity_id"] = job.EntityID
	}

	maxRetries := 3
	backoff := 500 * time.Millisecond
	for attempt := 1; attempt <= maxRetries; attempt++ {
		if ctx.Err() != nil {
			log.Printf("Attempt %d: Context canceled before publishing to %s: %v", attempt, stream, ctx.Err())
			return ctx.Err()
		}

		err := rs.client.XAdd(ctx, &redis.XAddArgs{
			Stream: stream,
			ID:     "*",
			Values: values,
		}).Err()
		if err == nil {
			log.Printf("Successfully published to Redis stream %s", stream)
			return nil
		}

		log.Printf("Attempt %d: Failed to publish to %s: %v", attempt, stream, err)
		if attempt == maxRetries {
			return fmt.Errorf("failed to publish to Redis stream %s after %d attempts: %v", stream, maxRetries, err)
		}
		time.Sleep(backoff)
		backoff *= 2
	}
	return fmt.Errorf("failed to publish to Redis stream %s after %d attempts", stream, maxRetries)
}

func (rs *RedisStream) CacheGet(ctx context.Context, key string) (string, error) {
	val, err := rs.client.Get(ctx, key).Result()
	if err == redis.Nil {
		return "", nil
	}
	if err != nil {
		log.Printf("Failed to get cache key %s: %v", key, err)
		return "", err
	}
	return val, nil
}

func (rs *RedisStream) CacheSet(ctx context.Context, key, value string, ttl time.Duration) error {
	err := rs.client.Set(ctx, key, value, ttl).Err()
	if err != nil {
		log.Printf("Failed to set cache key %s: %v", key, err)
		return err
	}
	log.Printf("Successfully set cache key %s", key)
	return nil
}

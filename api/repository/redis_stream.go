// repository/redis_stream.go
package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/redis/go-redis/v9"
)

// RedisStream implements the RedisStream interface for stream and caching operations.
type RedisStream struct {
	client *redis.Client
}

// NewRedisStream creates a new RedisStream.
func NewRedisStream(client *redis.Client) domain.RedisStream {
	return &RedisStream{client: client}
}

// Publish sends a JobPayload to a Redis stream.
func (r *RedisStream) Publish(ctx context.Context, stream string, payload domain.JobPayload) error {
	start := time.Now()
	if stream != "slack_jobs" && stream != "github_jobs" && stream != "query_jobs" {
		log.Printf("RecordID: %s - Invalid stream: %s in %.3fs", payload.RecordID, stream, time.Since(start).Seconds())
		return fmt.Errorf("invalid stream: %s", stream)
	}
	if payload.RecordID == "" {
		log.Printf("RecordID: <none> - Empty record ID in %.3fs", time.Since(start).Seconds())
		return fmt.Errorf("empty record ID for stream %s", stream)
	}

	data, err := json.Marshal(payload)
	if err != nil {
		log.Printf("RecordID: %s - Failed to marshal payload for %s in %.3fs: %v", payload.RecordID, stream, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to marshal payload for %s: %v", stream, err)
	}

	err = r.client.XAdd(ctx, &redis.XAddArgs{
		Stream: stream,
		ID:     payload.ID,
		Values: map[string]interface{}{"data": string(data)},
	}).Err()
	if err != nil {
		log.Printf("RecordID: %s - Failed to publish to %s in %.3fs: %v", payload.RecordID, stream, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to publish to %s: %v", stream, err)
	}
	log.Printf("RecordID: %s - Successfully published to %s in %.3fs", payload.RecordID, stream, time.Since(start).Seconds())
	return nil
}

// CacheGet retrieves a value from Redis cache.
func (r *RedisStream) CacheGet(ctx context.Context, key string) (string, error) {
	start := time.Now()
	val, err := r.client.Get(ctx, key).Result()
	if err == redis.Nil {
		log.Printf("CacheKey: %s - Cache miss in %.3fs", key, time.Since(start).Seconds())
		return "", nil
	}
	if err != nil {
		log.Printf("CacheKey: %s - Failed to get cache in %.3fs: %v", key, time.Since(start).Seconds(), err)
		return "", fmt.Errorf("failed to get cache for %s: %v", key, err)
	}
	log.Printf("CacheKey: %s - Cache hit in %.3fs", key, time.Since(start).Seconds())
	return val, nil
}

// CacheSet stores a value in Redis cache with a TTL.
func (r *RedisStream) CacheSet(ctx context.Context, key, value string, ttl time.Duration) error {
	start := time.Now()
	err := r.client.Set(ctx, key, value, ttl).Err()
	if err != nil {
		log.Printf("CacheKey: %s - Failed to set cache in %.3fs: %v", key, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to set cache for %s: %v", key, err)
	}
	log.Printf("CacheKey: %s - Successfully set cache in %.3fs", key, time.Since(start).Seconds())
	return nil
}

// Subscribe subscribes to a Redis Pub/Sub channel.
func (r *RedisStream) Subscribe(ctx context.Context, channel string) (<-chan string, error) {
	start := time.Now()
	pubsub := r.client.Subscribe(ctx, channel)
	_, err := pubsub.Receive(ctx)
	if err != nil {
		log.Printf("Channel: %s - Failed to subscribe in %.3fs: %v", channel, time.Since(start).Seconds(), err)
		return nil, fmt.Errorf("failed to subscribe to %s: %v", channel, err)
	}

	// Create a channel to forward messages
	msgChan := make(chan string)
	go func() {
		defer pubsub.Close()
		for {
			select {
			case <-ctx.Done():
				log.Printf("Channel: %s - Subscription closed in %.3fs", channel, time.Since(start).Seconds())
				close(msgChan)
				return
			case msg, ok := <-pubsub.Channel():
				if !ok {
					log.Printf("Channel: %s - Pub/Sub channel closed in %.3fs", channel, time.Since(start).Seconds())
					close(msgChan)
					return
				}
				log.Printf("Channel: %s - Received message in %.3fs: %s", channel, time.Since(start).Seconds(), msg.Payload)
				select {
				case msgChan <- msg.Payload:
				case <-ctx.Done():
					log.Printf("Channel: %s - Subscription closed during message send in %.3fs", channel, time.Since(start).Seconds())
					close(msgChan)
					return
				}
			}
		}
	}()

	log.Printf("Channel: %s - Successfully subscribed in %.3fs", channel, time.Since(start).Seconds())
	return msgChan, nil
}

package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type RedisStream struct {
	BaseURL string
	Token   string
	Client  *http.Client
}

func NewRedisStream(baseURL, token string) domain.RedisStream {
	return &RedisStream{
		BaseURL: baseURL,
		Token:   token,
		Client:  &http.Client{},
	}
}

func (rs *RedisStream) Publish(ctx context.Context, stream string, job domain.JobPayload) error {
	id := "*"
	now := time.Now().UTC().Format(time.RFC3339)

	// Build path-based URL
	path := fmt.Sprintf("%s/xadd/%s/%s/record_id/%s/source/%s/content/%s/created_at/%s/",
		rs.BaseURL,
		stream,
		id,
		url.PathEscape(job.RecordID),
		url.PathEscape(job.Source),
		url.PathEscape(job.Content),
		url.PathEscape(now),
	)

	if job.EntityID != "" {
		path += fmt.Sprintf("/entity_id/%s", url.PathEscape(job.EntityID))
	}

	req, err := http.NewRequestWithContext(ctx, "POST", path, nil)
	if err != nil {
		return err
	}

	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", rs.Token))
	req.Header.Set("Content-Type", "application/json")

	resp, err := rs.Client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("failed to publish to Redis stream: %s, response: %s", resp.Status, string(bodyBytes))
	}

	log.Printf("Successfully published to Redis stream %s", stream)

	return nil
}

func (rs *RedisStream) CacheGet(ctx context.Context, key string) (string, error) {
	path := fmt.Sprintf("%s/get/%s", rs.BaseURL, url.PathEscape(key))

	req, err := http.NewRequestWithContext(ctx, "GET", path, nil)
	if err != nil {
		return "", err
	}

	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", rs.Token))
	req.Header.Set("Content-Type", "application/json")

	resp, err := rs.Client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 300 {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("failed to get from Redis cache: %s, response: %s", resp.Status, string(bodyBytes))
	}

	bodyBytes, _ := io.ReadAll(resp.Body)
	var result struct {
		Result string `json:"result"`
	}
	if err := json.Unmarshal(bodyBytes, &result); err != nil {
		return "", err
	}
	return result.Result, nil
}

func (rs *RedisStream) CacheSet(ctx context.Context, key, value string, ttl time.Duration) error {
	seconds := int(ttl.Seconds())
	path := fmt.Sprintf("%s/set/%s/%s/%d", rs.BaseURL, url.PathEscape(key), url.PathEscape(value), seconds)

	req, err := http.NewRequestWithContext(ctx, "POST", path, nil)
	if err != nil {
		return err
	}

	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", rs.Token))
	req.Header.Set("Content-Type", "application/json")

	resp, err := rs.Client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 300 {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("failed to set in Redis cache: %s, response: %s", resp.Status, string(bodyBytes))
	}

	log.Printf("Successfully set cache key %s in Redis", key)
	return nil
}

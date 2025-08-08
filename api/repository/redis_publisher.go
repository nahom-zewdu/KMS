package repository

import (
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"time"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
)

type RedisStreamPublisher struct {
	BaseURL string
	Token   string
	Client  *http.Client
}

func NewRedisStreamPublisher(baseURL, token string) domain.Publisher {
	return &RedisStreamPublisher{
		BaseURL: baseURL,
		Token:   token,
		Client:  &http.Client{},
	}
}

func (rp *RedisStreamPublisher) Publish(ctx context.Context, stream string, job domain.JobPayload) error {
	id := "*"
	recordID := uuid.New().String()
	now := time.Now().UTC().Format(time.RFC3339)

	// Build path-based URL
	path := fmt.Sprintf("%s/xadd/%s/%s/source/%s/content/%s/created_at/%s/record_id/%s",
		rp.BaseURL,
		stream,
		id,
		recordID,
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

	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", rp.Token))
	req.Header.Set("Content-Type", "application/json")

	resp, err := rp.Client.Do(req)
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

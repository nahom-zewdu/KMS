package services

import (
	"context"
	"testing"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type baselineRedis struct {
	stream  string
	payload domain.JobPayload
}

func (r *baselineRedis) Publish(_ context.Context, stream string, payload domain.JobPayload) error {
	r.stream, r.payload = stream, payload
	return nil
}
func (*baselineRedis) CacheGet(context.Context, string) (string, error)              { return "", nil }
func (*baselineRedis) CacheSet(context.Context, string, string, time.Duration) error { return nil }
func (*baselineRedis) Subscribe(context.Context, string) (<-chan string, error) {
	return nil, nil
}

func TestBaselineJobIncludesVerifiedCompanyContext(t *testing.T) {
	redis := &baselineRedis{}
	service := NewCodebaseService(redis)
	if err := service.SyncRepository(context.Background(), "company-a", "org/repo"); err != nil {
		t.Fatalf("SyncRepository() error = %v", err)
	}
	if redis.stream != "codebase_baseline_jobs" {
		t.Fatalf("stream = %q", redis.stream)
	}
	if redis.payload.CompanyID != "company-a" || redis.payload.Payload["company_id"] != "company-a" {
		t.Fatalf("company context missing from queued job: %#v", redis.payload)
	}
	if redis.payload.Payload["repo"] != "org/repo" {
		t.Fatalf("repository = %#v", redis.payload.Payload["repo"])
	}
}

var _ domain.RedisStream = (*baselineRedis)(nil)

package services

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type fakeOutbox struct {
	*idempotencyStorage
	records    []domain.IngestionOutboxRecord
	inFlight   map[string]domain.IngestionOutboxRecord
	failures   []string
	published  []string
	claimError error
	markError  error
	failError  error
}

func newFakeOutbox() *fakeOutbox {
	return &fakeOutbox{idempotencyStorage: &idempotencyStorage{}}
}

func (f *fakeOutbox) PersistIngestion(ctx context.Context, event, rawData map[string]interface{}, job domain.JobPayload) error {
	for _, row := range f.records {
		if row.Payload.RecordID == job.RecordID {
			return nil
		}
	}
	if err := f.idempotencyStorage.PersistIngestion(ctx, event, rawData, job); err != nil {
		return err
	}
	f.records = append(f.records, domain.IngestionOutboxRecord{ID: "outbox-" + job.RecordID, Payload: job})
	return nil
}
func (f *fakeOutbox) ClaimIngestionOutbox(_ context.Context, _ string, _ int) ([]domain.IngestionOutboxRecord, error) {
	if f.claimError != nil {
		return nil, f.claimError
	}
	rows := append([]domain.IngestionOutboxRecord(nil), f.records...)
	f.records = nil
	if f.inFlight == nil {
		f.inFlight = make(map[string]domain.IngestionOutboxRecord)
	}
	for _, row := range rows {
		f.inFlight[row.ID] = row
	}
	return rows, nil
}
func (f *fakeOutbox) MarkIngestionOutboxPublished(_ context.Context, id, _ string) error {
	if f.markError != nil {
		if row, ok := f.inFlight[id]; ok {
			f.records = append(f.records, row)
		}
		return f.markError
	}
	f.published = append(f.published, id)
	delete(f.inFlight, id)
	return nil
}
func (f *fakeOutbox) FailIngestionOutbox(_ context.Context, id, _, failure string) error {
	f.failures = append(f.failures, failure)
	if row, ok := f.inFlight[id]; ok {
		f.records = append(f.records, row)
		delete(f.inFlight, id)
	}
	return f.failError
}

type outboxRedis struct {
	published []domain.JobPayload
	err       error
	ctx       context.Context
	ctxErr    error
}

func (r *outboxRedis) Publish(ctx context.Context, _ string, job domain.JobPayload) error {
	r.ctx = ctx
	r.ctxErr = ctx.Err()
	r.published = append(r.published, job)
	return r.err
}
func (*outboxRedis) CacheGet(context.Context, string) (string, error)              { return "", nil }
func (*outboxRedis) CacheSet(context.Context, string, string, time.Duration) error { return nil }
func (*outboxRedis) Subscribe(context.Context, string) (<-chan string, error)      { return nil, nil }

func TestOutboxRedisFailureLeavesRetryableOutboxFailure(t *testing.T) {
	outbox := newFakeOutbox()
	outbox.records = []domain.IngestionOutboxRecord{
		{ID: "outbox-1", Payload: domain.JobPayload{
			RecordID: "delivery-1", Source: "github", CompanyID: "company-a",
		}},
	}
	redis := &outboxRedis{err: errors.New("redis unavailable")}
	dispatcher := NewIngestionOutboxDispatcher(outbox, redis)

	err := dispatcher.DispatchOnce(context.Background())
	if err == nil || !strings.Contains(err.Error(), "redis unavailable") {
		t.Fatalf("DispatchOnce() error = %v, want Redis failure", err)
	}
	if len(outbox.failures) != 1 || len(outbox.published) != 0 || len(outbox.records) != 1 {
		t.Fatalf("failed dispatch state: failures=%v published=%v retryable=%v", outbox.failures, outbox.published, outbox.records)
	}
	if redis.ctx == nil || redis.ctxErr != nil {
		t.Fatalf("publish should receive a live bounded context, got %v", redis.ctx)
	}
	if deadline, ok := redis.ctx.Deadline(); !ok || time.Until(deadline) > 10*time.Second {
		t.Fatalf("publish timeout missing or exceeds 10 seconds")
	}
}

func TestOutboxPublishBeforeMarkCrashCanRepublishSameDelivery(t *testing.T) {
	job := domain.JobPayload{RecordID: "delivery-1", Source: "slack", CompanyID: "company-a"}
	outbox := newFakeOutbox()
	outbox.records = []domain.IngestionOutboxRecord{{ID: "outbox-1", Payload: job}}
	outbox.markError = errors.New("database unavailable after Redis publish")
	redis := &outboxRedis{}
	dispatcher := NewIngestionOutboxDispatcher(outbox, redis)

	if err := dispatcher.DispatchOnce(context.Background()); err == nil {
		t.Fatal("expected mark-published failure")
	}
	if len(redis.published) != 1 {
		t.Fatalf("first Redis publish count = %d, want 1", len(redis.published))
	}

	outbox.markError = nil
	if err := dispatcher.DispatchOnce(context.Background()); err != nil {
		t.Fatalf("retry dispatch failed: %v", err)
	}
	if len(redis.published) != 2 || redis.published[0].RecordID != redis.published[1].RecordID {
		t.Fatalf("expected duplicate at-least-once publish for same delivery, got %+v", redis.published)
	}
}

func TestPersistenceSucceedsWhileRedisIsUnavailable(t *testing.T) {
	outbox := newFakeOutbox()
	core := NewCoreIngest(outbox, nil)
	request := domain.IngestRequest{
		Source: "github", EventType: "push", Content: "push event",
		RecordID: "delivery-retry", CompanyID: "company-a",
	}
	if err := core.Ingest(context.Background(), request); err != nil {
		t.Fatalf("ingest should persist transactionally without requiring Redis: %v", err)
	}
	if len(outbox.records) != 1 {
		t.Fatalf("pending outbox records = %d, want 1", len(outbox.records))
	}

	redis := &outboxRedis{err: errors.New("redis unavailable")}
	dispatcher := NewIngestionOutboxDispatcher(outbox, redis)
	if err := dispatcher.DispatchOnce(context.Background()); err == nil {
		t.Fatal("expected dispatcher to report Redis outage")
	}
	if len(outbox.records) != 1 || outbox.records[0].Payload.RecordID != "delivery-retry" {
		t.Fatalf("persisted outbox job was not retained for retry: %+v", outbox.records)
	}
}

func TestOutboxRejectsTenantMismatchBeforePublishing(t *testing.T) {
	outbox := newFakeOutbox()
	outbox.records = []domain.IngestionOutboxRecord{{ID: "outbox-1", Payload: domain.JobPayload{
			RecordID: "delivery-1", Source: "github", CompanyID: " default ",
		}}}
	redis := &outboxRedis{}
	dispatcher := NewIngestionOutboxDispatcher(outbox, redis)
	if err := dispatcher.DispatchOnce(context.Background()); err == nil {
		t.Fatal("invalid tenant was accepted")
	}
	if len(redis.published) != 0 || len(outbox.failures) != 1 {
		t.Fatalf("invalid tenant handling published=%d failure=%v", len(redis.published), outbox.failures)
	}
}

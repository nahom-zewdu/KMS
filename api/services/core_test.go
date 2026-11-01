package services

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type idempotencyStorage struct {
	events  []map[string]interface{}
	rawData []map[string]interface{}
	outbox  []domain.JobPayload
	fail    error
}

func (s *idempotencyStorage) PersistIngestion(ctx context.Context, event, rawData map[string]interface{}, job domain.JobPayload) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if s.fail != nil {
		return s.fail
	}
	for _, existing := range s.events {
		if existing["delivery_id"] == event["delivery_id"] {
			return nil
		}
	}
	s.events = append(s.events, event)
	s.rawData = append(s.rawData, rawData)
	s.outbox = append(s.outbox, job)
	return nil
}
func (*idempotencyStorage) ClaimIngestionOutbox(context.Context, string, int) ([]domain.IngestionOutboxRecord, error) {
	return nil, nil
}
func (*idempotencyStorage) MarkIngestionOutboxPublished(context.Context, string, string) error {
	return nil
}
func (*idempotencyStorage) FailIngestionOutbox(context.Context, string, string, string) error {
	return nil
}
func (*idempotencyStorage) Insert(context.Context, string, map[string]interface{}) error {
	return errors.New("individual persistence is not transactional")
}
func (*idempotencyStorage) Query(context.Context, string, map[string]interface{}) ([]map[string]interface{}, error) {
	return nil, errors.New("unsupported query")
}
func (*idempotencyStorage) QueryKnowledgeGraphSupabase(context.Context, string, string) (string, error) {
	return "", nil
}
func (*idempotencyStorage) ResolveCompanyByIntegration(context.Context, string, string) (string, error) {
	return "", nil
}
func (*idempotencyStorage) ResolveCompanyByInstallation(context.Context, string) (string, error) {
	return "", nil
}
func (*idempotencyStorage) AuthenticateUser(context.Context, string) (string, error) {
	return "", domain.ErrUnauthenticated
}
func (*idempotencyStorage) IsCompanyMember(context.Context, string, string) (bool, error) {
	return false, nil
}
func (*idempotencyStorage) ResolveRepositoryForCompany(context.Context, string, string) (string, error) {
	return "", nil
}

type recordingRedis struct {
	published  int
	publishCtx context.Context
}

func (r *recordingRedis) Publish(ctx context.Context, _ string, _ domain.JobPayload) error {
	r.published++
	r.publishCtx = ctx
	if err := ctx.Err(); err != nil {
		return err
	}
	return nil
}
func (*recordingRedis) CacheGet(context.Context, string) (string, error)              { return "", nil }
func (*recordingRedis) CacheSet(context.Context, string, string, time.Duration) error { return nil }
func (*recordingRedis) Subscribe(context.Context, string) (<-chan string, error) {
	return nil, nil
}

func TestDuplicateGitHubDeliveryPersistsOneOutboxJob(t *testing.T) {
	storage := &idempotencyStorage{}
	redis := &recordingRedis{}
	core := NewCoreIngest(storage, redis)
	github := NewGitHubIngest(core)
	request := domain.IngestRequest{
		Source:    "github",
		EventType: "push",
		Content:   "push event",
		Payload:   map[string]interface{}{"delivery_id": "delivery-1"},
		RecordID:  "delivery-1",
		CompanyID: "company-a",
		CreatedAt: time.Now().UTC(),
	}

	if err := github.IngestGitHubEvent(context.Background(), request); err != nil {
		t.Fatalf("first delivery failed: %v", err)
	}
	if err := github.IngestGitHubEvent(context.Background(), request); err != nil {
		t.Fatalf("duplicate delivery failed: %v", err)
	}
	if len(storage.events) != 1 {
		t.Fatalf("stored event count = %d, want 1", len(storage.events))
	}
	if storage.events[0]["company_id"] != "company-a" {
		t.Fatalf("stored event company_id = %v, want company-a", storage.events[0]["company_id"])
	}
	if len(storage.outbox) != 1 {
		t.Fatalf("outbox job count = %d, want 1", len(storage.outbox))
	}
	if _, err := json.Marshal(storage.events[0]); err != nil {
		t.Fatalf("stored event is not serializable: %v", err)
	}
}

func TestCoreIngestPersistenceHonorsParentCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	storage := &idempotencyStorage{}
	core := NewCoreIngest(storage, nil)

	err := core.Ingest(ctx, validIngestRequest())
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("Ingest() error = %v, want context.Canceled", err)
	}
	if len(storage.events) != 0 || len(storage.rawData) != 0 || len(storage.outbox) != 0 {
		t.Fatalf("cancelled transaction persisted partial data: events=%d raw=%d outbox=%d",
			len(storage.events), len(storage.rawData), len(storage.outbox))
	}
}

func TestCoreIngestPersistsEventRawDataAndOutboxTogether(t *testing.T) {
	parentDeadline := time.Now().Add(2 * time.Second)
	ctx, cancel := context.WithDeadline(context.Background(), parentDeadline)
	defer cancel()
	storage := &idempotencyStorage{}
	core := NewCoreIngest(storage, nil)

	if err := core.Ingest(ctx, validIngestRequest()); err != nil {
		t.Fatalf("Ingest() error = %v", err)
	}
	if len(storage.events) != 1 || len(storage.rawData) != 1 || len(storage.outbox) != 1 {
		t.Fatalf("persisted events=%d raw=%d outbox=%d, want one of each",
			len(storage.events), len(storage.rawData), len(storage.outbox))
	}
	if storage.outbox[0].CompanyID != "company-a" || storage.outbox[0].RecordID != "delivery-2" {
		t.Fatalf("outbox tenant/delivery identity = %+v", storage.outbox[0])
	}
}

func validIngestRequest() domain.IngestRequest {
	return domain.IngestRequest{
		Source:    "github",
		EventType: "push",
		Content:   "push event",
		Payload:   map[string]interface{}{},
		RecordID:  "delivery-2",
		CompanyID: "company-a",
		CreatedAt: time.Now().UTC(),
	}
}

var _ domain.StoragePort = (*idempotencyStorage)(nil)
var _ domain.RedisStream = (*recordingRedis)(nil)

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
	events   []map[string]interface{}
	inserts  int
	onInsert func(string)
}

func (s *idempotencyStorage) Insert(_ context.Context, table string, data map[string]interface{}) error {
	s.inserts++
	if s.onInsert != nil {
		s.onInsert(table)
	}
	if table == "events" {
		s.events = append(s.events, data)
	}
	return nil
}
func (s *idempotencyStorage) Query(_ context.Context, table string, filter map[string]interface{}) ([]map[string]interface{}, error) {
	if table != "events" {
		return nil, nil
	}
	deliveryID, ok := filter["delivery_id"]
	if !ok {
		return nil, nil
	}
	var matched []map[string]interface{}
	for _, event := range s.events {
		if event["delivery_id"] == deliveryID {
			matched = append(matched, event)
		}
	}
	return matched, nil
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

func TestDuplicateGitHubDeliveryIsNotReprocessed(t *testing.T) {
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
	if redis.published != 1 {
		t.Fatalf("published job count = %d, want 1", redis.published)
	}
	if _, err := json.Marshal(storage.events[0]); err != nil {
		t.Fatalf("stored event is not serializable: %v", err)
	}
}

func TestCoreIngestPublishHonorsParentCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	storage := &idempotencyStorage{
		onInsert: func(table string) {
			if table == "raw_data" {
				cancel()
			}
		},
	}
	redis := &recordingRedis{}
	core := NewCoreIngest(storage, redis)

	err := core.Ingest(ctx, validIngestRequest())
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("Ingest() error = %v, want context.Canceled", err)
	}
	if redis.publishCtx == nil {
		t.Fatal("Redis publish was not attempted")
	}
	if !errors.Is(redis.publishCtx.Err(), context.Canceled) {
		t.Fatalf("Redis publish context error = %v, want context.Canceled", redis.publishCtx.Err())
	}
}

func TestCoreIngestPublishInheritsParentDeadlineAndTenSecondBound(t *testing.T) {
	parentDeadline := time.Now().Add(2 * time.Second)
	ctx, cancel := context.WithDeadline(context.Background(), parentDeadline)
	defer cancel()
	redis := &recordingRedis{}
	core := NewCoreIngest(&idempotencyStorage{}, redis)

	if err := core.Ingest(ctx, validIngestRequest()); err != nil {
		t.Fatalf("Ingest() error = %v", err)
	}
	gotDeadline, ok := redis.publishCtx.Deadline()
	if !ok {
		t.Fatal("Redis publish context has no deadline")
	}
	if !gotDeadline.Equal(parentDeadline) {
		t.Fatalf("publish deadline = %v, want inherited parent deadline %v", gotDeadline, parentDeadline)
	}

	redis = &recordingRedis{}
	core = NewCoreIngest(&idempotencyStorage{}, redis)
	if err := core.Ingest(context.Background(), validIngestRequest()); err != nil {
		t.Fatalf("Ingest() without parent deadline error = %v", err)
	}
	gotDeadline, ok = redis.publishCtx.Deadline()
	if !ok {
		t.Fatal("Redis publish context has no deadline")
	}
	remaining := time.Until(gotDeadline)
	if remaining <= 0 || remaining > 10*time.Second {
		t.Fatalf("publish deadline remaining = %v, want >0 and <=10s", remaining)
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

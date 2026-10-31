package services

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type idempotencyStorage struct {
	events  []map[string]interface{}
	inserts int
}

func (s *idempotencyStorage) Insert(_ context.Context, table string, data map[string]interface{}) error {
	s.inserts++
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

type recordingRedis struct{ published int }

func (r *recordingRedis) Publish(context.Context, string, domain.JobPayload) error {
	r.published++
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
	if redis.published != 1 {
		t.Fatalf("published job count = %d, want 1", redis.published)
	}
	if _, err := json.Marshal(storage.events[0]); err != nil {
		t.Fatalf("stored event is not serializable: %v", err)
	}
}

var _ domain.StoragePort = (*idempotencyStorage)(nil)
var _ domain.RedisStream = (*recordingRedis)(nil)

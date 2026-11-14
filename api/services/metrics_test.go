package services

import (
	"context"
	"sync"
	"testing"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type recordingMetricsStorage struct {
	domain.StoragePort
	mu      sync.Mutex
	queries []map[string]interface{}
	inserts []map[string]interface{}
}

func (s *recordingMetricsStorage) Insert(_ context.Context, table string, values map[string]interface{}) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if table != "contributions" {
		panic("unexpected insert table: " + table)
	}
	copyValues := make(map[string]interface{}, len(values))
	for key, value := range values {
		copyValues[key] = value
	}
	s.inserts = append(s.inserts, copyValues)
	return nil
}

func (s *recordingMetricsStorage) Query(_ context.Context, table string, filter map[string]interface{}) ([]map[string]interface{}, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if table != "contributions" {
		panic("unexpected query table: " + table)
	}
	copyFilter := make(map[string]interface{}, len(filter))
	for key, value := range filter {
		copyFilter[key] = value
	}
	s.queries = append(s.queries, copyFilter)
	return []map[string]interface{}{
		{"person_name": "engineer", "commit_count": int64(4)},
	}, nil
}

func TestCalculateBusFactorScopesQueryAndUpdateToCompany(t *testing.T) {
	storage := &recordingMetricsStorage{}
	service := &MetricsServiceImpl{storage: storage}

	busFactor, err := service.CalculateBusFactor(context.Background(), "org/repo", "company-a")
	if err != nil {
		t.Fatalf("CalculateBusFactor() error = %v", err)
	}
	if busFactor != 1 {
		t.Fatalf("bus factor = %v, want 1", busFactor)
	}

	storage.mu.Lock()
	defer storage.mu.Unlock()
	if len(storage.queries) != 1 {
		t.Fatalf("query count = %d, want 1", len(storage.queries))
	}
	if storage.queries[0]["company_id"] != "company-a" || storage.queries[0]["repo_name"] != "org/repo" {
		t.Fatalf("query filter = %#v, want company and repository filters", storage.queries[0])
	}
	if len(storage.inserts) == 0 || storage.inserts[0]["company_id"] != "company-a" {
		t.Fatalf("bus factor update = %#v, want company-a scoped row", storage.inserts)
	}
}

func TestUpdateContributionsRequiresCompanyAndWritesCompanyScope(t *testing.T) {
	storage := &recordingMetricsStorage{}
	service := &MetricsServiceImpl{storage: storage}
	request := domain.IngestRequest{
		Source:    "github",
		EventType: "push",
		CompanyID: "company-a",
		Payload: map[string]interface{}{
			"sender":     map[string]interface{}{"login": "engineer"},
			"repository": map[string]interface{}{"full_name": "org/repo"},
			"commits":    []interface{}{map[string]interface{}{}},
		},
	}

	if err := service.UpdateContributions(context.Background(), request); err != nil {
		t.Fatalf("UpdateContributions() error = %v", err)
	}
	storage.mu.Lock()
	if len(storage.inserts) != 1 || storage.inserts[0]["company_id"] != "company-a" {
		storage.mu.Unlock()
		t.Fatalf("contribution insert = %#v, want company-a scoped row", storage.inserts)
	}
	storage.mu.Unlock()

	request.CompanyID = "default"
	if err := service.UpdateContributions(context.Background(), request); err == nil {
		t.Fatal("UpdateContributions() without a real company succeeded")
	}
}

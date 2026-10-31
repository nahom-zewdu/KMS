package repository

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/supabase-community/supabase-go"
)

func TestAuthenticateUserUsesSupabaseAuthAndRejectsInvalidToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/auth/v1/user" {
			http.NotFound(w, r)
			return
		}
		if r.Header.Get("apikey") != "service-api-key" {
			t.Errorf("apikey = %q", r.Header.Get("apikey"))
		}
		if r.Header.Get("Authorization") == "Bearer valid-token" {
			_, _ = fmt.Fprint(w, `{"id":"user-123"}`)
			return
		}
		http.Error(w, `{"message":"invalid token"}`, http.StatusUnauthorized)
	}))
	defer server.Close()
	repo := newTestSupabaseRepo(t, server.URL, "service-api-key")

	userID, err := repo.AuthenticateUser(context.Background(), "valid-token")
	if err != nil || userID != "user-123" {
		t.Fatalf("AuthenticateUser() = (%q, %v), want user-123 and nil", userID, err)
	}
	if _, err := repo.AuthenticateUser(context.Background(), "invalid-token"); !errors.Is(err, domain.ErrUnauthenticated) {
		t.Fatalf("invalid token error = %v, want ErrUnauthenticated", err)
	}
}

func TestIsCompanyMemberAppliesBothDatabaseFilters(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/rest/v1/company_members" {
			http.NotFound(w, r)
			return
		}
		if got := r.URL.Query().Get("user_id"); got != "eq.user-1" {
			t.Errorf("user_id filter = %q", got)
		}
		if got := r.URL.Query().Get("company_id"); got != "eq.company-a" {
			t.Errorf("company_id filter = %q", got)
		}
		_, _ = fmt.Fprint(w, `[{"user_id":"user-1","company_id":"company-a"}]`)
	}))
	defer server.Close()
	repo := newTestSupabaseRepo(t, server.URL, "service-api-key")

	member, err := repo.IsCompanyMember(context.Background(), "user-1", "company-a")
	if err != nil || !member {
		t.Fatalf("IsCompanyMember() = (%v, %v), want true and nil", member, err)
	}
}

func TestResolveRepositoryForCompanyAppliesCompanyAndRepositoryFilters(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/rest/v1/repositories" {
			http.NotFound(w, r)
			return
		}
		if got := r.URL.Query().Get("company_id"); got != "eq.company-a" {
			t.Errorf("company_id filter = %q", got)
		}
		if got := r.URL.Query().Get("id"); got != "eq.123e4567-e89b-12d3-a456-426614174000" {
			t.Errorf("id filter = %q", got)
		}
		_, _ = fmt.Fprint(w, `[{"id":"123e4567-e89b-12d3-a456-426614174000","company_id":"company-a","full_name":"org/repo"}]`)
	}))
	defer server.Close()
	repo := newTestSupabaseRepo(t, server.URL, "service-api-key")

	fullName, err := repo.ResolveRepositoryForCompany(context.Background(), "company-a", "123e4567-e89b-12d3-a456-426614174000")
	if err != nil || fullName != "org/repo" {
		t.Fatalf("ResolveRepositoryForCompany() = (%q, %v), want org/repo and nil", fullName, err)
	}
}

func TestQueryKnowledgeGraphAppliesCompanyFilter(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/rest/v1/raw_data" {
			http.NotFound(w, r)
			return
		}
		if got := r.URL.Query().Get("company_id"); got != "eq.company-a" {
			t.Errorf("company_id filter = %q", got)
		}
		_, _ = fmt.Fprint(w, `[{"content":"company data"}]`)
	}))
	defer server.Close()
	repo := newTestSupabaseRepo(t, server.URL, "service-api-key")

	answer, err := repo.QueryKnowledgeGraphSupabase(context.Background(), "company", "company-a")
	if err != nil || answer != "company data" {
		t.Fatalf("QueryKnowledgeGraphSupabase() = (%q, %v), want company data and nil", answer, err)
	}
}

func TestQueryKnowledgeGraphRejectsMissingOrDefaultCompany(t *testing.T) {
	repo := newTestSupabaseRepo(t, "http://127.0.0.1:1", "service-api-key")
	for _, companyID := range []string{"", "default", " DEFAULT "} {
		if _, err := repo.QueryKnowledgeGraphSupabase(context.Background(), "query", companyID); err == nil {
			t.Errorf("QueryKnowledgeGraphSupabase(companyID=%q) succeeded, want validation error", companyID)
		}
	}
}

func TestContributionQueryRequiresAndAppliesTenantFilters(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/rest/v1/contributions" {
			http.NotFound(w, r)
			return
		}
		if got := r.URL.Query().Get("company_id"); got != "eq.company-a" {
			t.Errorf("company_id filter = %q", got)
		}
		if got := r.URL.Query().Get("repo_name"); got != "eq.org/repo" {
			t.Errorf("repo_name filter = %q", got)
		}
		_, _ = fmt.Fprint(w, `[{"person_name":"engineer","commit_count":3}]`)
	}))
	defer server.Close()
	repo := newTestSupabaseRepo(t, server.URL, "service-api-key")

	if _, err := repo.Query(context.Background(), "contributions", map[string]interface{}{
		"company_id": "company-a",
		"repo_name":  "org/repo",
	}); err != nil {
		t.Fatalf("scoped contributions query failed: %v", err)
	}
	if _, err := repo.Query(context.Background(), "contributions", map[string]interface{}{
		"repo_name": "org/repo",
	}); err == nil {
		t.Fatal("unscoped contributions query succeeded")
	}
}

func TestContributionInsertUsesTenantConflictTarget(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/rest/v1/contributions" {
			http.NotFound(w, r)
			return
		}
		if got := r.URL.Query().Get("on_conflict"); got != "company_id,person_name,repo_name" {
			t.Errorf("on_conflict = %q", got)
		}
		if !strings.Contains(r.Header.Get("Prefer"), "resolution=merge-duplicates") {
			t.Errorf("Prefer header = %q, want merge-duplicates", r.Header.Get("Prefer"))
		}
		_, _ = fmt.Fprint(w, `[]`)
	}))
	defer server.Close()
	repo := newTestSupabaseRepo(t, server.URL, "service-api-key")

	if err := repo.Insert(context.Background(), "contributions", map[string]interface{}{
		"id":          "row-1",
		"company_id":  "company-a",
		"person_name": "engineer",
		"repo_name":   "org/repo",
	}); err != nil {
		t.Fatalf("scoped contribution insert failed: %v", err)
	}
	if err := repo.Insert(context.Background(), "contributions", map[string]interface{}{
		"id":          "row-2",
		"company_id":  "default",
		"person_name": "engineer",
		"repo_name":   "org/repo",
	}); err == nil {
		t.Fatal("default-company contribution insert succeeded")
	}
}

func newTestSupabaseRepo(t *testing.T, projectURL, key string) *SupabaseRepo {
	t.Helper()
	client, err := supabase.NewClient(projectURL, key, nil)
	if err != nil {
		t.Fatalf("create Supabase test client: %v", err)
	}
	return &SupabaseRepo{
		client:     client,
		projectURL: projectURL,
		apiKey:     key,
		httpClient: &http.Client{Timeout: time.Second},
	}
}

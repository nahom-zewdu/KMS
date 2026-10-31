package repository

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
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

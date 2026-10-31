package handlers

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
)

type securityStorage struct {
	tokens          map[string]string
	memberships     map[string]map[string]bool
	repositories    map[string]string
	companies       map[string]string
	authCalls       int
	membershipCalls int
	repositoryCalls int
	companyCalls    int
	mu              sync.Mutex
}

func (s *securityStorage) Insert(context.Context, string, map[string]interface{}) error {
	return nil
}
func (s *securityStorage) Query(context.Context, string, map[string]interface{}) ([]map[string]interface{}, error) {
	return nil, nil
}
func (s *securityStorage) QueryKnowledgeGraphSupabase(context.Context, string, string) (string, error) {
	return "", nil
}
func (s *securityStorage) ResolveCompanyByIntegration(_ context.Context, provider, externalID string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.companyCalls++
	return s.companies[provider+":"+externalID], nil
}
func (s *securityStorage) ResolveCompanyByInstallation(context.Context, string) (string, error) {
	return "", nil
}
func (s *securityStorage) AuthenticateUser(_ context.Context, token string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.authCalls++
	if userID := s.tokens[token]; userID != "" {
		return userID, nil
	}
	return "", domain.ErrUnauthenticated
}
func (s *securityStorage) IsCompanyMember(_ context.Context, userID, companyID string) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.membershipCalls++
	return s.memberships[userID][companyID], nil
}
func (s *securityStorage) ResolveRepositoryForCompany(_ context.Context, companyID, repository string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.repositoryCalls++
	return s.repositories[companyID+"|"+repository], nil
}

type securityBot struct {
	botID string
	start chan struct{}
	done  chan struct{}
	err   error
}

func (b *securityBot) HandleEvent(context.Context, string, string, string, string, string, string) error {
	if b.start != nil {
		close(b.start)
	}
	if b.done != nil {
		<-b.done
	}
	return b.err
}
func (b *securityBot) GetBotID(context.Context) (string, error) { return b.botID, nil }

type securitySlackIngest struct {
	requests []domain.IngestRequest
}

func (s *securitySlackIngest) IngestSlackEvent(_ context.Context, request domain.IngestRequest) error {
	s.requests = append(s.requests, request)
	return nil
}

type securityRedis struct {
	published []domain.JobPayload
	subscribe bool
}

func (r *securityRedis) Publish(_ context.Context, _ string, payload domain.JobPayload) error {
	r.published = append(r.published, payload)
	return nil
}
func (*securityRedis) CacheGet(context.Context, string) (string, error)              { return "", nil }
func (*securityRedis) CacheSet(context.Context, string, string, time.Duration) error { return nil }
func (r *securityRedis) Subscribe(_ context.Context, _ string) (<-chan string, error) {
	r.subscribe = true
	result := make(chan string, 1)
	result <- `{"answer":"ok"}`
	return result, nil
}

type securityCodebase struct {
	companyID string
	repo      string
}

func (s *securityCodebase) SyncRepository(_ context.Context, companyID, repo string) error {
	s.companyID, s.repo = companyID, repo
	return nil
}

func newTestRouter(storage domain.StoragePort, redis domain.RedisStream, bot domain.SlackBotService, codebase domain.CodebaseService) *gin.Engine {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	auth := requireSupabaseUser(storage)
	router.POST("/query", auth, NewQueryHandler(bot, redis, storage).HandleQuery)
	router.GET("/github/sync-baseline", auth, NewCodebaseHandler(codebase, storage).SyncBaseline)
	return router
}

func TestQueryRequiresVerifiedMembershipAndUsesAuthorizedCompany(t *testing.T) {
	storage := &securityStorage{
		tokens:      map[string]string{"valid-token": "user-1"},
		memberships: map[string]map[string]bool{"user-1": {"company-a": true}},
	}
	redis := &securityRedis{}
	router := newTestRouter(storage, redis, &securityBot{}, &securityCodebase{})

	tests := []struct {
		name        string
		token       string
		companyID   string
		wantStatus  int
		wantPublish bool
	}{
		{name: "missing authentication", companyID: "company-a", wantStatus: http.StatusUnauthorized},
		{name: "invalid authentication", token: "forged-token", companyID: "company-a", wantStatus: http.StatusUnauthorized},
		{name: "non-member company", token: "valid-token", companyID: "company-b", wantStatus: http.StatusForbidden},
		{name: "missing company", token: "valid-token", wantStatus: http.StatusBadRequest},
		{name: "default company", token: "valid-token", companyID: "default", wantStatus: http.StatusBadRequest},
		{name: "authorized company", token: "valid-token", companyID: "company-a", wantStatus: http.StatusOK, wantPublish: true},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			redis.published = nil
			redis.subscribe = false
			body, _ := json.Marshal(map[string]string{"question": "hello", "company_id": test.companyID})
			request := httptest.NewRequest(http.MethodPost, "/query", bytes.NewReader(body))
			if test.token != "" {
				request.Header.Set("Authorization", "Bearer "+test.token)
			}
			request.Header.Set("Content-Type", "application/json")
			response := httptest.NewRecorder()
			router.ServeHTTP(response, request)
			if response.Code != test.wantStatus {
				t.Fatalf("status = %d, want %d; body=%s", response.Code, test.wantStatus, response.Body)
			}
			if got := len(redis.published) > 0; got != test.wantPublish {
				t.Fatalf("published = %v, want %v", got, test.wantPublish)
			}
			if test.wantPublish {
				job := redis.published[0]
				if job.CompanyID != "company-a" || job.Payload["company_id"] != "company-a" {
					t.Fatalf("job tenant context not propagated: %#v", job)
				}
			}
		})
	}

	largeBody := `{"question":"` + strings.Repeat("x", (1<<20)+1) + `","company_id":"company-a"}`
	request := httptest.NewRequest(http.MethodPost, "/query", strings.NewReader(largeBody))
	request.Header.Set("Authorization", "Bearer valid-token")
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("oversized query status = %d, want %d", response.Code, http.StatusRequestEntityTooLarge)
	}
}

func TestBaselineRequiresMembershipAndRepositoryOwnership(t *testing.T) {
	storage := &securityStorage{
		tokens:      map[string]string{"valid-token": "user-1"},
		memberships: map[string]map[string]bool{"user-1": {"company-a": true}},
		repositories: map[string]string{
			"company-a|repo-id-a":  "org-a/repo",
			"company-b|org-b/repo": "org-b/repo",
		},
	}
	codebase := &securityCodebase{}
	router := newTestRouter(storage, &securityRedis{}, &securityBot{}, codebase)

	tests := []struct {
		name       string
		token      string
		companyID  string
		repository string
		wantStatus int
	}{
		{name: "missing authentication", companyID: "company-a", repository: "repo-id-a", wantStatus: http.StatusUnauthorized},
		{name: "invalid authentication", token: "invalid", companyID: "company-a", repository: "repo-id-a", wantStatus: http.StatusUnauthorized},
		{name: "missing company", token: "valid-token", repository: "repo-id-a", wantStatus: http.StatusBadRequest},
		{name: "default company", token: "valid-token", companyID: "default", repository: "repo-id-a", wantStatus: http.StatusBadRequest},
		{name: "missing repository", token: "valid-token", companyID: "company-a", wantStatus: http.StatusBadRequest},
		{name: "non-member", token: "valid-token", companyID: "company-b", repository: "org-b/repo", wantStatus: http.StatusForbidden},
		{name: "cross-company repository", token: "valid-token", companyID: "company-a", repository: "org-b/repo", wantStatus: http.StatusForbidden},
		{name: "authorized repository", token: "valid-token", companyID: "company-a", repository: "repo-id-a", wantStatus: http.StatusAccepted},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			codebase.companyID, codebase.repo = "", ""
			target := fmt.Sprintf("/github/sync-baseline?company_id=%s&repo=%s", test.companyID, test.repository)
			request := httptest.NewRequest(http.MethodGet, target, nil)
			if test.token != "" {
				request.Header.Set("Authorization", "Bearer "+test.token)
			}
			response := httptest.NewRecorder()
			router.ServeHTTP(response, request)
			if response.Code != test.wantStatus {
				t.Fatalf("status = %d, want %d; body=%s", response.Code, test.wantStatus, response.Body)
			}
			if test.wantStatus == http.StatusAccepted && (codebase.companyID != "company-a" || codebase.repo != "org-a/repo") {
				t.Fatalf("sync used unverified repo: company=%q repo=%q", codebase.companyID, codebase.repo)
			}
		})
	}
}

func TestSlackSignatureRejectsInvalidOldAndFutureRequests(t *testing.T) {
	handler := NewSlackHandler(nil, nil, nil, "signing-secret", nil)
	body := []byte(`{"type":"url_verification","challenge":"test"}`)
	now := time.Now()
	for _, tc := range []struct {
		name  string
		when  time.Time
		valid bool
	}{
		{name: "current", when: now, valid: true},
		{name: "old", when: now.Add(-6 * time.Minute)},
		{name: "future", when: now.Add(6 * time.Minute)},
	} {
		t.Run(tc.name, func(t *testing.T) {
			timestamp := fmt.Sprintf("%d", tc.when.Unix())
			signature := slackSignature("signing-secret", timestamp, body)
			if tc.name == "current" {
				signature = "v0=" + strings.Repeat("0", 64)
				if handler.verifySlackSignature(timestamp, signature, body) {
					t.Fatal("invalid signature was accepted")
				}
				signature = slackSignature("signing-secret", timestamp, body)
			}
			if got := handler.verifySlackSignature(timestamp, signature, body); got != tc.valid {
				t.Fatalf("verification = %v, want %v", got, tc.valid)
			}
		})
	}
}

func slackSignature(secret, timestamp string, body []byte) string {
	mac := hmac.New(sha256.New, []byte(secret))
	_, _ = fmt.Fprintf(mac, "v0:%s:%s", timestamp, body)
	return "v0=" + hex.EncodeToString(mac.Sum(nil))
}

func TestWebhookBodyLimitAndSignatureBeforeProcessing(t *testing.T) {
	storage := &securityStorage{
		companies: map[string]string{"slack:T1": "company-a"},
	}
	slackHandler := NewSlackHandler(nil, nil, nil, "secret", storage)
	gin.SetMode(gin.TestMode)

	oversized := httptest.NewRequest(http.MethodPost, "/slack/events", strings.NewReader(strings.Repeat("x", maxWebhookBodyBytes+1)))
	oversizedResponse := httptest.NewRecorder()
	router := gin.New()
	router.POST("/slack/events", slackHandler.HandleSlackWebhook)
	router.ServeHTTP(oversizedResponse, oversized)
	if oversizedResponse.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("oversized request status = %d, want %d", oversizedResponse.Code, http.StatusRequestEntityTooLarge)
	}

	body := []byte(`{"type":"event_callback","event_id":"Ev123","team_id":"T1","event":{"type":"message","user":"U1","text":"hello","ts":"1.000001","channel":"C1"}}`)
	request := httptest.NewRequest(http.MethodPost, "/slack/events", bytes.NewReader(body))
	request.Header.Set("X-Slack-Request-Timestamp", fmt.Sprintf("%d", time.Now().Unix()))
	request.Header.Set("X-Slack-Signature", "v0="+strings.Repeat("0", 64))
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("invalid signature status = %d, want %d", response.Code, http.StatusUnauthorized)
	}
	if storage.companyLookupCount() != 0 {
		t.Fatal("payload was processed before webhook signature verification")
	}

	githubHandler := NewGitHubHandler(nil, "secret", storage)
	githubRouter := gin.New()
	githubRouter.POST("/github", githubHandler.HandleGitHubWebhook)
	githubOversized := httptest.NewRequest(http.MethodPost, "/github", strings.NewReader(strings.Repeat("x", maxWebhookBodyBytes+1)))
	githubOversizedResponse := httptest.NewRecorder()
	githubRouter.ServeHTTP(githubOversizedResponse, githubOversized)
	if githubOversizedResponse.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("oversized GitHub request status = %d, want %d", githubOversizedResponse.Code, http.StatusRequestEntityTooLarge)
	}

	githubBody := []byte(`{}`)
	githubRequest := httptest.NewRequest(http.MethodPost, "/github", bytes.NewReader(githubBody))
	githubRequest.Header.Set("X-Hub-Signature-256", "sha256="+strings.Repeat("0", 64))
	githubRequest.Header.Set("X-GitHub-Delivery", "123e4567-e89b-12d3-a456-426614174000")
	githubRequest.Header.Set("X-GitHub-Event", "push")
	githubResponse := httptest.NewRecorder()
	githubRouter.ServeHTTP(githubResponse, githubRequest)
	if githubResponse.Code != http.StatusUnauthorized {
		t.Fatalf("invalid GitHub signature status = %d, want %d", githubResponse.Code, http.StatusUnauthorized)
	}

	validSignature := hmac.New(sha256.New, []byte("secret"))
	_, _ = validSignature.Write(githubBody)
	githubRequest = httptest.NewRequest(http.MethodPost, "/github", bytes.NewReader(githubBody))
	githubRequest.Header.Set("X-Hub-Signature-256", "sha256="+hex.EncodeToString(validSignature.Sum(nil)))
	githubRequest.Header.Set("X-GitHub-Delivery", "not-a-uuid")
	githubRequest.Header.Set("X-GitHub-Event", "push")
	githubResponse = httptest.NewRecorder()
	githubRouter.ServeHTTP(githubResponse, githubRequest)
	if githubResponse.Code != http.StatusBadRequest {
		t.Fatalf("invalid GitHub delivery ID status = %d, want %d", githubResponse.Code, http.StatusBadRequest)
	}
}

func TestSlackHandlerWaitsForProcessingBeforeReturning(t *testing.T) {
	storage := &securityStorage{companies: map[string]string{"slack:T1": "company-a"}}
	started, release := make(chan struct{}), make(chan struct{})
	bot := &securityBot{start: started, done: release}
	handler := NewSlackHandler(nil, bot, nil, "secret", storage)
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.POST("/slack/events", handler.HandleSlackWebhook)
	body := []byte(`{"type":"event_callback","event_id":"Ev123","team_id":"T1","event":{"type":"app_mention","user":"U1","text":"@bot hello","ts":"1760533260.035849","channel":"C1"}}`)
	request := httptest.NewRequest(http.MethodPost, "/slack/events", bytes.NewReader(body))
	timestamp := fmt.Sprintf("%d", time.Now().Unix())
	request.Header.Set("X-Slack-Request-Timestamp", timestamp)
	request.Header.Set("X-Slack-Signature", slackSignature("secret", timestamp, body))
	response := httptest.NewRecorder()
	done := make(chan struct{})
	go func() {
		router.ServeHTTP(response, request)
		close(done)
	}()
	select {
	case <-started:
	case <-time.After(2 * time.Second):
		t.Fatal("Slack handler did not start event processing")
	}
	select {
	case <-done:
		t.Fatal("handler returned before event processing completed")
	default:
	}
	close(release)
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("handler did not return after event processing completed")
	}
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusOK, response.Body)
	}
}

func TestSlackIngestionUsesProviderEventIDAndRejectsMissingID(t *testing.T) {
	gin.SetMode(gin.TestMode)
	storage := &securityStorage{companies: map[string]string{"slack:T1": "company-a"}}
	ingest := &securitySlackIngest{}
	handler := NewSlackHandler(ingest, &securityBot{}, nil, "secret", storage)
	router := gin.New()
	router.POST("/slack/events", handler.HandleSlackWebhook)

	body := []byte(`{"type":"event_callback","event_id":"Ev-provider-delivery","team_id":"T1","event":{"type":"message","user":"U1","text":"hello","ts":"1760533260.035849","channel":"C1"}}`)
	request := httptest.NewRequest(http.MethodPost, "/slack/events", bytes.NewReader(body))
	timestamp := fmt.Sprintf("%d", time.Now().Unix())
	request.Header.Set("X-Slack-Request-Timestamp", timestamp)
	request.Header.Set("X-Slack-Signature", slackSignature("secret", timestamp, body))
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusOK, response.Body)
	}
	if len(ingest.requests) != 1 || ingest.requests[0].RecordID != "Ev-provider-delivery" {
		t.Fatalf("Slack delivery record IDs = %#v, want provider event ID", ingest.requests)
	}

	body = []byte(`{"type":"event_callback","team_id":"T1","event":{"type":"message","user":"U1","text":"hello","ts":"1760533260.035849","channel":"C1"}}`)
	request = httptest.NewRequest(http.MethodPost, "/slack/events", bytes.NewReader(body))
	timestamp = fmt.Sprintf("%d", time.Now().Unix())
	request.Header.Set("X-Slack-Request-Timestamp", timestamp)
	request.Header.Set("X-Slack-Signature", slackSignature("secret", timestamp, body))
	response = httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("missing event ID status = %d, want %d", response.Code, http.StatusBadRequest)
	}
	if len(ingest.requests) != 1 {
		t.Fatalf("missing event ID was ingested; requests = %d", len(ingest.requests))
	}
}

func (s *securityStorage) companyLookupCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.repositoryCalls + s.membershipCalls + s.authCalls + s.companyCalls
}

var _ domain.StoragePort = (*securityStorage)(nil)
var _ domain.SlackIngestService = (*securitySlackIngest)(nil)

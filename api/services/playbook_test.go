package services

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/slack-go/slack"
)

func TestGeneratePlaybookUsesCompanyBoundInternalToken(t *testing.T) {
	const secret = "internal-service-test-secret-with-at-least-32-bytes"
	t.Setenv("INTERNAL_SERVICE_SECRET", secret)
	t.Setenv("INTERNAL_SERVICE_ISSUER", "kms-internal")
	t.Setenv("INTERNAL_SERVICE_AUDIENCE", "kms-nlp")

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/playbooks/generate" {
			t.Errorf("request path = %q, want /internal/playbooks/generate", r.URL.Path)
		}
		if r.Method != http.MethodPost {
			t.Errorf("request method = %q, want POST", r.Method)
		}

		var payload map[string]string
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Errorf("decode request payload: %v", err)
		}
		if payload["company_id"] != "company-a" {
			t.Errorf("payload company_id = %q, want company-a", payload["company_id"])
		}
		if payload["role"] != "backend-engineer" {
			t.Errorf("payload role = %q, want backend-engineer", payload["role"])
		}

		token := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		parts := strings.Split(token, ".")
		if len(parts) != 3 {
			t.Errorf("service token has %d parts, want 3", len(parts))
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		unsigned := parts[0] + "." + parts[1]
		mac := hmac.New(sha256.New, []byte(secret))
		_, _ = mac.Write([]byte(unsigned))
		signature, err := base64.RawURLEncoding.DecodeString(parts[2])
		if err != nil || !hmac.Equal(signature, mac.Sum(nil)) {
			t.Errorf("service token signature is invalid")
		}

		var header map[string]string
		headerBytes, _ := base64.RawURLEncoding.DecodeString(parts[0])
		if err := json.Unmarshal(headerBytes, &header); err != nil {
			t.Errorf("decode token header: %v", err)
		}
		if header["alg"] != "HS256" {
			t.Errorf("token algorithm = %q, want HS256", header["alg"])
		}
		var claims struct {
			Issuer    string `json:"iss"`
			Audience  string `json:"aud"`
			Subject   string `json:"sub"`
			Role      string `json:"role"`
			CompanyID string `json:"company_id"`
			IssuedAt  int64  `json:"iat"`
			ExpiresAt int64  `json:"exp"`
		}
		claimsBytes, _ := base64.RawURLEncoding.DecodeString(parts[1])
		if err := json.Unmarshal(claimsBytes, &claims); err != nil {
			t.Errorf("decode token claims: %v", err)
		}
		if claims.Issuer != "kms-internal" || claims.Audience != "kms-nlp" ||
			claims.Subject != "kms-go-api" || claims.Role != "service" ||
			claims.CompanyID != "company-a" || claims.ExpiresAt <= claims.IssuedAt {
			t.Errorf("unexpected service token claims: %+v", claims)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = fmt.Fprint(w, `{"success":true,"playbook":{"title":"Secure onboarding","welcome_message":"Welcome"}}`)
	}))
	defer server.Close()

	service := &PlaybookService{pythonURL: server.URL + "/internal/playbooks/generate"}
	message, err := service.GeneratePlaybook(context.Background(), "backend-engineer", "", "company-a")
	if err != nil {
		t.Fatalf("GeneratePlaybook() error = %v", err)
	}
	if !strings.Contains(message, "Secure onboarding") || !strings.Contains(message, "Welcome") {
		t.Fatalf("playbook response not reflected in message: %q", message)
	}
}

func TestGeneratePlaybookRejectsMissingCompanyAndServiceConfiguration(t *testing.T) {
	t.Setenv("INTERNAL_SERVICE_SECRET", "internal-service-test-secret-with-at-least-32-bytes")
	t.Setenv("INTERNAL_SERVICE_ISSUER", "kms-internal")
	t.Setenv("INTERNAL_SERVICE_AUDIENCE", "kms-nlp")

	service := &PlaybookService{pythonURL: "http://127.0.0.1:1"}
	if _, err := service.GeneratePlaybook(context.Background(), "backend-engineer", "", "default"); err == nil {
		t.Fatal("GeneratePlaybook() accepted the default company")
	}
	if _, err := service.GeneratePlaybook(context.Background(), "backend-engineer", "", ""); err == nil {
		t.Fatal("GeneratePlaybook() accepted a missing company")
	}

	t.Setenv("INTERNAL_SERVICE_SECRET", "")
	if _, err := service.GeneratePlaybook(context.Background(), "backend-engineer", "", "company-a"); err == nil {
		t.Fatal("GeneratePlaybook() succeeded without internal service token configuration")
	}
}

func TestGeneratePlaybookRejectsUnsuccessfulOrMissingDataResponses(t *testing.T) {
	t.Setenv("INTERNAL_SERVICE_SECRET", "internal-service-test-secret-with-at-least-32-bytes")
	t.Setenv("INTERNAL_SERVICE_ISSUER", "kms-internal")
	t.Setenv("INTERNAL_SERVICE_AUDIENCE", "kms-nlp")

	for _, responseBody := range []string{
		`{"success":false,"error":"generation failed"}`,
		`{"success":true}`,
	} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			_, _ = fmt.Fprint(w, responseBody)
		}))
		service := &PlaybookService{pythonURL: server.URL}
		_, err := service.GeneratePlaybook(context.Background(), "backend-engineer", "", "company-a")
		server.Close()
		if err == nil {
			t.Fatalf("GeneratePlaybook() accepted response %s", responseBody)
		}
	}
}

func TestCreatePlaybookServiceTokenHasShortExpiry(t *testing.T) {
	t.Setenv("INTERNAL_SERVICE_SECRET", "internal-service-test-secret-with-at-least-32-bytes")
	t.Setenv("INTERNAL_SERVICE_ISSUER", "kms-internal")
	t.Setenv("INTERNAL_SERVICE_AUDIENCE", "kms-nlp")
	now := time.Now().UTC().Truncate(time.Second)
	token, err := createPlaybookServiceToken("company-a", now)
	if err != nil {
		t.Fatalf("createPlaybookServiceToken() error = %v", err)
	}
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		t.Fatalf("token parts = %d, want 3", len(parts))
	}
	claimsBytes, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatalf("decode claims: %v", err)
	}
	var claims map[string]interface{}
	if err := json.Unmarshal(claimsBytes, &claims); err != nil {
		t.Fatalf("unmarshal claims: %v", err)
	}
	if got := claims["exp"].(float64) - claims["iat"].(float64); got != 60 {
		t.Fatalf("token lifetime = %v seconds, want 60", got)
	}
}

type capturingPlaybookService struct {
	companyID string
}

func (s *capturingPlaybookService) GeneratePlaybook(_ context.Context, _, _, companyID string) (string, error) {
	s.companyID = companyID
	return "generated playbook", nil
}

func TestSlackBotPassesResolvedCompanyToPlaybookService(t *testing.T) {
	slackAPI := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/chat.postMessage" {
			t.Errorf("Slack API path = %q, want /chat.postMessage", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = fmt.Fprint(w, `{"ok":true,"channel":"C1","ts":"123.456"}`)
	}))
	defer slackAPI.Close()

	playbooks := &capturingPlaybookService{}
	bot := &SlackBot{
		client:          slack.New("xoxb-test", slack.OptionAPIURL(slackAPI.URL+"/")),
		playbookService: playbooks,
	}
	if err := bot.HandleEvent(context.Background(), "T1", "C1", "", "@kms playbook for backend engineer", "event-1", "company-resolved"); err != nil {
		t.Fatalf("HandleEvent() error = %v", err)
	}
	if playbooks.companyID != "company-resolved" {
		t.Fatalf("playbook company_id = %q, want company-resolved", playbooks.companyID)
	}
}

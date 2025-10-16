// handlers/github.go
// Package handlers provides the GitHub webhook handler for KnowSphere, processing events
// (push, pull_request, issues) with HMAC-SHA256 verification. It extracts summarized content,
// stores raw payloads, and delegates to GitHubIngestService for ingestion. Ensures idempotency
// and handles edge cases (invalid signatures, large payloads, unsupported events).

package handlers

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
)

// GitHubHandler handles GitHub webhook requests.
type GitHubHandler struct {
	githubIngest domain.GitHubIngestService // Service for GitHub event ingestion
	secret       string                     // GitHub webhook secret for HMAC verification
}

// NewGitHubHandler creates a new GitHubHandler with the provided service and secret.
// Args:
//
//	githubIngest: GitHubIngestService for event ingestion.
//	secret: Webhook secret for HMAC-SHA256 verification.
//
// Returns:
//
//	Pointer to GitHubHandler.
func NewGitHubHandler(githubIngest domain.GitHubIngestService, secret string) *GitHubHandler {
	return &GitHubHandler{
		githubIngest: githubIngest,
		secret:       secret,
	}
}

// HandleGitHubWebhook processes GitHub webhook events, verifying signatures and extracting data.
// It supports push, pull_request, and issues events, storing raw payloads and summarized content.
// Args:
//
//	c: Gin context with HTTP request data.
//
// Returns:
//
//	HTTP response (200 for success, 400/401 for errors).
func (h *GitHubHandler) HandleGitHubWebhook(c *gin.Context) {
	start := time.Now()
	// Validate HTTP method
	if c.Request.Method != http.MethodPost {
		log.Printf("Invalid method: %s in %.3fs", c.Request.Method, time.Since(start).Seconds())
		c.JSON(http.StatusMethodNotAllowed, gin.H{"error": "Method not allowed"})
		return
	}

	// Read and preserve request body
	body, err := io.ReadAll(c.Request.Body)
	if err != nil {
		log.Printf("Failed to read request body in %.3fs: %v", time.Since(start).Seconds(), err)
		c.JSON(http.StatusBadRequest, gin.H{"error": "Failed to read request body"})
		return
	}
	c.Request.Body = io.NopCloser(strings.NewReader(string(body)))

	// Verify GitHub signature
	signature := c.GetHeader("X-Hub-Signature-256")
	if !h.verifyGitHubSignature(signature, body) {
		log.Printf("Invalid GitHub signature in %.3fs", time.Since(start).Seconds())
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid request signature"})
		return
	}

	// Get delivery ID for idempotency
	deliveryID := c.GetHeader("X-GitHub-Delivery")
	if deliveryID == "" {
		log.Printf("Missing GitHub delivery ID in %.3fs", time.Since(start).Seconds())
		c.JSON(http.StatusBadRequest, gin.H{"error": "Missing delivery ID"})
		return
	}

	// Parse event type
	eventType := c.GetHeader("X-GitHub-Event")
	if eventType != "push" && eventType != "pull_request" && eventType != "issues" {
		log.Printf("RecordID: %s - Unsupported event type %s in %.3fs", deliveryID, eventType, time.Since(start).Seconds())
		c.JSON(http.StatusOK, gin.H{"status": "unsupported event ignored"})
		return
	}

	// Parse payload
	var payload map[string]interface{}
	if err := json.Unmarshal(body, &payload); err != nil {
		log.Printf("RecordID: %s - Failed to parse GitHub payload in %.3fs: %v", deliveryID, time.Since(start).Seconds(), err)
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid event payload"})
		return
	}

	// Generate summarized content
	var content string
	switch eventType {
	case "push":
		repoName, _ := payload["repository"].(map[string]interface{})["full_name"].(string)
		sender, _ := payload["sender"].(map[string]interface{})["login"].(string)
		commits, _ := payload["commits"].([]interface{})
		content = fmt.Sprintf("Push to %s by %s (%d commits)", repoName, sender, len(commits))
	case "pull_request":
		pr, _ := payload["pull_request"].(map[string]interface{})
		repoName, _ := payload["repository"].(map[string]interface{})["full_name"].(string)
		sender, _ := payload["sender"].(map[string]interface{})["login"].(string)
		action, _ := payload["action"].(string)
		content = fmt.Sprintf("%s PR #%v: %s in %s by %s", action, pr["number"], pr["title"], repoName, sender)
	case "issues":
		issue, _ := payload["issue"].(map[string]interface{})
		repoName, _ := payload["repository"].(map[string]interface{})["full_name"].(string)
		sender, _ := payload["sender"].(map[string]interface{})["login"].(string)
		action, _ := payload["action"].(string)
		content = fmt.Sprintf("%s issue #%v: %s in %s by %s", action, issue["number"], issue["title"], repoName, sender)
	}
	if content == "" {
		log.Printf("RecordID: %s - Empty content for %s event in %.3fs", deliveryID, eventType, time.Since(start).Seconds())
		c.JSON(http.StatusOK, gin.H{"status": "empty content ignored"})
		return
	}

	// Ingest event
	ingestReq := domain.IngestRequest{
		Source:    "github",
		EventType: eventType,
		Content:   content,
		Payload:   payload,
		RecordID:  deliveryID,
		CreatedAt: time.Now().UTC(),
	}
	if err := h.githubIngest.IngestGitHubEvent(c.Request.Context(), ingestReq); err != nil {
		log.Printf("RecordID: %s - Failed to ingest %s event in %.3fs: %v", deliveryID, eventType, time.Since(start).Seconds(), err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to process event"})
		return
	}

	log.Printf("RecordID: %s - Successfully handled %s event in %.3fs", deliveryID, eventType, time.Since(start).Seconds())
	c.JSON(http.StatusOK, gin.H{"status": "event received"})
}

// verifyGitHubSignature verifies the HMAC-SHA256 signature of the GitHub webhook payload.
// Args:
//
//	signature: X-Hub-Signature-256 header value.
//	body: Raw request body.
//
// Returns:
//
//	True if signature matches, false otherwise.
func (h *GitHubHandler) verifyGitHubSignature(signature string, body []byte) bool {
	start := time.Now()
	if !strings.HasPrefix(signature, "sha256=") {
		log.Printf("Invalid signature format in %.3fs", time.Since(start).Seconds())
		return false
	}

	// Compute expected signature
	hash := hmac.New(sha256.New, []byte(h.secret))
	hash.Write(body)
	expectedSignature := "sha256=" + hex.EncodeToString(hash.Sum(nil))

	// Compare signatures securely
	if !hmac.Equal([]byte(signature), []byte(expectedSignature)) {
		log.Printf("Signature mismatch in %.3fs: expected <redacted>, got <redacted>", time.Since(start).Seconds())
		return false
	}
	log.Printf("Successfully verified signature in %.3fs", time.Since(start).Seconds())
	return true
}

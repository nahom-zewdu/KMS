// handlers/github.go
package handlers

import (
	"bytes"
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
	githubIngest domain.GitHubIngestService
	secret       string // GitHub Webhook Secret
}

// NewGitHubHandler creates a new GitHubHandler.
func NewGitHubHandler(githubIngest domain.GitHubIngestService, secret string) *GitHubHandler {
	return &GitHubHandler{
		githubIngest: githubIngest,
		secret:       secret,
	}
}

// HandleGitHubWebhook processes GitHub webhook events.
func (h *GitHubHandler) HandleGitHubWebhook(c *gin.Context) {
	start := time.Now()
	if c.Request.Method != http.MethodPost {
		log.Printf("Invalid method: %s in %.3fs", c.Request.Method, time.Since(start).Seconds())
		c.JSON(http.StatusMethodNotAllowed, gin.H{"error": "Method not allowed"})
		return
	}

	// Read body
	body, err := io.ReadAll(c.Request.Body)
	if err != nil {
		log.Printf("Failed to read request body in %.3fs: %v", time.Since(start).Seconds(), err)
		c.JSON(http.StatusBadRequest, gin.H{"error": "Failed to read request body"})
		return
	}
	c.Request.Body = io.NopCloser(bytes.NewBuffer(body))

	// Verify GitHub signature
	signature := c.GetHeader("X-Hub-Signature-256")
	if signature == "" {
		log.Printf("Missing GitHub signature header in %.3fs", time.Since(start).Seconds())
		c.JSON(http.StatusBadRequest, gin.H{"error": "Missing signature header"})
		return
	}
	if !h.verifyGitHubSignature(signature, body) {
		log.Printf("Invalid GitHub signature in %.3fs", time.Since(start).Seconds())
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid request signature"})
		return
	}

	// Parse webhook payload
	var event domain.GitHubEvent
	if err := json.Unmarshal(body, &event); err != nil {
		log.Printf("Failed to parse GitHub event in %.3fs: %v", time.Since(start).Seconds(), err)
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid event payload"})
		return
	}

	// Validate event
	deliveryID := c.GetHeader("X-GitHub-Delivery")
	if deliveryID == "" {
		log.Printf("Missing GitHub delivery ID in %.3fs", time.Since(start).Seconds())
		c.JSON(http.StatusBadRequest, gin.H{"error": "Missing delivery ID"})
		return
	}
	eventType := c.GetHeader("X-GitHub-Event")
	if eventType != "pull_request" && eventType != "issue" && eventType != "push" {
		log.Printf("RecordID: %s - Unsupported GitHub event type: %s in %.3fs", deliveryID, eventType, time.Since(start).Seconds())
		c.JSON(http.StatusOK, gin.H{"status": "unsupported event ignored"})
		return
	}

	// Extract content based on event type
	var content string
	switch eventType {
	case "pull_request":
		if event.PullRequest != nil {
			content = fmt.Sprintf("%s pull request #%v: %s in repo %s by %s",
				event.Action,
				event.PullRequest["number"],
				event.PullRequest["title"],
				event.Repository["full_name"],
				event.Sender["login"])
		}
	case "issue":
		if event.Issue != nil {
			content = fmt.Sprintf("%s issue #%v: %s in repo %s by %s",
				event.Action,
				event.Issue["number"],
				event.Issue["title"],
				event.Repository["full_name"],
				event.Sender["login"])
		}
	case "push":
		if event.Repository != nil {
			content = fmt.Sprintf("push to %s by %s", event.Repository["full_name"], event.Sender["login"])
		}
	}
	if content == "" {
		log.Printf("RecordID: %s - Empty content for %s event in %.3fs", deliveryID, eventType, time.Since(start).Seconds())
		c.JSON(http.StatusOK, gin.H{"status": "empty content ignored"})
		return
	}

	// Ingest event
	ingestReq := domain.IngestRequest{
		Source:    "github",
		Content:   content,
		RecordID:  deliveryID,
		CreatedAt: time.Now().UTC(),
	}
	if err := h.githubIngest.IngestGitHubEvent(c.Request.Context(), ingestReq); err != nil {
		log.Printf("RecordID: %s - Failed to ingest GitHub event in %.3fs: %v", deliveryID, time.Since(start).Seconds(), err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to process event"})
		return
	}

	log.Printf("RecordID: %s - Successfully handled %s event in %.3fs", deliveryID, eventType, time.Since(start).Seconds())
	c.JSON(http.StatusOK, gin.H{"status": "event received"})
}

// verifyGitHubSignature verifies the GitHub webhook signature.
func (h *GitHubHandler) verifyGitHubSignature(signature string, body []byte) bool {
	start := time.Now()
	if !strings.HasPrefix(signature, "sha256=") {
		log.Printf("Invalid GitHub signature format in %.3fs", time.Since(start).Seconds())
		return false
	}

	hash := hmac.New(sha256.New, []byte(h.secret))
	hash.Write(body)
	expectedSignature := "sha256=" + hex.EncodeToString(hash.Sum(nil))
	if signature != expectedSignature {
		log.Printf("Signature mismatch in %.3fs: expected <redacted>, got <redacted>", time.Since(start).Seconds())
		return false
	}
	log.Printf("Successfully verified GitHub signature in %.3fs", time.Since(start).Seconds())
	return true
}

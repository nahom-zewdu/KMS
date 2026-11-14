// handlers/slack.go
// Package handlers provides the Slack webhook handler for KnowSphere, processing message and app_mention
// events with HMAC-SHA256 verification. It ingests user messages, handles bot mentions for queries, and
// ensures idempotency using the provider event_id as record_id. Supports edge cases like bot messages, timeouts, and
// retries for reliability.

package handlers

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/slack-go/slack"
	"github.com/slack-go/slack/slackevents"
)

// SlackHandler handles Slack webhook requests and bot interactions.
type SlackHandler struct {
	slackIngest domain.SlackIngestService // Service for ingesting Slack events
	slackBot    domain.SlackBotService    // Service for handling bot queries
	slackClient *slack.Client             // For posting fallback messages
	signKey     string                    // Slack Signing Secret
	storage     domain.StoragePort        // For resolving company from Slack team_id
}

// NewSlackHandler creates a new SlackHandler with the provided dependencies.
// Args:
//
//	slackIngest: Service for ingesting Slack events.
//	slackBot: Service for handling bot queries (app_mention).
//	slackClient: Slack API client for posting messages.
//	signKey: Slack Signing Secret for HMAC verification.
//
// Returns:
//
//	Pointer to SlackHandler.
func NewSlackHandler(slackIngest domain.SlackIngestService, slackBot domain.SlackBotService, slackClient *slack.Client, signKey string, supabase domain.StoragePort) *SlackHandler {
	return &SlackHandler{
		slackIngest: slackIngest,
		slackBot:    slackBot,
		slackClient: slackClient,
		signKey:     signKey,
		storage:     supabase,
	}
}

// HandleSlackWebhook processes Slack webhook events, verifying signatures and handling message/app_mention events.
// It ingests user messages, processes bot queries, and handles retries for reliability.
// Args:
//
//	c: Gin context with HTTP request data.
//
// Returns:
//
//	HTTP response (200 for success, 400/401/405 for errors).
func (h *SlackHandler) HandleSlackWebhook(c *gin.Context) {
	start := time.Now()
	// Validate HTTP method
	if c.Request.Method != http.MethodPost {
		log.Printf("Invalid method: %s in %.3fs", c.Request.Method, time.Since(start).Seconds())
		c.JSON(http.StatusMethodNotAllowed, gin.H{"error": "Method not allowed"})
		return
	}

	body, ok := readWebhookBody(c)
	if !ok {
		return
	}

	// Verify Slack signature
	timestamp := c.GetHeader("X-Slack-Request-Timestamp")
	signature := c.GetHeader("X-Slack-Signature")
	if timestamp == "" || signature == "" {
		log.Printf("Missing Slack signature headers in %.3fs", time.Since(start).Seconds())
		c.JSON(http.StatusBadRequest, gin.H{"error": "Missing signature headers"})
		return
	}
	if !h.verifySlackSignature(timestamp, signature, body) {
		log.Printf("Invalid Slack signature in %.3fs", time.Since(start).Seconds())
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid request signature"})
		return
	}
	log.Printf("Successfully verified Slack signature in %.3fs", time.Since(start).Seconds())

	// Parse Slack event
	eventsAPIEvent, err := slackevents.ParseEvent(json.RawMessage(body), slackevents.OptionNoVerifyToken())
	if err != nil {
		log.Printf("Failed to parse Slack event in %.3fs: %v", time.Since(start).Seconds(), err)
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid event payload"})
		return
	}

	// Handle URL verification
	if eventsAPIEvent.Type == slackevents.URLVerification {
		var r *slackevents.ChallengeResponse
		if err := json.Unmarshal(body, &r); err != nil {
			log.Printf("Failed to parse challenge in %.3fs: %v", time.Since(start).Seconds(), err)
			c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid challenge"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"challenge": r.Challenge})
		return
	}

	// Handle callback events
	if eventsAPIEvent.Type != slackevents.CallbackEvent {
		log.Printf("Unsupported event type: %s in %.3fs", eventsAPIEvent.Type, time.Since(start).Seconds())
		c.JSON(http.StatusBadRequest, gin.H{"error": "Unsupported event type"})
		return
	}
	var callbackMetadata struct {
		EventID string `json:"event_id"`
	}
	if err := json.Unmarshal(body, &callbackMetadata); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid callback metadata"})
		return
	}
	eventID := strings.TrimSpace(callbackMetadata.EventID)
	if eventID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Slack event_id is required"})
		return
	}

	innerEvent := eventsAPIEvent.InnerEvent
	companyID, tenantErr := resolveSlackTenant(c.Request.Context(), h.storage, eventsAPIEvent.TeamID)
	if tenantErr != nil {
		if errors.Is(tenantErr, errTenantNotFound) {
			log.Printf("No company mapped for Slack event")
			c.JSON(http.StatusUnprocessableEntity, gin.H{"error": "Unable to resolve event tenant"})
			return
		}
		log.Printf("Failed to resolve Slack event tenant: %v", tenantErr)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to resolve event tenant"})
		return
	}

	switch ev := innerEvent.Data.(type) {
	case *slackevents.AppMentionEvent:
		if strings.TrimSpace(ev.Text) == "" {
			log.Printf("RecordID: %s - Empty app_mention event in %.3fs", ev.TimeStamp, time.Since(start).Seconds())
			c.JSON(http.StatusOK, gin.H{"status": "empty query ignored"})
			return
		}
		log.Printf("RecordID: %s - Handling app_mention event: %s", ev.TimeStamp, ev.Text)
		ctx, cancel := context.WithTimeout(c.Request.Context(), 60*time.Second)
		defer cancel()
		var processingErr error
		for attempt := 1; attempt <= 3; attempt++ {
			processingErr = h.slackBot.HandleEvent(ctx, eventsAPIEvent.TeamID, ev.Channel, ev.ThreadTimeStamp, ev.Text, ev.TimeStamp, companyID)
			if processingErr == nil {
				break
			}
			log.Printf("RecordID: %s - Failed to handle app_mention (attempt %d): %v", ev.TimeStamp, attempt, processingErr)
			if attempt < 3 {
				select {
				case <-ctx.Done():
					processingErr = ctx.Err()
					attempt = 3
				case <-time.After(time.Duration(attempt*attempt) * 100 * time.Millisecond):
				}
			}
		}
		if processingErr != nil {
			if h.slackClient != nil {
				if _, _, err := h.slackClient.PostMessageContext(ctx, ev.Channel,
					slack.MsgOptionText("Sorry, I couldn't process that query. Try again?", false),
					slack.MsgOptionTS(ev.ThreadTimeStamp)); err != nil {
					log.Printf("RecordID: %s - Failed to post fallback message: %v", ev.TimeStamp, err)
				}
			}
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to process message"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"status": "event received"})
		return

	case *slackevents.MessageEvent:
		eventTime, validTimestamp := parseSlackTimestamp(ev.TimeStamp)
		if !validTimestamp {
			log.Printf("RecordID: <none> - Invalid or empty Slack event_ts in %.3fs", time.Since(start).Seconds())
			c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid or empty event timestamp"})
			return
		}

		ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
		defer cancel()
		botID, err := h.slackBot.GetBotID(ctx)
		if err != nil {
			log.Printf("RecordID: %s - Failed to verify Slack bot identity: %v", ev.TimeStamp, err)
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Unable to process message"})
			return
		}
		if ev.BotID != "" || ev.User == botID || strings.Contains(ev.Text, "<@") || ev.User == "" {
			log.Printf("RecordID: %s - Skipping message event (bot or mention)", ev.TimeStamp)
			c.JSON(http.StatusOK, gin.H{"status": "skipped bot/mention"})
			return
		}

		ingestReq := domain.IngestRequest{
			Source:    "slack",
			EventType: "message",
			Content:   strings.TrimSpace(ev.Text),
			Payload: map[string]interface{}{
				"user":      ev.User,
				"channel":   ev.Channel,
				"thread_ts": ev.ThreadTimeStamp,
				"text":      ev.Text,
			},
			RecordID:  eventID,
			CompanyID: companyID,
			CreatedAt: eventTime,
		}
		var processingErr error
		for attempt := 1; attempt <= 3; attempt++ {
			processingErr = h.slackIngest.IngestSlackEvent(ctx, ingestReq)
			if processingErr == nil {
				break
			}
			log.Printf("RecordID: %s - Failed to ingest Slack message (attempt %d): %v", ev.TimeStamp, attempt, processingErr)
			if attempt < 3 {
				select {
				case <-ctx.Done():
					processingErr = ctx.Err()
					attempt = 3
				case <-time.After(time.Duration(attempt*attempt) * 100 * time.Millisecond):
				}
			}
		}
		if processingErr != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to process message"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"status": "event received"})
		return
	}

	log.Printf("Successfully handled Slack webhook of type %s in %.3fs", eventsAPIEvent.Type, time.Since(start).Seconds())
	c.JSON(http.StatusOK, gin.H{"status": "event received"})
}

// verifySlackSignature verifies the Slack webhook signature using HMAC-SHA256.
// Args:
//
//	timestamp: X-Slack-Request-Timestamp header.
//	signature: X-Slack-Signature header.
//	body: Raw request body.
//
// Returns:
//
//	True if signature is valid, false otherwise.
func (h *SlackHandler) verifySlackSignature(timestamp, signature string, body []byte) bool {
	ts, err := strconv.ParseInt(timestamp, 10, 64)
	if err != nil {
		return false
	}
	delta := time.Since(time.Unix(ts, 0))
	if delta < -5*time.Minute || delta > 5*time.Minute {
		return false
	}

	sigBase := fmt.Sprintf("v0:%s:%s", timestamp, string(body))
	hash := hmac.New(sha256.New, []byte(h.signKey))
	hash.Write([]byte(sigBase))
	expectedSignature := "v0=" + hex.EncodeToString(hash.Sum(nil))
	return hmac.Equal([]byte(signature), []byte(expectedSignature))
}

// slackTimestampToTime converts a Slack timestamp string to time.Time in UTC.
// Args:
//
//	ts: Slack timestamp (e.g., "1760533260.035849").
//
// Returns:
//
//	Converted time.Time or current time on error.
func parseSlackTimestamp(ts string) (time.Time, bool) {
	parts := strings.Split(ts, ".")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return time.Time{}, false
	}
	sec, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil {
		return time.Time{}, false
	}
	if _, err := strconv.ParseInt(parts[1], 10, 64); err != nil {
		return time.Time{}, false
	}
	if sec < 0 {
		return time.Time{}, false
	}
	return time.Unix(sec, 0).UTC(), true
}

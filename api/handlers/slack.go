// handlers/slack.go
package handlers

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/slack-go/slack"
	"github.com/slack-go/slack/slackevents"
)

// SlackHandler handles Slack webhook requests and bot interactions.
type SlackHandler struct {
	slackIngest domain.SlackIngestService
	slackBot    domain.SlackBotService
	slackClient *slack.Client // For posting fallback messages
	signKey     string        // Slack Signing Secret
}

// NewSlackHandler creates a new SlackHandler.
func NewSlackHandler(slackIngest domain.SlackIngestService, slackBot domain.SlackBotService, slackClient *slack.Client, signKey string) *SlackHandler {
	return &SlackHandler{
		slackIngest: slackIngest,
		slackBot:    slackBot,
		slackClient: slackClient,
		signKey:     signKey,
	}
}

// HandleSlackWebhook processes Slack webhook events.
func (h *SlackHandler) HandleSlackWebhook(c *gin.Context) {
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

	// Verify Slack signature
	timestamp := c.GetHeader("X-Slack-Request-Timestamp")
	signature := c.GetHeader("X-Slack-Signature")
	if timestamp == "" || signature == "" {
		log.Printf("Missing Slack signature headers in %.3fs", time.Since(start).Seconds())
		c.JSON(http.StatusBadRequest, gin.H{"error": "Missing signature headers"})
		return
	}
	if !h.verifySlackSignature(timestamp, signature, body) {
		log.Printf("Invalid Slack signature in %.3fs, expected: <redacted>, got: <redacted>", time.Since(start).Seconds())
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid request signature"})
		return
	}

	// Parse event
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
	if eventsAPIEvent.Type == slackevents.CallbackEvent {
		innerEvent := eventsAPIEvent.InnerEvent
		switch ev := innerEvent.Data.(type) {
		case *slackevents.AppMentionEvent:
			if strings.TrimSpace(ev.Text) == "" {
				log.Printf("RecordID: %s - Empty app_mention event in %.3fs", ev.TimeStamp, time.Since(start).Seconds())
				c.JSON(http.StatusOK, gin.H{"status": "empty query ignored"})
				return
			}
			log.Printf("RecordID: %s - Handling app_mention event: %s", ev.TimeStamp, ev.Text)
			go func() {
				// Use new context to avoid HTTP request cancellation
				ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
				defer cancel()

				// Retry logic for HandleEvent
				for attempt := 1; attempt <= 3; attempt++ {
					err := h.slackBot.HandleEvent(ctx, eventsAPIEvent.TeamID, ev.Channel, ev.ThreadTimeStamp, ev.Text)
					if err == nil {
						log.Printf("RecordID: %s - Successfully handled app_mention in %.3fs (attempt %d)", ev.TimeStamp, time.Since(start).Seconds(), attempt)
						return
					}
					log.Printf("RecordID: %s - Failed to handle app_mention in %.3fs (attempt %d): %v", ev.TimeStamp, time.Since(start).Seconds(), attempt, err)
					time.Sleep(time.Duration(attempt*attempt) * 100 * time.Millisecond) // Exponential backoff
				}

				// Post fallback message on failure
				_, _, err = h.slackClient.PostMessageContext(ctx, ev.Channel,
					slack.MsgOptionText("Sorry, I couldn't process that query. Try again?", false),
					slack.MsgOptionTS(ev.ThreadTimeStamp))
				if err != nil {
					log.Printf("RecordID: %s - Failed to post fallback message in %.3fs: %v", ev.TimeStamp, time.Since(start).Seconds(), err)
				}
			}()
		case *slackevents.MessageEvent:
			// Ingest only non-mention, non-bot messages
			botID := h.slackBot.GetBotID()
			if !strings.Contains(ev.Text, "<@") && ev.User != "" && ev.BotID == "" && ev.User != botID {
				log.Printf("RecordID: %s - Handling message event: %s", ev.TimeStamp, ev.Text)
				err := h.slackIngest.IngestSlackEvent(c.Request.Context(), domain.IngestRequest{
					Source:    "slack",
					Content:   ev.Text,
					RecordID:  uuid.New().String(),
					CreatedAt: slackTimestampToTime(ev.TimeStamp),
				})
				if err != nil {
					log.Printf("RecordID: %s - Failed to ingest message in %.3fs: %v", ev.TimeStamp, time.Since(start).Seconds(), err)
				}
			} else {
				log.Printf("RecordID: %s - Skipping message event (bot or mention) in %.3fs", ev.TimeStamp, time.Since(start).Seconds())
			}
		}
	}

	log.Printf("Successfully handled Slack webhook of type %s in %.3fs", eventsAPIEvent.Type, time.Since(start).Seconds())
	c.JSON(http.StatusOK, gin.H{"status": "event received"})
}

// verifySlackSignature verifies the Slack webhook signature.
func (h *SlackHandler) verifySlackSignature(timestamp, signature string, body []byte) bool {
	start := time.Now()
	ts, err := strconv.ParseInt(timestamp, 10, 64)
	if err != nil || time.Now().Unix()-ts > 5*60 {
		log.Printf("Invalid Slack timestamp: %s in %.3fs", timestamp, time.Since(start).Seconds())
		return false
	}

	sigBase := fmt.Sprintf("v0:%s:%s", timestamp, string(body))
	hash := hmac.New(sha256.New, []byte(h.signKey))
	hash.Write([]byte(sigBase))
	expectedSignature := "v0=" + hex.EncodeToString(hash.Sum(nil))
	if signature != expectedSignature {
		log.Printf("Signature mismatch in %.3fs: expected <redacted>, got <redacted>", time.Since(start).Seconds())
		return false
	}
	log.Printf("Successfully verified Slack signature in %.3fs", time.Since(start).Seconds())
	return true
}

// slackTimestampToTime converts a Slack timestamp string to time.Time in UTC.
func slackTimestampToTime(ts string) time.Time {
	parts := strings.Split(ts, ".")
	sec, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil {
		log.Printf("Failed to parse Slack timestamp %s: %v, using current time", ts, err)
		return time.Now().UTC()
	}
	return time.Unix(sec, 0).UTC()
}

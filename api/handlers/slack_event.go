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
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/slack-go/slack/slackevents"
)

type SlackEventHandler struct {
	botService    domain.SlackBotService
	ingestService domain.IngestService
	signKey       string
}

func NewSlackEventHandler(botService domain.SlackBotService, ingestService domain.IngestService, signKey string) *SlackEventHandler {
	return &SlackEventHandler{
		botService:    botService,
		ingestService: ingestService,
		signKey:       signKey,
	}
}

func (seh *SlackEventHandler) EventHandler(c *gin.Context) {
	body, err := io.ReadAll(c.Request.Body)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to read request body"})
		return
	}
	c.Request.Body = io.NopCloser(bytes.NewBuffer(body))

	slackSignature := c.GetHeader("X-Slack-Signature")
	slackRequestTimestamp := c.GetHeader("X-Slack-Request-Timestamp")
	if !verifySlackSignature(seh.signKey, slackRequestTimestamp, body, slackSignature) {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid request signature"})
		return
	}

	eventsAPIEvent, err := slackevents.ParseEvent(json.RawMessage(body), slackevents.OptionNoVerifyToken())
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid event payload"})
		return
	}

	if eventsAPIEvent.Type == slackevents.URLVerification {
		var r *slackevents.ChallengeResponse
		err := json.Unmarshal(body, &r)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to parse challenge"})
			return
		}
		c.String(http.StatusOK, r.Challenge)
		return
	}

	if eventsAPIEvent.Type == slackevents.CallbackEvent {
		innerEvent := eventsAPIEvent.InnerEvent
		switch ev := innerEvent.Data.(type) {
		case *slackevents.AppMentionEvent:
			log.Printf("Handling app_mention event: %s", ev.Text)
			go func() {
				err := seh.botService.HandleEvent(c.Request.Context(), eventsAPIEvent.TeamID, ev.Channel, ev.ThreadTimeStamp, ev.Text)
				if err != nil {
					log.Printf("Error handling app_mention event: %v", err)
				}
			}()
		case *slackevents.MessageEvent:
			// Ingest only non-mention, non-bot messages
			if !strings.Contains(ev.Text, "<@") && ev.User != "" && ev.BotID == "" {
				log.Printf("Handling message event: %s", ev.Text)
				err := seh.ingestService.IngestService(c.Request.Context(), domain.IngestRequest{
					Source:  "slack",
					Content: ev.Text,
				})
				if err != nil {
					log.Printf("Failed to ingest normal message: %v", err)
				}
			}
		}
	}

	c.JSON(http.StatusOK, gin.H{"status": "event received"})
}

func verifySlackSignature(signingKey, timestamp string, body []byte, signature string) bool {
	ts, err := strconv.ParseInt(timestamp, 10, 64)
	if err != nil || time.Now().Unix()-ts > 5*60 {
		return false
	}
	sigBase := fmt.Sprintf("v0:%s:%s", timestamp, string(body))
	h := hmac.New(sha256.New, []byte(signingKey))
	h.Write([]byte(sigBase))
	computedSig := "v0=" + hex.EncodeToString(h.Sum(nil))
	return computedSig == signature
}

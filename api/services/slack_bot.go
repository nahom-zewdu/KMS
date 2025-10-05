package services

import (
	"context"
	"fmt"
	"log"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/redis/go-redis/v9"
	"github.com/slack-go/slack"
)

type SlackBot struct {
	client        *slack.Client
	ingestService domain.IngestService
	redis         *redis.Client
	signingKey    string
}

func NewSlackBot(botToken, signingKey string, ingestService domain.IngestService, redis *redis.Client) domain.SlackBotService {
	return &SlackBot{
		client:        slack.New(botToken),
		ingestService: ingestService,
		redis:         redis,
		signingKey:    signingKey,
	}
}

func (sb *SlackBot) HandleEvent(ctx context.Context, teamID, channel, threadTs, query string) error {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	cleanQuery := removeBotMention(query)
	if cleanQuery == "" {
		log.Printf("Empty query after cleaning for channel %s, thread %s", channel, threadTs)
		_, _, err := sb.client.PostMessage(channel,
			slack.MsgOptionText("Please provide a valid query (e.g., 'Who owns github?').", false),
			slack.MsgOptionTS(threadTs))
		return err
	}

	// All @KMS mentions are queries
	if strings.Contains(query, "<@") { // Check raw query for mention
		queryID := uuid.New().String()
		job := domain.JobPayload{
			RecordID:  queryID,
			Source:    "slack",
			Content:   cleanQuery,
			CreatedAt: time.Now().UTC().Format(time.RFC3339),
		}

		// Publish to query_jobs
		err := sb.redis.XAdd(ctx, &redis.XAddArgs{
			Stream: "query_jobs",
			ID:     "*",
			Values: map[string]interface{}{
				"record_id":  job.RecordID,
				"source":     job.Source,
				"content":    job.Content,
				"created_at": job.CreatedAt,
			},
		}).Err()
		if err != nil {
			log.Printf("Failed to publish to query_jobs: %v", err)
			_, _, err = sb.client.PostMessage(channel,
				slack.MsgOptionText("Sorry, I couldn't process that query. Try again?", false),
				slack.MsgOptionTS(threadTs))
			return err
		}

		// Subscribe to Pub/Sub for answer
		pubsub := sb.redis.Subscribe(ctx, "query_results:"+queryID)
		defer pubsub.Close()
		msg, err := pubsub.ReceiveMessage(ctx)
		if err != nil {
			log.Printf("Pub/Sub receive error for query '%s': %v", cleanQuery, err)
			_, _, err = sb.client.PostMessage(channel,
				slack.MsgOptionText("Sorry, I couldn't process that query. Try again?", false),
				slack.MsgOptionTS(threadTs))
			return err
		}
		answer := msg.Payload

		_, _, err = sb.client.PostMessage(channel,
			slack.MsgOptionText(answer, false),
			slack.MsgOptionTS(threadTs))
		if err != nil {
			log.Printf("Failed to post Slack message: %v", err)
			return fmt.Errorf("failed to post Slack message: %v", err)
		}
	} else {
		// Ingest normal messages
		err := sb.ingestService.IngestService(ctx, domain.IngestRequest{
			Source:  "slack",
			Content: cleanQuery,
		})
		msg := "Message recorded."
		if err != nil {
			log.Printf("Ingest error for '%s': %v", cleanQuery, err)
			if strings.Contains(err.Error(), "failed to publish to Redis stream") {
				msg = "Message recorded in database, but failed to queue for processing."
			} else {
				msg = "Failed to record message. Try again?"
			}
		}
		_, _, err = sb.client.PostMessage(channel,
			slack.MsgOptionText(msg, false),
			slack.MsgOptionTS(threadTs))
		if err != nil {
			log.Printf("Failed to post Slack message: %v", err)
			return fmt.Errorf("failed to post Slack message: %v", err)
		}
	}

	log.Printf("Successfully processed '%s' in channel %s, thread %s", cleanQuery, channel, threadTs)
	return nil
}

func (sb *SlackBot) GetBotID() string {
	return sb.signingKey
}

func removeBotMention(query string) string {
	re := regexp.MustCompile(`(?i)<@U[0-9A-Z]+>|@kms`)
	cleaned := re.ReplaceAllString(query, "")
	reInvalid := regexp.MustCompile(`[^a-zA-Z0-9\s\?\.,#]`)
	cleaned = reInvalid.ReplaceAllString(cleaned, "")
	return strings.TrimSpace(cleaned)
}

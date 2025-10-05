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
	botToken      string
	ingestService domain.IngestService
	redis         *redis.Client
}

func NewSlackBot(botToken, signingKey string, ingestService domain.IngestService, redis *redis.Client) domain.SlackBotService {
	return &SlackBot{
		client:        slack.New(botToken),
		botToken:      botToken,
		ingestService: ingestService,
		redis:         redis,
	}
}

func (sb *SlackBot) HandleEvent(ctx context.Context, teamID, channel, threadTs, query string) error {
	ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
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
	queryID := uuid.New().String()
	job := domain.JobPayload{
		ID:        "*",
		RecordID:  queryID,
		Source:    "slack",
		Content:   cleanQuery,
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	}

	// Publish to query_jobs
	maxRetries := 3
	backoff := 500 * time.Millisecond
	for attempt := 1; attempt <= maxRetries; attempt++ {
		if ctx.Err() != nil {
			log.Printf("Attempt %d: Context canceled before publishing to query_jobs: %v", attempt, ctx.Err())
			return ctx.Err()
		}
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
		if err == nil {
			break
		}
		log.Printf("Attempt %d: Failed to publish to query_jobs: %v", attempt, err)
		if attempt == maxRetries {
			_, _, err = sb.client.PostMessage(channel,
				slack.MsgOptionText("Sorry, I couldn't process that query. Try again?", false),
				slack.MsgOptionTS(threadTs))
			return fmt.Errorf("failed to publish to query_jobs after %d attempts: %v", maxRetries, err)
		}
		time.Sleep(backoff)
		backoff *= 2
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

	log.Printf("Successfully processed query '%s' in channel %s, thread %s", cleanQuery, channel, threadTs)
	return nil
}

func (sb *SlackBot) GetBotID() string {
	auth, err := sb.client.AuthTest()
	if err != nil {
		log.Printf("Failed to get bot ID: %v", err)
		return ""
	}
	return auth.BotID

}

func (sb *SlackBot) GetBotToken() string {
	return sb.botToken
}

func removeBotMention(query string) string {
	re := regexp.MustCompile(`(?i)<@U[0-9A-Z]+>|@kms`)
	cleaned := re.ReplaceAllString(query, "")
	reInvalid := regexp.MustCompile(`[^a-zA-Z0-9\s\?\.,#]`)
	cleaned = reInvalid.ReplaceAllString(cleaned, "")
	return strings.TrimSpace(cleaned)
}

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
	client       *slack.Client
	slackService domain.SlackService
	redis        *redis.Client
	signingKey   string
}

func NewSlackBot(botToken, signingKey string, slackService domain.SlackService, redis *redis.Client) domain.SlackBotService {
	return &SlackBot{
		client:       slack.New(botToken),
		slackService: slackService,
		redis:        redis,
		signingKey:   signingKey,
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

	isQuery := strings.Contains(strings.ToLower(cleanQuery), "who") ||
		strings.Contains(strings.ToLower(cleanQuery), "what") ||
		strings.Contains(cleanQuery, "?")

	if isQuery {
		queryID := uuid.New().String()
		// Publish query to Redis Streams
		job := domain.JobPayload{
			ID:        "*",
			RecordID:  queryID,
			Source:    "slack",
			Content:   cleanQuery,
			CreatedAt: time.Now().UTC().Format(time.RFC3339),
		}
		err := sb.slackService.IngestService(ctx, domain.IngestRequest{
			Source:  "slack",
			Content: cleanQuery,
		})
		if err != nil {
			log.Printf("Ingest error for query '%s': %v", cleanQuery, err)
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
		err := sb.slackService.IngestService(ctx, domain.IngestRequest{
			Source:  "slack",
			Content: cleanQuery,
		})
		msg := "Message recorded."
		if err != nil {
			log.Printf("Ingest error for '%s': %v", cleanQuery, err)
			msg = "Failed to record message. Try again?"
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

func removeBotMention(query string) string {
	re := regexp.MustCompile(`(?i)<@U[0-9A-Z]+>|@KnowSphere`)
	cleaned := re.ReplaceAllString(query, "")
	reInvalid := regexp.MustCompile(`[^a-zA-Z0-9\s\?\.,#]`)
	cleaned = reInvalid.ReplaceAllString(cleaned, "")
	return strings.TrimSpace(cleaned)
}

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
	start := time.Now()
	ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()

	cleanQuery := removeBotMention(query)
	if cleanQuery == "" {
		log.Printf("QueryID: <none>, Channel: %s, Thread: %s - Empty query after cleaning, original: %s", channel, threadTs, query)
		startPost := time.Now()
		_, _, err := sb.client.PostMessage(channel,
			slack.MsgOptionText("Please provide a valid query (e.g., 'Who owns github?').", false),
			slack.MsgOptionTS(threadTs))
		if err != nil {
			log.Printf("QueryID: <none>, Channel: %s, Thread: %s - Failed to post empty query response in %v: %v", channel, threadTs, time.Since(startPost), err)
			return fmt.Errorf("failed to post empty query response: %v", err)
		}
		log.Printf("QueryID: <none>, Channel: %s, Thread: %s - Posted empty query response in %v", channel, threadTs, time.Since(startPost))
		return nil
	}

	// All @KMS mentions are queries
	queryID := uuid.New().String()
	job := domain.JobPayload{
		RecordID:  queryID,
		Source:    "slack",
		Content:   cleanQuery,
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	}
	log.Printf("QueryID: %s, Channel: %s, Thread: %s - Processing query: %s", queryID, channel, threadTs, cleanQuery)

	// Publish to query_jobs
	maxRetries := 3
	backoff := 500 * time.Millisecond
	for attempt := 1; attempt <= maxRetries; attempt++ {
		if ctx.Err() != nil {
			log.Printf("QueryID: %s, Channel: %s, Thread: %s - Attempt %d: Context canceled before publishing to query_jobs: %v", queryID, channel, threadTs, attempt, ctx.Err())
			return ctx.Err()
		}
		startXAdd := time.Now()
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
		durationXAdd := time.Since(startXAdd)
		if err == nil {
			log.Printf("QueryID: %s, Channel: %s, Thread: %s - Successfully published to query_jobs in %v", queryID, channel, threadTs, durationXAdd)
			break
		}
		log.Printf("QueryID: %s, Channel: %s, Thread: %s - Attempt %d: Failed to publish to query_jobs in %v: %v", queryID, channel, threadTs, attempt, durationXAdd, err)
		if attempt == maxRetries {
			startPost := time.Now()
			_, _, err = sb.client.PostMessage(channel,
				slack.MsgOptionText("Sorry, I couldn't process that query. Try again?", false),
				slack.MsgOptionTS(threadTs))
			durationPost := time.Since(startPost)
			if err != nil {
				log.Printf("QueryID: %s, Channel: %s, Thread: %s - Failed to post retry message in %v: %v", queryID, channel, threadTs, durationPost, err)
			} else {
				log.Printf("QueryID: %s, Channel: %s, Thread: %s - Posted retry message in %v", queryID, channel, threadTs, durationPost)
			}
			return fmt.Errorf("failed to publish to query_jobs after %d attempts: %v", maxRetries, err)
		}
		time.Sleep(backoff)
		backoff *= 2
	}

	// Subscribe to Pub/Sub for answer
	startSubscribe := time.Now()
	pubsub := sb.redis.Subscribe(ctx, "query_results:"+queryID)
	defer pubsub.Close()
	log.Printf("QueryID: %s, Channel: %s, Thread: %s - Subscribed to query_results:%s in %v", queryID, channel, threadTs, queryID, time.Since(startSubscribe))

	startReceive := time.Now()
	msg, err := pubsub.ReceiveMessage(ctx)
	durationReceive := time.Since(startReceive)
	if err != nil {
		log.Printf("QueryID: %s, Channel: %s, Thread: %s - Pub/Sub receive error in %v: %v", queryID, channel, threadTs, durationReceive, err)
		startPost := time.Now()
		_, _, err = sb.client.PostMessage(channel,
			slack.MsgOptionText("Sorry, I couldn't process that query. Try again?", false),
			slack.MsgOptionTS(threadTs))
		durationPost := time.Since(startPost)
		if err != nil {
			log.Printf("QueryID: %s, Channel: %s, Thread: %s - Failed to post retry message in %v: %v", queryID, channel, threadTs, durationPost, err)
		} else {
			log.Printf("QueryID: %s, Channel: %s, Thread: %s - Posted retry message in %v", queryID, channel, threadTs, durationPost)
		}
		return fmt.Errorf("failed to receive Pub/Sub message: %v", err)
	}
	answer := msg.Payload
	log.Printf("QueryID: %s, Channel: %s, Thread: %s - Received Pub/Sub answer in %v: %s", queryID, channel, threadTs, durationReceive, answer)

	startPost := time.Now()
	_, _, err = sb.client.PostMessage(channel,
		slack.MsgOptionText(answer, false),
		slack.MsgOptionTS(threadTs))
	durationPost := time.Since(startPost)
	if err != nil {
		log.Printf("QueryID: %s, Channel: %s, Thread: %s - Failed to post Slack message in %v: %v", queryID, channel, threadTs, durationPost, err)
		return fmt.Errorf("failed to post Slack message: %v", err)
	}
	log.Printf("QueryID: %s, Channel: %s, Thread: %s - Successfully posted answer to Slack in %v", queryID, channel, threadTs, durationPost)

	log.Printf("QueryID: %s, Channel: %s, Thread: %s - Successfully processed query in %v", queryID, channel, threadTs, time.Since(start))
	return nil
}

func (sb *SlackBot) GetBotID() string {
	start := time.Now()
	auth, err := sb.client.AuthTest()
	duration := time.Since(start)
	if err != nil {
		log.Printf("Failed to get bot ID in %v: %v", duration, err)
		return ""
	}
	log.Printf("Successfully got bot ID %s in %v", auth.BotID, duration)
	return auth.BotID
}

func (sb *SlackBot) GetBotToken() string {
	return sb.botToken
}

func removeBotMention(query string) string {
	start := time.Now()
	re := regexp.MustCompile(`(?i)<@U[0-9A-Z]+>|@kms`)
	cleaned := re.ReplaceAllString(query, "")
	reInvalid := regexp.MustCompile(`[^a-zA-Z0-9\s\?\.,#]`)
	cleaned = reInvalid.ReplaceAllString(cleaned, "")
	cleaned = strings.TrimSpace(cleaned)
	log.Printf("Cleaned query '%s' to '%s' in %v", query, cleaned, time.Since(start))
	return cleaned
}

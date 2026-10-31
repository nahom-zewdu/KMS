// services/slack_bot.go
package services

import (
	"context"
	"errors"
	"fmt"
	"log"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/slack-go/slack"
)

const slackQueryTimeout = 45 * time.Second

// SlackBot handles Slack bot interactions for queries.
type SlackBot struct {
	client          *slack.Client
	botToken        string
	coreIngest      domain.CoreIngestService
	redis           domain.RedisStream
	playbookService domain.PlaybookService
}

// NewSlackBot creates a new SlackBot service.
func NewSlackBot(botToken string, coreIngest domain.CoreIngestService, redis domain.RedisStream, playbookService domain.PlaybookService) domain.SlackBotService {
	return &SlackBot{
		client:          slack.New(botToken),
		botToken:        botToken,
		coreIngest:      coreIngest,
		redis:           redis,
		playbookService: playbookService,
	}
}

// HandleEvent processes Slack app_mention events and publishes queries to Redis.
func (sb *SlackBot) HandleEvent(ctx context.Context, teamID, channel, threadTs, query, eventTs string, companyID string) error {
	start := time.Now()
	ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()

	// Clean query to remove bot mentions
	cleanQuery := removeBotMention(query)
	if cleanQuery == "" {
		log.Printf("QueryID: <none>, Channel: %s, Thread: %s - Empty query after cleaning, original: %s", channel, threadTs, query)
		startPost := time.Now()
		_, _, err := sb.client.PostMessageContext(ctx, channel,
			slack.MsgOptionText("Please provide a valid query (e.g., 'Who owns github?').", false),
			slack.MsgOptionTS(threadTs))
		if err != nil {
			log.Printf("QueryID: <none>, Channel: %s, Thread: %s - Failed to post empty query response in %.3fs: %v", channel, threadTs, time.Since(startPost).Seconds(), err)
			return fmt.Errorf("failed to post empty query response: %v", err)
		}
		log.Printf("QueryID: <none>, Channel: %s, Thread: %s - Posted empty query response in %.3fs", channel, threadTs, time.Since(startPost).Seconds())
		return nil
	}

	// Generate query ID
	queryID := eventTs + "-" + uuid.New().String()

	if strings.Contains(strings.ToLower(cleanQuery), "onboard") ||
		strings.Contains(strings.ToLower(cleanQuery), "playbook") {

		role := extractRole(cleanQuery)
		if role == "" {
			role = "software-engineer" // default
		}

		log.Printf("QueryID: %s - Playbook request detected for role: %s", queryID, role)

		playbookMsg, err := sb.playbookService.GeneratePlaybook(ctx, role, "")
		if err != nil {
			playbookMsg = "Sorry, I couldn't generate the playbook right now."
		}

		_, _, err = sb.client.PostMessageContext(ctx, channel,
			slack.MsgOptionText(playbookMsg, false),
			slack.MsgOptionTS(threadTs))
		return err
	}

	log.Printf("QueryID: %s, Channel: %s, Thread: %s - Processing query: %s", queryID, channel, threadTs, cleanQuery)

	answer, err := sb.requestAnswer(ctx, queryID, cleanQuery, companyID, slackQueryTimeout)
	if err != nil {
		log.Printf("QueryID: %s, Channel: %s, Thread: %s - Query processing failed in %.3fs: %v", queryID, channel, threadTs, time.Since(start).Seconds(), err)
		startPost := time.Now()
		_, _, err = sb.client.PostMessageContext(ctx, channel,
			slack.MsgOptionText("Sorry, I couldn't process that query. Try again?", false),
			slack.MsgOptionTS(threadTs))
		if err != nil {
			log.Printf("QueryID: %s, Channel: %s, Thread: %s - Failed to post failure message in %.3fs: %v", queryID, channel, threadTs, time.Since(startPost).Seconds(), err)
		}
		return err
	}
	startPost := time.Now()
	_, _, err = sb.client.PostMessageContext(ctx, channel,
		slack.MsgOptionText(answer, false),
		slack.MsgOptionTS(threadTs))
	if err != nil {
		log.Printf("QueryID: %s, Channel: %s, Thread: %s - Failed to post Slack answer in %.3fs: %v", queryID, channel, threadTs, time.Since(startPost).Seconds(), err)
		return fmt.Errorf("failed to post Slack answer: %v", err)
	}
	log.Printf("QueryID: %s, Channel: %s, Thread: %s - Posted answer '%s' in %.3fs", queryID, channel, threadTs, answer, time.Since(startPost).Seconds())

	log.Printf("QueryID: %s, Channel: %s, Thread: %s - Successfully processed query in %.3fs", queryID, channel, threadTs, time.Since(start).Seconds())
	return nil
}

func (sb *SlackBot) requestAnswer(
	ctx context.Context,
	queryID string,
	query string,
	companyID string,
	timeout time.Duration,
) (string, error) {
	queryCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	channel := "query_results:" + queryID
	answerChan, err := sb.redis.Subscribe(queryCtx, channel)
	if err != nil {
		return "", fmt.Errorf("failed to subscribe to %s: %w", channel, err)
	}

	err = sb.redis.Publish(queryCtx, "query_jobs", domain.JobPayload{
		ID:        "*",
		RecordID:  queryID,
		Source:    "slack",
		Content:   query,
		CompanyID: companyID,
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	})
	if err != nil {
		return "", fmt.Errorf("failed to publish query job: %w", err)
	}

	select {
	case answer, ok := <-answerChan:
		if !ok {
			return "", errors.New("query result subscription closed before a response")
		}
		return answer, nil
	case <-queryCtx.Done():
		return "", fmt.Errorf("query wait ended: %w", queryCtx.Err())
	}
}

// GetBotID retrieves the Slack bot's ID.
func (sb *SlackBot) GetBotID(ctx context.Context) (string, error) {
	start := time.Now()
	auth, err := sb.client.AuthTestContext(ctx)
	if err != nil {
		log.Printf("Failed to get bot ID in %.3fs: %v", time.Since(start).Seconds(), err)
		return "", err
	}
	log.Printf("Successfully got bot ID %s in %.3fs", auth.BotID, time.Since(start).Seconds())
	return auth.BotID, nil
}

// removeBotMention cleans a query by removing bot mentions and invalid characters.
func removeBotMention(query string) string {
	start := time.Now()
	re := regexp.MustCompile(`(?i)<@U[0-9A-Z]+>|@kms`)
	cleaned := re.ReplaceAllString(query, "")
	reInvalid := regexp.MustCompile(`[^a-zA-Z0-9\s\?\.,#]`)
	cleaned = reInvalid.ReplaceAllString(cleaned, "")
	cleaned = strings.TrimSpace(cleaned)
	log.Printf("Cleaned query '%s' to '%s' in %.3fs", query, cleaned, time.Since(start).Seconds())
	return cleaned
}

func extractRole(query string) string {
	re := regexp.MustCompile(`(?i)\b(?:for|as|onboard)\s+([a-z0-9]+(?:[-\s][a-z0-9]+)*)`)
	match := re.FindStringSubmatch(query)
	if len(match) < 2 {
		return ""
	}
	role := strings.TrimSpace(strings.ToLower(match[1]))
	role = strings.ReplaceAll(role, " ", "-")
	return role
}

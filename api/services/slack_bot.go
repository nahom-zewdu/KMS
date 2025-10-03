package services

import (
	"context"
	"fmt"
	"log"
	"regexp"
	"strings"

	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/slack-go/slack"
)

type SlackBot struct {
	client       *slack.Client
	slackService domain.SlackService // For ingestion
	signingKey   string
}

func NewSlackBot(botToken, signingKey string, slackService domain.SlackService) domain.SlackBotService {
	return &SlackBot{
		client:       slack.New(botToken),
		slackService: slackService,
		signingKey:   signingKey,
	}
}

func (sb *SlackBot) HandleEvent(ctx context.Context, teamID, channel, threadTs, query string) error {
	cleanQuery := removeBotMention(query)
	if cleanQuery == "" {
		log.Printf("Empty query after cleaning for channel %s, thread %s", channel, threadTs)
		_, _, err := sb.client.PostMessage(channel,
			slack.MsgOptionText("Please provide a valid query (e.g., 'Who owns github?').", false),
			slack.MsgOptionTS(threadTs))
		return err
	}

	// Determine if it's a query (e.g., contains "who", "what", or "?")
	isQuery := strings.Contains(strings.ToLower(cleanQuery), "who") ||
		strings.Contains(strings.ToLower(cleanQuery), "what") ||
		strings.Contains(cleanQuery, "?")

	if isQuery {
		// Placeholder: Send query to NLP worker (to be implemented)
		answer, err := sb.queryNLP(ctx, cleanQuery)
		if err != nil {
			log.Printf("NLP query error for '%s': %v", cleanQuery, err)
			_, _, err = sb.client.PostMessage(channel,
				slack.MsgOptionText("Sorry, I couldn't process that query. Try again?", false),
				slack.MsgOptionTS(threadTs))
			return err
		}
		_, _, err = sb.client.PostMessage(channel,
			slack.MsgOptionText(answer, false),
			slack.MsgOptionTS(threadTs))
		if err != nil {
			log.Printf("Failed to post Slack message: %v", err)
			return fmt.Errorf("failed to post Slack message: %v", err)
		}
	} else {
		// Ingest non-query message
		err := sb.slackService.IngestService(ctx, domain.IngestRequest{
			Source:  "slack",
			Content: cleanQuery,
		})
		if err != nil {
			log.Printf("Ingest error for '%s': %v", cleanQuery, err)
			return err
		}
		_, _, err = sb.client.PostMessage(channel,
			slack.MsgOptionText("Message recorded.", false),
			slack.MsgOptionTS(threadTs))
		if err != nil {
			log.Printf("Failed to post Slack message: %v", err)
			return fmt.Errorf("failed to post Slack message: %v", err)
		}
	}

	log.Printf("Successfully processed '%s' in channel %s, thread %s", cleanQuery, channel, threadTs)
	return nil
}

// Placeholder for NLP worker communication (to be replaced in Step 4)
func (sb *SlackBot) queryNLP(ctx context.Context, query string) (string, error) {
	// Simulate NLP response until worker is implemented
	log.Printf("Simulating NLP query for: %s", query)
	if strings.Contains(strings.ToLower(query), "who owns github") {
		return "Nahom owns github, Jira #435", nil
	}
	return "No answer found.", nil
}

func removeBotMention(query string) string {
	// Remove @KnowSphere and Slack user IDs (case-insensitive)
	re := regexp.MustCompile(`(?i)<@U[0-9A-Z]+>|@KnowSphere`)
	cleaned := re.ReplaceAllString(query, "")
	// Remove invalid characters
	reInvalid := regexp.MustCompile(`[^a-zA-Z0-9\s\?\.,#]`)
	cleaned = reInvalid.ReplaceAllString(cleaned, "")
	return strings.TrimSpace(cleaned)
}

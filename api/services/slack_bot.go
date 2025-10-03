package services

import (
	"context"
	"fmt"
	"log"
	"regexp"
	"strings"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/slack-go/slack"
)

type SlackBot struct {
	client       *slack.Client
	slackService domain.SlackService
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
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second) // Extended timeout
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
		err := sb.slackService.IngestService(ctx, domain.IngestRequest{
			Source:  "slack",
			Content: cleanQuery,
		})
		msg := "Message recorded."
		if err != nil {
			log.Printf("Ingest error for '%s': %v", cleanQuery, err)
			if strings.Contains(err.Error(), "failed to publish to Redis stream") {
				msg = "Message recorded in database, but failed to queue for processing. Try again later."
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

func (sb *SlackBot) queryNLP(ctx context.Context, query string) (string, error) {
	log.Printf("Simulating NLP query for: %s", query)
	if strings.Contains(strings.ToLower(query), "who owns github") {
		return "Nahom owns github, Jira #435", nil
	}
	return "No answer found.", nil
}

func removeBotMention(query string) string {
	re := regexp.MustCompile(`(?i)<@U[0-9A-Z]+>|@kms`)
	cleaned := re.ReplaceAllString(query, "")
	reInvalid := regexp.MustCompile(`[^a-zA-Z0-9\s\?\.,#]`)
	cleaned = reInvalid.ReplaceAllString(cleaned, "")
	return strings.TrimSpace(cleaned)
}

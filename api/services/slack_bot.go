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
	client     *slack.Client
	query      domain.QueryService
	signingKey string
}

func NewSlackBot(botToken, signingKey string, query domain.QueryService) domain.SlackBotService {
	return &SlackBot{
		client:     slack.New(botToken),
		query:      query,
		signingKey: signingKey,
	}
}

func (sb *SlackBot) HandleEvent(ctx context.Context, teamID, channel, threadTs, query string) error {
	// Clean query (remove @KnowSphere and Slack user IDs)
	cleanQuery := removeBotMention(query)
	if cleanQuery == "" {
		log.Printf("Empty query after cleaning for channel %s, thread %s", channel, threadTs)
		_, _, err := sb.client.PostMessage(channel,
			slack.MsgOptionText("Please provide a valid query (e.g., 'Who owns github?').", false),
			slack.MsgOptionTS(threadTs))
		return err
	}

	// Call QueryService
	resp, err := sb.query.HandleQuery(ctx, domain.QueryRequest{Query: cleanQuery})
	if err != nil {
		log.Printf("Query error for '%s': %v", cleanQuery, err)
		_, _, err = sb.client.PostMessage(channel,
			slack.MsgOptionText("Sorry, I couldn't process that query. Try again?", false),
			slack.MsgOptionTS(threadTs))
		return err
	}

	// Post response in thread
	_, _, err = sb.client.PostMessage(channel,
		slack.MsgOptionText(resp.Answer, false),
		slack.MsgOptionTS(threadTs))
	if err != nil {
		log.Printf("Failed to post Slack message: %v", err)
		return fmt.Errorf("failed to post Slack message: %v", err)
	}

	return nil
}

func removeBotMention(query string) string {
	// Remove bot mention and Slack user IDs (e.g., <@U09HQ4SH58E>)
	re := regexp.MustCompile(`<@U[0-9A-Z]+>|@kms`)
	cleaned := re.ReplaceAllString(query, "")
	return strings.TrimSpace(cleaned)
}

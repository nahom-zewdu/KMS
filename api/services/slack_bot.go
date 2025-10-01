package services

import (
	"context"
	"fmt"
	"log"
	"strings"

	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/slack-go/slack"
)

type SlackBot struct {
	client       *slack.Client
	queryService domain.QueryService
	signkey      string
}

func NewSlackBot(token, signkey string, queryService domain.QueryService) domain.SlackBotService {
	client := slack.New(token)
	return &SlackBot{
		client:       client,
		signkey:      signkey,
		queryService: queryService,
	}
}

func (sb *SlackBot) HandleEvent(ctx context.Context, teamID, channelID, threadTs, query string) error {
	cleanQuery := removeBotMention(query)
	if cleanQuery == "" {
		return nil // Ignore empty queries
	}

	// Process the query
	resp, err := sb.queryService.HandleQuery(ctx, domain.QueryRequest{Query: cleanQuery})
	if err != nil {
		log.Printf("Query error for %s: %v", cleanQuery, err)
		// Post Fallback message to Slack
		_, _, err := sb.client.PostMessage(channelID,
			slack.MsgOptionText("Sorry, I couldn't process your request at the moment.", false),
			slack.MsgOptionTS(threadTs))

		return err
	}

	// Post response to Slack
	_, _, err = sb.client.PostMessage(channelID,
		slack.MsgOptionText(resp.Answer, false),
		slack.MsgOptionTS(threadTs))
	if err != nil {
		log.Printf("Failed to post message to Slack: %v", err)
		return fmt.Errorf("failed to post message to Slack: %w", err)
	}
	return nil
}

func removeBotMention(query string) string {
	// Simple cleanup: remove @KnowSphere or similar
	return strings.TrimSpace(strings.Replace(query, "@kms", "", 1))
}

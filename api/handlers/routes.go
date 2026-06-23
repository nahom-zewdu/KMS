// handlers/routes.go
package handlers

import (
	"log"

	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/slack-go/slack"
)

// SetupRoutes configures the HTTP routes for the KnowSphere backend.
func SetupRoutes(
	slackIngest domain.SlackIngestService,
	slackBot domain.SlackBotService,
	githubIngest domain.GitHubIngestService,
	slackBotToken, slackSignKey, githubSecret string,
	codebaseService domain.CodebaseService,
	redis domain.RedisStream,
) *gin.Engine {
	// Initialize Gin router
	router := gin.Default()

	// Initialize Slack client for fallback messages
	slackClient := slack.New(slackBotToken)

	// Initialize handlers
	slackHandler := NewSlackHandler(slackIngest, slackBot, slackClient, slackSignKey)
	githubHandler := NewGitHubHandler(githubIngest, githubSecret)
	queryHandler := NewQueryHandler(slackBot, redis)
	codebaseHandler := NewCodebaseHandler(codebaseService)

	// Define routes
	router.POST("/slack/events", slackHandler.HandleSlackWebhook)
	router.POST("/slack/events/", slackHandler.HandleSlackWebhook)
	router.POST("/github", githubHandler.HandleGitHubWebhook)
	router.POST("/github/", githubHandler.HandleGitHubWebhook)
	router.POST("/github/sync-baseline", codebaseHandler.SyncBaseline)
	router.POST("/query", queryHandler.HandleQuery)

	// Health check endpoint
	router.GET("/health", func(c *gin.Context) {
		log.Printf("Health check requested")
		c.JSON(200, gin.H{"status": "healthy"})
	})

	return router
}

package handlers

import (
	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
)

func SetupRoutes(router *gin.Engine, slackService domain.SlackService, queryService domain.QueryService, slackBot domain.SlackBotService, signingKey string) {
	slackHandler := NewSlackHandler(slackService)
	queryHandler := NewQueryHandler(queryService)
	eventHandler := NewSlackEventHandler(slackBot, signingKey)

	router.GET("/", func(c *gin.Context) {
		c.JSON(200, gin.H{"message": "Welcome to the Slack API!"})
	})

	router.POST("/slack/ingest/", slackHandler.IngestHandler)
	router.POST("/slack/query/", queryHandler.QueryHandler)
	router.POST("/slack/events/", eventHandler.EventHandler)
}

package handlers

import (
	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
)

func SetupRoutes(router *gin.Engine, ingestService domain.IngestService, queryService domain.QueryService, slackBot domain.SlackBotService, signingKey string) {
	slackHandler := NewSlackHandler(ingestService)
	queryHandler := NewQueryHandler(queryService)
	eventHandler := NewSlackEventHandler(slackBot, ingestService, signingKey)

	router.GET("/", func(c *gin.Context) {
		c.JSON(200, gin.H{"message": "Welcome to the Slack API!"})
	})

	router.POST("/slack/ingest/", slackHandler.IngestHandler)
	router.POST("/slack/query/", queryHandler.QueryHandler)
	router.POST("/slack/events/", eventHandler.EventHandler)
}

package handlers

import (
	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
)

func SetupRoutes(router *gin.Engine, service domain.SlackService) {
	slackHandler := NewSlackHandler(service)

	// Define the route for getting a Slack message by ID
	router.GET("/", func(c *gin.Context) {
		c.JSON(200, gin.H{"message": "Welcome to the Slack API!"})
	})

	router.POST("/slack/ingest/", slackHandler.IngestHandler)
}

package handlers

import (
	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/services"
)

func SetupRoutes(router *gin.Engine, service services.SlackService) {
	slackHandler := NewSlackHandler(service)

	// Define the route for getting a Slack message by ID
	router.GET("/slack/messages/:id", slackHandler.GetMessage)
}

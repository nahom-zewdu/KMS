package handlers

import (
	"log"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
)

type SlackHandler struct {
	service domain.SlackService
}

func NewSlackHandler(service domain.SlackService) *SlackHandler {
	return &SlackHandler{
		service: service,
	}
}

func (sh *SlackHandler) IngestHandler(c *gin.Context) {
	var req domain.IngestRequest

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body"})
		return
	}

	ctx := c.Request.Context()
	err := sh.service.IngestService(ctx, req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	log.Printf("Received Slack data: %+v", req)
	c.JSON(http.StatusOK, gin.H{"message": "Message received successfully", "data": req})
}

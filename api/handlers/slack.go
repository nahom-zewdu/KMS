package handlers

import (
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

func (sh *SlackHandler) GetMessage(c *gin.Context) {
	id := c.Param("id")

	message, err := sh.service.GetMessage(c.Request.Context(), id)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to retrieve message"})
		return
	}

	if message == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Message not found"})
		return
	}

	c.JSON(http.StatusOK, message)
}

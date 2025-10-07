package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
)

type IngestHandler struct {
	service domain.IngestService
}

func NewSlackHandler(service domain.IngestService) *IngestHandler {
	return &IngestHandler{
		service: service,
	}
}

func (sh *IngestHandler) IngestHandler(c *gin.Context) {
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

	c.JSON(http.StatusOK, gin.H{"message": "Message received successfully", "data": req})
}

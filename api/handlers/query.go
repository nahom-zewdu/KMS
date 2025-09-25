package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
)

type QueryHandler struct {
	service domain.QueryService
}

func NewQueryHandler(service domain.QueryService) *QueryHandler {
	return &QueryHandler{service: service}
}

func (qh *QueryHandler) QueryHandler(c *gin.Context) {
	var req domain.QueryRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request body"})
		return
	}

	ctx := c.Request.Context()
	resp, err := qh.service.HandleQuery(ctx, req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "Query processed successfully", "data": resp})
}

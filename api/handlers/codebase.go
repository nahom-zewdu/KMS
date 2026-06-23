// api/handlers/codebase.go
// Package handlers implements the CodebaseHandler for handling codebase-related HTTP requests.
package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
)

type CodebaseHandler struct {
	codebaseService domain.CodebaseService
}

func NewCodebaseHandler(s domain.CodebaseService) *CodebaseHandler {
	return &CodebaseHandler{codebaseService: s}
}

func (h *CodebaseHandler) SyncBaseline(c *gin.Context) {
	repo := c.Query("repo")
	if repo == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "repo query param required"})
		return
	}

	err := h.codebaseService.SyncRepository(c.Request.Context(), repo)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusAccepted, gin.H{
		"status":  "queued",
		"repo":    repo,
		"message": "Baseline sync has been queued",
	})
}

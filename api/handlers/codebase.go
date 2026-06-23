// api/handlers/codebase.go
// Package handlers implements the CodebaseHandler for handling codebase-related HTTP requests.
package handlers

import (
	"net/http"
	"time"

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
	start := time.Now()
	repoFullName := c.Query("repo")
	if repoFullName == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "repo parameter is required"})
		return
	}

	err := h.codebaseService.SyncRepository(c.Request.Context(), repoFullName)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"status": "baseline_sync_queued",
		"repo":   repoFullName,
		"time":   time.Since(start).String(),
	})
}

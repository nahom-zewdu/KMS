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
	storage         domain.StoragePort
}

func NewCodebaseHandler(s domain.CodebaseService, storage domain.StoragePort) *CodebaseHandler {
	return &CodebaseHandler{codebaseService: s, storage: storage}
}

func (h *CodebaseHandler) SyncBaseline(c *gin.Context) {
	repo := c.Query("repo")
	if repo == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "repo query param required"})
		return
	}
	companyID := c.Query("company_id")
	if !authorizeCompany(c, h.storage, companyID) {
		return
	}

	repoFullName, err := h.storage.ResolveRepositoryForCompany(c.Request.Context(), normalizeCompanyID(companyID), repo)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Unable to verify repository access"})
		return
	}
	if repoFullName == "" {
		c.JSON(http.StatusForbidden, gin.H{"error": "Repository is not accessible to this company"})
		return
	}

	err = h.codebaseService.SyncRepository(c.Request.Context(), normalizeCompanyID(companyID), repoFullName)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to queue baseline sync"})
		return
	}

	c.JSON(http.StatusAccepted, gin.H{
		"status":  "queued",
		"repo":    repoFullName,
		"message": "Baseline sync has been queued",
	})
}

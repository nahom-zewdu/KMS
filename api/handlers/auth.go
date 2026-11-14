package handlers

import (
	"context"
	"errors"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/nahom-zewdu/kMS/api/domain"
)

const authenticatedUserKey = "authenticated_user_id"
const maxSupabaseAccessTokenBytes = 16 << 10

func requireSupabaseUser(storage domain.StoragePort) gin.HandlerFunc {
	return func(c *gin.Context) {
		scheme, token, ok := strings.Cut(strings.TrimSpace(c.GetHeader("Authorization")), " ")
		if !ok || !strings.EqualFold(scheme, "Bearer") || strings.TrimSpace(token) == "" || strings.ContainsAny(strings.TrimSpace(token), " \t\r\n") {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required"})
			return
		}
		if len(token) > maxSupabaseAccessTokenBytes {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Invalid authentication"})
			return
		}

		ctx, cancel := context.WithTimeout(c.Request.Context(), 8*time.Second)
		defer cancel()
		userID, err := storage.AuthenticateUser(ctx, strings.TrimSpace(token))
		if errors.Is(err, domain.ErrUnauthenticated) || (err == nil && strings.TrimSpace(userID) == "") {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Invalid authentication"})
			return
		}
		if err != nil {
			log.Printf("Supabase user validation failed: %v", err)
			c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{"error": "Authentication service unavailable"})
			return
		}

		c.Set(authenticatedUserKey, userID)
		c.Next()
	}
}

func authorizeCompany(c *gin.Context, storage domain.StoragePort, companyID string) bool {
	companyID = normalizeCompanyID(companyID)
	if !isResolvedCompany(companyID) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "A valid company_id is required"})
		return false
	}
	userValue, ok := c.Get(authenticatedUserKey)
	userID, isString := userValue.(string)
	if !ok || !isString || strings.TrimSpace(userID) == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Authentication required"})
		return false
	}
	member, err := storage.IsCompanyMember(c.Request.Context(), userID, companyID)
	if err != nil {
		log.Printf("Company membership lookup failed: %v", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Unable to verify company access"})
		return false
	}
	if !member {
		c.JSON(http.StatusForbidden, gin.H{"error": "Forbidden"})
		return false
	}
	return true
}

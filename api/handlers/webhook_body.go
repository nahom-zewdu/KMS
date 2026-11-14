package handlers

import (
	"errors"
	"io"
	"net/http"

	"github.com/gin-gonic/gin"
)

const maxWebhookBodyBytes = 1 << 20

func readWebhookBody(c *gin.Context) ([]byte, bool) {
	body, err := io.ReadAll(http.MaxBytesReader(c.Writer, c.Request.Body, maxWebhookBodyBytes))
	if err == nil {
		return body, true
	}
	var maxBytesError *http.MaxBytesError
	if errors.As(err, &maxBytesError) {
		c.JSON(http.StatusRequestEntityTooLarge, gin.H{"error": "Webhook payload too large"})
		return nil, false
	}
	c.JSON(http.StatusBadRequest, gin.H{"error": "Failed to read request body"})
	return nil, false
}

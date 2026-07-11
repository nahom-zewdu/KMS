// handlers/query.go
// This file defines the QueryHandler, which processes direct queries from the frontend embedded chat.
// It receives a question, publishes it to a Redis stream for processing, and waits for an answer with a timeout. The handler also logs the query ID and timing for monitoring purposes.

package handlers

import (
	"log"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
)

// QueryHandler handles direct queries from frontend (embedded chat)
type QueryHandler struct {
	slackBot domain.SlackBotService
	redis    domain.RedisStream
}

func NewQueryHandler(slackBot domain.SlackBotService, redis domain.RedisStream) *QueryHandler {
	return &QueryHandler{slackBot: slackBot, redis: redis}
}

func (h *QueryHandler) HandleQuery(c *gin.Context) {
	start := time.Now()

	var req struct {
		Question string `json:"question"`
		Context  string `json:"context"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		log.Printf("Invalid query request in %.3fs", time.Since(start).Seconds())
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request"})
		return
	}

	queryID := uuid.New().String()
	log.Printf("QueryID: %s - Received from frontend: %s", queryID, req.Question)

	// Publish to query_jobs
	err := h.redis.Publish(c.Request.Context(), "query_jobs", domain.JobPayload{
		ID:        "*",
		RecordID:  queryID,
		Source:    "frontend",
		Content:   req.Question,
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	})
	if err != nil {
		log.Printf("QueryID: %s - Failed to publish in %.3fs", queryID, time.Since(start).Seconds())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to process query"})
		return
	}

	// Subscribe for answer
	answerChan, err := h.redis.Subscribe(c.Request.Context(), "query_results:"+queryID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to subscribe"})
		return
	}

	// Wait for answer with timeout (30s to allow sentence transformer model load on first query)
	select {
	case answer := <-answerChan:
		c.JSON(http.StatusOK, gin.H{
			"answer": answer,
		})
	case <-time.After(30 * time.Second):
		c.JSON(http.StatusGatewayTimeout, gin.H{"error": "Query timeout after 30 seconds"})
	}
}

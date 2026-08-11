// handlers/query.go
// QueryHandler processes direct queries from the frontend embedded chat / ramp ask.
// Publishes to Redis query_jobs with company_id, waits on query_results:{id}.

package handlers

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
)

// QueryHandler handles direct queries from frontend (embedded chat, ramp ask).
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
		Question  string `json:"question"`
		Context   string `json:"context"`
		CompanyID string `json:"company_id"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		log.Printf("Invalid query request in %.3fs: %v", time.Since(start).Seconds(), err)
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request"})
		return
	}

	question := strings.TrimSpace(req.Question)
	if question == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "question is required"})
		return
	}

	companyID := strings.TrimSpace(req.CompanyID)
	if companyID == "" {
		companyID = "default"
	}

	// Optional ramp/playbook grounding prepended for the NLP worker (not user-visible).
	content := question
	if ctx := strings.TrimSpace(req.Context); ctx != "" {
		content = ctx + "\n\nQuestion: " + question
	}

	queryID := uuid.New().String()
	log.Printf("QueryID: %s - frontend query company=%s q=%q", queryID, companyID, question)

	// Subscribe first so we do not miss a fast answer.
	answerChan, err := h.redis.Subscribe(c.Request.Context(), "query_results:"+queryID)
	if err != nil {
		log.Printf("QueryID: %s - subscribe failed: %v", queryID, err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to subscribe"})
		return
	}

	err = h.redis.Publish(c.Request.Context(), "query_jobs", domain.JobPayload{
		ID:        "*",
		RecordID:  queryID,
		Source:    "frontend",
		EventType: "query",
		Content:   content,
		CompanyID: companyID,
		Payload: map[string]interface{}{
			"question":   question,
			"context":    req.Context,
			"company_id": companyID,
		},
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	})
	if err != nil {
		log.Printf("QueryID: %s - publish failed in %.3fs: %v", queryID, time.Since(start).Seconds(), err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to process query"})
		return
	}

	select {
	case raw := <-answerChan:
		resp := gin.H{
			"answer": raw,
		}
		// If NLP published a JSON contract, surface fields for the UI.
		var parsed map[string]interface{}
		if err := json.Unmarshal([]byte(raw), &parsed); err == nil {
			if a, ok := parsed["answer"].(string); ok && a != "" {
				resp["answer"] = a
			}
			if s, ok := parsed["sources"]; ok {
				resp["sources"] = s
			}
			if o, ok := parsed["owners"]; ok {
				resp["owners"] = o
			}
			if conf, ok := parsed["confidence"]; ok {
				resp["confidence"] = conf
			}
			if ar, ok := parsed["abstain_reason"]; ok {
				resp["abstain_reason"] = ar
			}
		}
		log.Printf("QueryID: %s - answered in %.3fs company=%s", queryID, time.Since(start).Seconds(), companyID)
		c.JSON(http.StatusOK, resp)

	case <-time.After(45 * time.Second):
		log.Printf("QueryID: %s - timeout after %.3fs", queryID, time.Since(start).Seconds())
		c.JSON(http.StatusGatewayTimeout, gin.H{"error": "Query timeout after 45 seconds"})
	}
}

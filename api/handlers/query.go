// handlers/query.go
// QueryHandler processes direct queries from the frontend embedded chat / ramp ask.
// Publishes to Redis query_jobs with company_id, waits on query_results:{id}.

package handlers

import (
	"encoding/json"
	"errors"
	"io"
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
	storage  domain.StoragePort
}

func NewQueryHandler(slackBot domain.SlackBotService, redis domain.RedisStream, storage domain.StoragePort) *QueryHandler {
	return &QueryHandler{slackBot: slackBot, redis: redis, storage: storage}
}

func (h *QueryHandler) HandleQuery(c *gin.Context) {
	start := time.Now()

	var req struct {
		Question           string                   `json:"question"`
		Context            string                   `json:"context"`
		CompanyID          string                   `json:"company_id"`
		Repository         string                   `json:"repository,omitempty"`
		ConversationHistory []map[string]interface{} `json:"conversation_history"`
	}

	body, err := io.ReadAll(http.MaxBytesReader(c.Writer, c.Request.Body, 1<<20))
	if err != nil {
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			c.JSON(http.StatusRequestEntityTooLarge, gin.H{"error": "Request payload too large"})
			return
		}
		log.Printf("Invalid query request in %.3fs: %v", time.Since(start).Seconds(), err)
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request"})
		return
	}
	if err := json.Unmarshal(body, &req); err != nil {
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
	if !authorizeCompany(c, h.storage, companyID) {
		return
	}

	queryID := uuid.New().String()
	verifiedRepository := ""
	if repository := strings.TrimSpace(req.Repository); repository != "" {
		repositoryStarted := time.Now()
		resolved, resolveErr := h.storage.ResolveRepositoryForCompany(
			c.Request.Context(), normalizeCompanyID(companyID), repository,
		)
		if resolveErr != nil {
			log.Printf("Query repository verification failed: %v", resolveErr)
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Unable to verify repository access"})
			return
		}
		if strings.TrimSpace(resolved) == "" {
			c.JSON(http.StatusForbidden, gin.H{"error": "Repository is not accessible to this company"})
			return
		}
		verifiedRepository = resolved
		log.Printf("kms_query_stage query_id=%s stage=repository_verification duration_ms=%.3f", queryID, float64(time.Since(repositoryStarted).Microseconds())/1000)
	}

	content := question

	log.Printf("QueryID: %s - frontend query company=%s", queryID, companyID)

	// Subscribe first so we do not miss a fast answer.
	answerChan, err := h.redis.Subscribe(c.Request.Context(), "query_results:"+queryID)
	if err != nil {
		log.Printf("QueryID: %s - subscribe failed: %v", queryID, err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to subscribe"})
		return
	}

	publishStarted := time.Now()
	err = h.redis.Publish(c.Request.Context(), "query_jobs", domain.JobPayload{
		ID:         "*",
		RecordID:   queryID,
		Source:     "frontend",
		EventType:  "query",
		Content:    content,
		CompanyID:  companyID,
		Repository: verifiedRepository,
		Payload: map[string]interface{}{
			"question":             question,
			"context":              req.Context,
			"company_id":           companyID,
			"conversation_history": req.ConversationHistory,
		},
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	})
	log.Printf("kms_query_stage query_id=%s stage=job_publish duration_ms=%.3f", queryID, float64(time.Since(publishStarted).Microseconds())/1000)
	if err != nil {
		log.Printf("QueryID: %s - publish failed in %.3fs: %v", queryID, time.Since(start).Seconds(), err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to process query"})
		return
	}

	waitStarted := time.Now()
	select {
	case raw := <-answerChan:
		log.Printf("kms_query_stage query_id=%s stage=worker_round_trip duration_ms=%.3f", queryID, float64(time.Since(waitStarted).Microseconds())/1000)
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
			if claims, ok := parsed["claims"]; ok {
				resp["claims"] = claims
			}
		}
		log.Printf("QueryID: %s - answered in %.3fs company=%s", queryID, time.Since(start).Seconds(), companyID)
		c.JSON(http.StatusOK, resp)

	case <-time.After(45 * time.Second):
		log.Printf("kms_query_stage query_id=%s stage=worker_timeout duration_ms=%.3f", queryID, float64(time.Since(waitStarted).Microseconds())/1000)
		log.Printf("QueryID: %s - timeout after %.3fs", queryID, time.Since(start).Seconds())
		c.JSON(http.StatusGatewayTimeout, gin.H{"error": "Query timeout after 45 seconds"})
	}
}

// api/services/codebase.go
// Package services implements the CodebaseService for managing codebase-related operations.
// It provides functionality to queue baseline sync jobs for repositories, ensuring that
// the necessary data is processed and indexed for code intelligence features.
package services

import (
	"context"
	"log"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

// CodebaseService implements baseline + incremental codebase management.
type CodebaseService struct {
	redis domain.RedisStream
}

func NewCodebaseService(redis domain.RedisStream) domain.CodebaseService {
	return &CodebaseService{redis: redis}
}

func (s *CodebaseService) SyncRepository(ctx context.Context, repoFullName string) error {
	start := time.Now()
	log.Printf("Queueing baseline sync for repository: %s", repoFullName)

	payload := domain.JobPayload{
		ID:        "*",
		RecordID:  "baseline-" + repoFullName,
		Source:    "codebase",
		EventType: "baseline_sync",
		Content:   "Full repository baseline sync requested",
		Payload: map[string]interface{}{
			"repo": repoFullName,
		},
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	}

	err := s.redis.Publish(ctx, "codebase_baseline_jobs", payload)
	if err != nil {
		log.Printf("Failed to queue baseline sync: %v", err)
		return err
	}

	log.Printf("Baseline sync queued successfully in %.3fs", time.Since(start).Seconds())
	return nil
}

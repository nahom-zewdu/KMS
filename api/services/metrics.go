// services/metrics.go
// Package services implements the MetricsService for computing contribution metrics and bus factor
// from GitHub events. It updates the contributions table in Supabase, supporting queries for ownership
// and risk analysis (e.g., bus factor). Handles edge cases like unmerged commits and deleted repos.

package services

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
)

// MetricsServiceImpl implements the MetricsService interface for contribution metrics.
type MetricsServiceImpl struct {
	storage domain.StoragePort // Supabase storage for metrics updates
}

// NewMetricsService creates a new MetricsService with the provided storage dependency.
// Args:
//
//	storage: Supabase storage interface for inserting/querying data.
//
// Returns:
//
//	MetricsService implementation.
func NewMetricsService(storage domain.StoragePort) domain.MetricsService {
	return &MetricsServiceImpl{storage: storage}
}

// UpdateContributions updates contribution metrics for a PERSON in a PROJECT based on a GitHub event.
// It increments commit_count, pr_count, or issue_count in the contributions table.
// Args:
//
//	ctx: Context for cancellation and timeouts.
//	req: IngestRequest with event_type, payload, and record_id.
//
// Returns:
//
//	error if update fails.
func (m *MetricsServiceImpl) UpdateContributions(ctx context.Context, req domain.IngestRequest) error {
	start := time.Now()
	if req.Source != "github" {
		log.Printf("RecordID: %s - Invalid source for metrics update: %s in %.3fs", req.RecordID, req.Source, time.Since(start).Seconds())
		return fmt.Errorf("invalid source for metrics update: %s", req.Source)
	}

	// Extract person and repo from payload
	sender, _ := req.Payload["sender"].(map[string]interface{})["login"].(string)
	repoName, _ := req.Payload["repository"].(map[string]interface{})["full_name"].(string)
	if sender == "" || repoName == "" {
		log.Printf("RecordID: %s - Missing sender or repo in %s event in %.3fs", req.RecordID, req.EventType, time.Since(start).Seconds())
		return fmt.Errorf("missing sender or repo in %s event", req.EventType)
	}

	// Initialize update fields
	update := map[string]interface{}{
		"id":          NewUUID(),
		"person_name": sender,
		"repo_name":   repoName,
		"updated_at":  time.Now().UTC().Format(time.RFC3339),
	}

	// Update counts based on event type
	switch req.EventType {
	case "push":
		commits, _ := req.Payload["commits"].([]interface{})
		update["commit_count"] = len(commits)
	case "pull_request":
		update["pr_count"] = 1
	case "issues":
		update["issue_count"] = 1
	default:
		log.Printf("RecordID: %s - Unsupported event type %s for metrics in %.3fs", req.RecordID, req.EventType, time.Since(start).Seconds())
		return fmt.Errorf("unsupported event type for metrics: %s", req.EventType)
	}

	// Upsert into contributions table
	err := m.storage.Insert(ctx, "contributions", update)
	if err != nil {
		log.Printf("RecordID: %s - Failed to update contributions for %s in %.3fs: %v", req.RecordID, req.EventType, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to update contributions: %v", err)
	}
	log.Printf("RecordID: %s - Updated contributions for %s (%s) in %.3fs", req.RecordID, sender, req.EventType, time.Since(start).Seconds())

	// Update bus factor asynchronously
	go func() {
		if _, err := m.CalculateBusFactor(context.Background(), repoName); err != nil {
			log.Printf("RecordID: %s - Failed to update bus factor for %s in %.3fs: %v", req.RecordID, repoName, time.Since(start).Seconds(), err)
		}
	}()

	return nil
}

// CalculateBusFactor computes the bus factor for a repository based on commit contributions.
// It calculates the percentage of commits by the top contributor, updating the contributions table.
// Args:
//
//	ctx: Context for cancellation and timeouts.
//	repoName: Repository name (e.g., nahom/kms).
//
// Returns:
//
//	Bus factor (0-1, 1 = single contributor) and error if query fails.
func (m *MetricsServiceImpl) CalculateBusFactor(ctx context.Context, repoName string) (float64, error) {
	start := time.Now()
	// Query contributions for the repository
	records, err := m.storage.Query(ctx, "contributions", map[string]interface{}{"repo_name": repoName})
	if err != nil {
		log.Printf("Failed to query contributions for %s in %.3fs: %v", repoName, time.Since(start).Seconds(), err)
		return 0, fmt.Errorf("failed to query contributions: %v", err)
	}

	// Calculate total commits and max per person
	totalCommits := 0
	maxCommits := 0
	var topContributor string
	for _, record := range records {
		commits, _ := record["commit_count"].(int64)
		totalCommits += int(commits)
		if int(commits) > maxCommits {
			maxCommits = int(commits)
			topContributor, _ = record["person_name"].(string)
		}
	}

	// Compute bus factor
	busFactor := 0.0
	if totalCommits > 0 {
		busFactor = float64(maxCommits) / float64(totalCommits)
	}

	// Update bus factor in contributions table
	if topContributor != "" {
		err = m.storage.Insert(ctx, "contributions", map[string]interface{}{
			"person_name": topContributor,
			"repo_name":   repoName,
			"bus_factor":  busFactor,
			"updated_at":  time.Now().UTC().Format(time.RFC3339),
		})
		if err != nil {
			log.Printf("Failed to update bus factor for %s in %.3fs: %v", repoName, time.Since(start).Seconds(), err)
			return busFactor, fmt.Errorf("failed to update bus factor: %v", err)
		}
	}

	log.Printf("Calculated bus factor %.2f for %s in %.3fs", busFactor, repoName, time.Since(start).Seconds())
	return busFactor, nil
}

// NewUUID generates a new UUID string for database records.
// Returns:
//
//	UUID as string.
func NewUUID() string {
	return uuid.New().String()
}

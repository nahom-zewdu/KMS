// domain/github.go
// Package domain provides GitHub-specific structs and interfaces for the KnowSphere backend,
// supporting intelligent event processing (e.g., push, pull_request, issues) for knowledge graph
// extraction and metrics. It ensures compatibility with the hybrid architecture and existing Slack features.

package domain

import "context"

// GitHubEvent represents a parsed GitHub webhook payload.
// Used to validate and extract data from incoming events before ingestion.
type GitHubEvent struct {
	Action      string                 `json:"action"`       // e.g., opened, closed (for pull_request, issues)
	Repository  map[string]interface{} `json:"repository"`   // Contains full_name, url
	Sender      map[string]interface{} `json:"sender"`       // Contains login
	PullRequest map[string]interface{} `json:"pull_request"` // Contains number, title, body, assignee
	Issue       map[string]interface{} `json:"issue"`        // Contains number, title, body, assignee
	Commits     []interface{}          `json:"commits"`      // Array of commit objects (for push)
}

// GitHubIngestService defines the interface for GitHub-specific event ingestion.
// Ensures validation and preprocessing before delegating to CoreIngestService.
type GitHubIngestService interface {
	IngestGitHubEvent(ctx context.Context, req IngestRequest) error
}

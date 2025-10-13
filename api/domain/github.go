// domain/github.go
package domain

import "context"

// GitHubEvent represents a GitHub webhook event payload.
type GitHubEvent struct {
	Action      string                 `json:"action"`
	PullRequest map[string]interface{} `json:"pull_request"`
	Issue       map[string]interface{} `json:"issue"`
	Repository  map[string]interface{} `json:"repository"`
	Sender      map[string]interface{} `json:"sender"`
	DeliveryID  string                 `json:"delivery_id"`
}

// GitHubIngestService defines the interface for ingesting GitHub events.
type GitHubIngestService interface {
	IngestGitHubEvent(ctx context.Context, req IngestRequest) error
}

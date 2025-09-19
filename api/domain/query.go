package domain

import "context"

// New structs for query endpoint
type QueryRequest struct {
	Query string `json:"query" binding:"required"`
}

type QueryResponse struct {
	Answer string `json:"answer"`
}

// New interface for query repository
type QueryRepository interface {
	QueryKnowledgeGraph(ctx context.Context, query string) (string, error)
}

// New interface for query service
type QueryService interface {
	HandleQuery(ctx context.Context, req QueryRequest) (QueryResponse, error)
}

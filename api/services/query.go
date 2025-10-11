// services/query.go
package services

import (
	"context"
	"errors"
	"log"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

// QueryService handles knowledge graph queries.
type QueryService struct {
	repo domain.QueryRepository
}

// NewQueryService creates a new QueryService.
func NewQueryService(repo domain.QueryRepository) domain.QueryService {
	return &QueryService{repo: repo}
}

// HandleQuery processes a query and returns the result from the knowledge graph.
func (qs *QueryService) HandleQuery(ctx context.Context, req domain.QueryRequest) (domain.QueryResponse, error) {
	start := time.Now()
	if req.Query == "" {
		log.Printf("QueryID: <none> - Empty query in %.3fs", time.Since(start).Seconds())
		return domain.QueryResponse{}, errors.New("empty query provided")
	}

	answer, err := qs.repo.QueryKnowledgeGraph(ctx, req.Query)
	if err != nil {
		log.Printf("QueryID: %s - Failed to query knowledge graph in %.3fs: %v", req.Query, time.Since(start).Seconds(), err)
		return domain.QueryResponse{}, err
	}
	log.Printf("QueryID: %s - Successfully queried knowledge graph in %.3fs, answer: %s", req.Query, time.Since(start).Seconds(), answer)

	return domain.QueryResponse{Answer: answer}, nil
}

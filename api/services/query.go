package services

import (
	"context"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type QueryService struct {
	repo domain.QueryRepository
}

func NewQueryService(repo domain.QueryRepository) domain.QueryService {
	return &QueryService{repo: repo}
}

func (qs *QueryService) HandleQuery(ctx context.Context, req domain.QueryRequest) (domain.QueryResponse, error) {
	answer, err := qs.repo.QueryKnowledgeGraph(ctx, req.Query)
	if err != nil {
		return domain.QueryResponse{}, err
	}
	return domain.QueryResponse{Answer: answer}, nil
}

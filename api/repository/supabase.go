package repository

import (
	"context"
	"fmt"
	"log"
	"strings"

	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/supabase-community/supabase-go"
)

type SupabaseClient struct {
	client *supabase.Client
}

func NewSupabaseRepo(url, key string) domain.StoragePort {
	client, err := supabase.NewClient(url, key, nil)
	if err != nil {
		log.Fatalf("Failed to initialize Supabase client: %v", err)
	}
	log.Println("Supabase client initialized successfully")
	return &SupabaseClient{client: client}
}

func (sc *SupabaseClient) Insert(ctx context.Context, table string, data map[string]interface{}) error {
	_, _, err := sc.client.From(table).Insert(data, false, "", "", "").Execute()
	if err != nil {
		log.Printf("Error inserting data into table %s: %v", table, err)
		return err
	}
	return nil
}

func (sc *SupabaseClient) QueryKnowledgeGraphSupabase(ctx context.Context, query string) (string, error) {
	// Normalize query for tsvector search
	normalized := strings.ToLower(strings.TrimSpace(query))
	if normalized == "" {
		log.Printf("Empty query provided")
		return "No answer found.", nil
	}
	queryStr := strings.ReplaceAll(normalized, " ", " & ")
	log.Printf("Executing TextSearch with query: %s", queryStr)

	type EntityResult struct {
		ID       string                 `json:"id"`
		Type     string                 `json:"type"`
		Name     string                 `json:"name"`
		Metadata map[string]interface{} `json:"metadata"`
	}
	var results []EntityResult

	// Try TextSearch
	_, err := sc.client.From("entities").
		Select("id, type, name, metadata", "", false).
		TextSearch("search_vector", queryStr, "plain", "english").
		ExecuteTo(&results)
	if err != nil {
		log.Printf("Supabase TextSearch error: %v, raw: %+v", err, err)
		// Fallback to ILIKE query
		log.Printf("Falling back to ILIKE query for: %s", normalized)
		// Split query to handle multi-word searches
		words := strings.Fields(normalized)
		queryBuilder := sc.client.From("entities").Select("id, type, name, metadata", "", false)
		for _, word := range words {
			queryBuilder = queryBuilder.Ilike("name", "%"+word+"%")
		}
		_, err = queryBuilder.ExecuteTo(&results)
		if err != nil {
			log.Printf("Supabase ILIKE query error: %v, raw: %+v", err, err)
			return "", fmt.Errorf("supabase query error: %v", err)
		}
	}

	log.Printf("Supabase query '%s' returned %d results", queryStr, len(results))

	// Simple logic: Find person or project, check edges for relationships
	answer := "No answer found."
	for _, result := range results {
		if strings.Contains(normalized, "who owns") && result.Type == "project" {
			type EdgeResult struct {
				SourceID string                 `json:"source_id"`
				TargetID string                 `json:"target_id"`
				Type     string                 `json:"type"`
				Metadata map[string]interface{} `json:"metadata"`
			}
			var edges []EdgeResult
			_, err := sc.client.From("edges").
				Select("source_id, target_id, type, metadata", "", false).
				Eq("target_id", result.ID).
				Eq("type", "owns").
				ExecuteTo(&edges)
			if err != nil {
				log.Printf("Error querying edges: %v", err)
				continue
			}
			for _, edge := range edges {
				var owner EntityResult
				_, err := sc.client.From("entities").
					Select("id, type, name, metadata", "", false).
					Eq("id", edge.SourceID).
					Single().
					ExecuteTo(&owner)
				if err == nil && owner.Name != "" {
					answer = fmt.Sprintf("%s owns %s", owner.Name, result.Name)
					if edge.Metadata != nil {
						if ticket, ok := edge.Metadata["ticket"].(string); ok {
							answer += fmt.Sprintf(", %s", ticket)
						}
					}
					break
				}
			}
		}
	}

	return answer, nil
}

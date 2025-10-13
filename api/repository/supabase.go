// repository/supabase.go
package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/supabase-community/supabase-go"
)

// SupabaseRepo implements the StoragePort interface for Supabase operations.
type SupabaseRepo struct {
	client *supabase.Client
}

// NewSupabaseRepo creates a new SupabaseRepo.
func NewSupabaseRepo(url, key string) domain.StoragePort {
	client, err := supabase.NewClient(url, key, nil)
	if err != nil {
		log.Fatalf("Failed to initialize Supabase client: %v", err)
	}
	return &SupabaseRepo{client: client}
}

// Insert stores data in a Supabase table.
func (r *SupabaseRepo) Insert(ctx context.Context, table string, data map[string]interface{}) error {
	start := time.Now()
	if table != "raw_data" {
		log.Printf("RecordID: %v - Invalid table: %s in %.3fs", data["record_id"], table, time.Since(start).Seconds())
		return fmt.Errorf("invalid table: %s", table)
	}
	if data["record_id"] == nil || data["record_id"] == "" {
		log.Printf("RecordID: <none> - Empty record ID in %.3fs", time.Since(start).Seconds())
		return fmt.Errorf("empty record ID for table %s", table)
	}
	if data["source"] != "slack" && data["source"] != "github" {
		log.Printf("RecordID: %v - Invalid source: %v in %.3fs", data["record_id"], data["source"], time.Since(start).Seconds())
		return fmt.Errorf("invalid source: %v", data["source"])
	}

	_, _, err := r.client.From(table).Insert(data, false, "", "", "").Execute()
	if err != nil {
		log.Printf("RecordID: %v - Failed to insert into %s in %.3fs: %v", data["record_id"], table, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to insert into %s: %v", table, err)
	}
	log.Printf("RecordID: %v - Successfully inserted into %s in %.3fs", data["record_id"], table, time.Since(start).Seconds())
	return nil
}

// QueryKnowledgeGraphSupabase queries the Supabase knowledge graph.
func (r *SupabaseRepo) QueryKnowledgeGraphSupabase(ctx context.Context, query string) (string, error) {
	start := time.Now()
	if strings.TrimSpace(query) == "" {
		log.Printf("QueryID: <none> - Empty query in %.3fs", time.Since(start).Seconds())
		return "", fmt.Errorf("empty query provided")
	}

	// Execute PostgREST query (example: search raw_data content)
	// Note: Assumes hf_processor.py populates entities/edges for actual graph queries
	result, _, err := r.client.From("raw_data").Select("content", "", false).
		Like("content", "%"+strings.ToLower(query)+"%").Execute()
	if err != nil {
		log.Printf("QueryID: %s - Failed to query Supabase in %.3fs: %v", query, time.Since(start).Seconds(), err)
		return "", fmt.Errorf("failed to query Supabase: %v", err)
	}

	var records []map[string]interface{}
	if err := json.Unmarshal(result, &records); err != nil {
		log.Printf("QueryID: %s - Failed to parse Supabase response in %.3fs: %v", query, time.Since(start).Seconds(), err)
		return "", fmt.Errorf("failed to parse Supabase response: %v", err)
	}

	if len(records) == 0 {
		log.Printf("QueryID: %s - No results found in Supabase in %.3fs", query, time.Since(start).Seconds())
		return "", fmt.Errorf("no results found for query: %s", query)
	}

	// Return the first matching content (simplified for demo; hf_processor.py enhances this)
	answer := records[0]["content"].(string)
	log.Printf("QueryID: %s - Successfully queried Supabase in %.3fs, answer: %s", query, time.Since(start).Seconds(), answer)
	return answer, nil
}

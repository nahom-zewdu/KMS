// repository/supabase.go
// Package repository implements the StoragePort interface for Supabase operations, providing
// methods to insert, query, and search the database. It supports the KnowSphere backend's hybrid
// architecture, handling GitHub/Slack event storage, knowledge graph queries, and contribution
// metrics. The implementation ensures performance (<50ms inserts), reliability (error logging),
// and edge case handling (e.g., invalid tables, empty queries).

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
	client *supabase.Client // Supabase client for database operations
}

// NewSupabaseRepo creates a new SupabaseRepo with the provided URL and key.
// It initializes the Supabase client and logs fatal errors if initialization fails.
// Args:
//
//	url: Supabase project URL.
//	key: Supabase API key.
//
// Returns:
//
//	StoragePort implementation.
func NewSupabaseRepo(url, key string) domain.StoragePort {
	client, err := supabase.NewClient(url, key, nil)
	if err != nil {
		log.Fatalf("Failed to initialize Supabase client: %v", err)
	}
	return &SupabaseRepo{client: client}
}

// Insert stores data in a specified Supabase table, validating the table and data fields.
// It supports tables: raw_data, events, contributions, entities, edges, pull_requests, issues.
// Args:
//
//	ctx: Context for cancellation and timeouts.
//	table: Target table name.
//	data: Map of column names to values.
//
// Returns:
//
//	error if the table is invalid, data is incomplete, or insertion fails.
func (r *SupabaseRepo) Insert(ctx context.Context, table string, data map[string]interface{}) error {
	start := time.Now()
	// Validate table name
	validTables := map[string]bool{
		"raw_data":             true,
		"events":               true,
		"contributions":        true,
		"entities":             true,
		"edges":                true,
		"pull_requests":        true,
		"issues":               true,
		"company_integrations": true,
	}
	if !validTables[table] {
		log.Printf("RecordID: %v - Invalid table: %s in %.3fs", data["record_id"], table, time.Since(start).Seconds())
		return fmt.Errorf("invalid table: %s", table)
	}

	// Validate record_id for relevant tables
	if table == "raw_data" {
		if data["record_id"] == nil || data["record_id"] == "" {
			log.Printf("RecordID: <none> - Empty record ID in %.3fs", time.Since(start).Seconds())
			return fmt.Errorf("empty record ID for table %s", table)
		}
	}

	// Validate source for relevant tables
	if table == "raw_data" || table == "events" {
		source, ok := data["source"].(string)
		if !ok || (source != "slack" && source != "github") {
			log.Printf("RecordID: %v - Invalid source: %v in %.3fs", data["record_id"], data["source"], time.Since(start).Seconds())
			return fmt.Errorf("invalid source: %v", data["source"])
		}
	}

	// Perform insert with upsert for contributions to handle updates
	_, _, err := r.client.From(table).Insert(data, table == "contributions", "", "", "").Execute()
	if err != nil {
		log.Printf("RecordID: %v - Failed to insert into %s in %.3fs: %v", data["record_id"], table, time.Since(start).Seconds(), err)
		return fmt.Errorf("failed to insert into %s: %v", table, err)
	}
	log.Printf("RecordID: %v - Successfully inserted into %s in %.3fs", data["record_id"], table, time.Since(start).Seconds())
	return nil
}

// Query retrieves records from a specified Supabase table based on a filter.
// It supports querying events (for idempotency), contributions (for metrics), and other tables.
// Args:
//
//	ctx: Context for cancellation and timeouts.
//	table: Target table name.
//	filter: Map of column names to values for filtering (e.g., {"delivery_id": "uuid"}).
//
// Returns:
//
//	Slice of matching records and error if query fails.
func (r *SupabaseRepo) Query(ctx context.Context, table string, filter map[string]interface{}) ([]map[string]interface{}, error) {
	start := time.Now()
	// Validate table name
	validTables := map[string]bool{
		"raw_data":             true,
		"events":               true,
		"contributions":        true,
		"entities":             true,
		"edges":                true,
		"pull_requests":        true,
		"issues":               true,
		"company_integrations": true,
	}
	if !validTables[table] {
		log.Printf("Failed to query invalid table: %s in %.3fs", table, time.Since(start).Seconds())
		return nil, fmt.Errorf("invalid table: %s", table)
	}

	// Build query with filters
	query := r.client.From(table).Select("*", "", false)
	for key, value := range filter {
		query = query.Eq(key, fmt.Sprintf("%v", value))
	}

	// Execute query
	result, _, err := query.Execute()
	if err != nil {
		log.Printf("Failed to query %s in %.3fs: %v", table, time.Since(start).Seconds(), err)
		return nil, fmt.Errorf("failed to query %s: %v", table, err)
	}

	// Parse response
	var records []map[string]interface{}
	if err := json.Unmarshal(result, &records); err != nil {
		log.Printf("Failed to parse %s query response in %.3fs: %v", table, time.Since(start).Seconds(), err)
		return nil, fmt.Errorf("failed to parse %s query response: %v", table, err)
	}

	log.Printf("Successfully queried %s (%d records) in %.3fs", table, len(records), time.Since(start).Seconds())
	return records, nil
}

// QueryKnowledgeGraphSupabase searches the knowledge graph in Supabase for a given query.
// It searches raw_data content for matches, to be enhanced by hf_processor.py for entities/edges.
// Args:
//
//	ctx: Context for cancellation and timeouts.
//	query: Search query string (e.g., "payment API").
//
// Returns:
//
//	Matching content string and error if query fails.
func (r *SupabaseRepo) QueryKnowledgeGraphSupabase(ctx context.Context, query string) (string, error) {
	start := time.Now()
	// Validate query
	if strings.TrimSpace(query) == "" {
		log.Printf("QueryID: <none> - Empty query in %.3fs", time.Since(start).Seconds())
		return "", fmt.Errorf("empty query provided")
	}

	// Search raw_data content (to be enhanced by entities/edges in hf_processor.py)
	result, _, err := r.client.From("raw_data").Select("content", "", false).
		Like("content", "%"+strings.ToLower(query)+"%").Execute()
	if err != nil {
		log.Printf("QueryID: %s - Failed to query Supabase in %.3fs: %v", query, time.Since(start).Seconds(), err)
		return "", fmt.Errorf("failed to query Supabase: %v", err)
	}

	// Parse response
	var records []map[string]interface{}
	if err := json.Unmarshal(result, &records); err != nil {
		log.Printf("QueryID: %s - Failed to parse Supabase response in %.3fs: %v", query, time.Since(start).Seconds(), err)
		return "", fmt.Errorf("failed to parse Supabase response: %v", err)
	}

	// Return first match or error
	if len(records) == 0 {
		log.Printf("QueryID: %s - No results found in Supabase in %.3fs", query, time.Since(start).Seconds())
		return "", fmt.Errorf("no results found for query: %s", query)
	}

	answer := records[0]["content"].(string)
	log.Printf("QueryID: %s - Successfully queried Supabase in %.3fs, answer: %s", query, time.Since(start).Seconds(), answer)
	return answer, nil
}

// ResolveCompanyByIntegration looks up company_id from company_integrations.
// It queries Supabase for a matching provider and external_id, returning the company_id if found.
// Args:
//
//	ctx: Context for cancellation and timeouts.
//	provider: Integration provider (e.g., "github").
//	externalID: External ID from the provider (e.g., GitHub org ID).
//
// Returns:
//
//	company_id string if found, or empty string if not found, and error if query fails.
func (r *SupabaseRepo) ResolveCompanyByIntegration(ctx context.Context, provider, externalID string) (string, error) {
	start := time.Now()

	result, _, err := r.client.From("company_integrations").
		Select("company_id", "", false).
		Eq("provider", provider).
		Eq("external_id", externalID).
		Eq("is_active", "true").
		Execute()

	if err != nil {
		log.Printf("Failed to resolve company for %s:%s in %.3fs: %v", provider, externalID, time.Since(start).Seconds(), err)
		return "", fmt.Errorf("failed to resolve company: %v", err)
	}

	var records []map[string]interface{}
	if err := json.Unmarshal(result, &records); err != nil {
		return "", fmt.Errorf("failed to parse company resolution: %v", err)
	}

	if len(records) == 0 {
		log.Printf("No company found for %s:%s in %.3fs", provider, externalID, time.Since(start).Seconds())
		return "", nil // not an error — just unmapped
	}

	companyID, _ := records[0]["company_id"].(string)
	log.Printf("Resolved company %s for %s:%s in %.3fs", companyID, provider, externalID, time.Since(start).Seconds())
	return companyID, nil
}

// ResolveCompanyByInstallation looks up company_id from company_integrations using installation_id.
// It queries Supabase for a matching installation_id, returning the company_id if found.
// Args:
//
//	ctx: Context for cancellation and timeouts.
//	installationID: Installation ID from the provider (e.g., GitHub App installation ID).
//
// Returns:
//
//	company_id string if found, or empty string if not found, and error if query fails.
func (r *SupabaseRepo) ResolveCompanyByInstallation(ctx context.Context, installationID string) (string, error) {
	start := time.Now()

	result, _, err := r.client.From("company_integrations").
		Select("company_id", "", false).
		Eq("provider", "github").
		Eq("installation_id", installationID).
		Eq("is_active", "true").
		Execute()

	if err != nil {
		log.Printf("Failed to resolve company for installation %s in %.3fs: %v", installationID, time.Since(start).Seconds(), err)
		return "", fmt.Errorf("failed to resolve company: %v", err)
	}

	var records []map[string]interface{}
	if err := json.Unmarshal(result, &records); err != nil {
		return "", fmt.Errorf("failed to parse company resolution: %v", err)
	}

	if len(records) == 0 {
		log.Printf("No company found for installation %s in %.3fs", installationID, time.Since(start).Seconds())
		return "", nil // not an error — just unmapped
	}

	companyID, _ := records[0]["company_id"].(string)
	log.Printf("Resolved company %s for installation %s in %.3fs", companyID, installationID, time.Since(start).Seconds())
	return companyID, nil
}

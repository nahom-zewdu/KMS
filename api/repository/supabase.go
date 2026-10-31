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
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/supabase-community/supabase-go"
)

// SupabaseRepo implements the StoragePort interface for Supabase operations.
type SupabaseRepo struct {
	client     *supabase.Client
	projectURL string
	apiKey     string
	httpClient *http.Client
}

const maxSupabaseAuthResponseBytes = 64 << 10

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
	return &SupabaseRepo{
		client:     client,
		projectURL: strings.TrimRight(url, "/"),
		apiKey:     key,
		httpClient: &http.Client{Timeout: 10 * time.Second},
	}
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
		"company_members":      true,
		"repositories":         true,
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

// AuthenticateUser delegates access-token validation to Supabase Auth rather than
// trusting client claims or introducing a separate JWT signing configuration.
func (r *SupabaseRepo) AuthenticateUser(ctx context.Context, accessToken string) (string, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, r.projectURL+"/auth/v1/user", nil)
	if err != nil {
		return "", fmt.Errorf("create Supabase user validation request: %w", err)
	}
	request.Header.Set("apikey", r.apiKey)
	request.Header.Set("Authorization", "Bearer "+accessToken)
	response, err := r.httpClient.Do(request)
	if err != nil {
		return "", fmt.Errorf("validate Supabase access token: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		if response.StatusCode == http.StatusBadRequest || response.StatusCode == http.StatusUnauthorized || response.StatusCode == http.StatusForbidden {
			return "", domain.ErrUnauthenticated
		}
		return "", fmt.Errorf("Supabase rejected access token with status %d", response.StatusCode)
	}

	userBody, err := io.ReadAll(io.LimitReader(response.Body, maxSupabaseAuthResponseBytes+1))
	if err != nil {
		return "", fmt.Errorf("read Supabase user response: %w", err)
	}
	if len(userBody) > maxSupabaseAuthResponseBytes {
		return "", fmt.Errorf("Supabase user response exceeded size limit")
	}
	var user struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(userBody, &user); err != nil {
		return "", fmt.Errorf("decode Supabase user response: %w", err)
	}
	if strings.TrimSpace(user.ID) == "" {
		return "", fmt.Errorf("Supabase user response omitted id")
	}
	return user.ID, nil
}

func (r *SupabaseRepo) IsCompanyMember(ctx context.Context, userID, companyID string) (bool, error) {
	memberships, err := r.queryWithFilters(ctx, "company_members", map[string]string{
		"user_id":    userID,
		"company_id": companyID,
	})
	if err != nil {
		return false, err
	}
	return len(memberships) > 0, nil
}

func (r *SupabaseRepo) ResolveRepositoryForCompany(ctx context.Context, companyID, repository string) (string, error) {
	repository = strings.TrimSpace(repository)
	if repository == "" {
		return "", fmt.Errorf("repository is required")
	}
	filter := map[string]interface{}{"company_id": companyID}
	if isUUID(repository) {
		filter["id"] = repository
	} else {
		filter["full_name"] = repository
	}
	stringFilter := make(map[string]string, len(filter))
	for key, value := range filter {
		stringFilter[key] = fmt.Sprint(value)
	}
	repositories, err := r.queryWithFilters(ctx, "repositories", stringFilter)
	if err != nil {
		return "", err
	}
	for _, repo := range repositories {
		fullName, _ := repo["full_name"].(string)
		if strings.TrimSpace(fullName) != "" {
			return fullName, nil
		}
	}
	return "", nil
}

func (r *SupabaseRepo) queryWithFilters(ctx context.Context, table string, filters map[string]string) ([]map[string]interface{}, error) {
	if table != "company_members" && table != "repositories" {
		return nil, fmt.Errorf("invalid authorization lookup table: %s", table)
	}
	projectURL, err := url.Parse(r.projectURL)
	if err != nil {
		return nil, fmt.Errorf("parse Supabase project URL: %w", err)
	}
	projectURL.Path = strings.TrimRight(projectURL.Path, "/") + "/rest/v1/" + table
	query := projectURL.Query()
	query.Set("select", "*")
	for key, value := range filters {
		query.Set(key, "eq."+value)
	}
	projectURL.RawQuery = query.Encode()

	request, err := http.NewRequestWithContext(ctx, http.MethodGet, projectURL.String(), nil)
	if err != nil {
		return nil, fmt.Errorf("create Supabase authorization lookup: %w", err)
	}
	request.Header.Set("apikey", r.apiKey)
	request.Header.Set("Authorization", "Bearer "+r.apiKey)
	response, err := r.httpClient.Do(request)
	if err != nil {
		return nil, fmt.Errorf("query Supabase authorization data: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Supabase authorization lookup failed with status %d", response.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, (1<<20)+1))
	if err != nil {
		return nil, fmt.Errorf("read Supabase authorization response: %w", err)
	}
	if len(body) > 1<<20 {
		return nil, fmt.Errorf("Supabase authorization response exceeded size limit")
	}
	var rows []map[string]interface{}
	if err := json.Unmarshal(body, &rows); err != nil {
		return nil, fmt.Errorf("decode Supabase authorization response: %w", err)
	}
	return rows, nil
}

func isUUID(value string) bool {
	if len(value) != 36 || value[8] != '-' || value[13] != '-' || value[18] != '-' || value[23] != '-' {
		return false
	}
	for i, r := range value {
		if i == 8 || i == 13 || i == 18 || i == 23 {
			continue
		}
		if !((r >= '0' && r <= '9') || (r >= 'a' && r <= 'f') || (r >= 'A' && r <= 'F')) {
			return false
		}
	}
	return true
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

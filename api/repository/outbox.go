package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"

	"github.com/nahom-zewdu/kMS/api/domain"
)

func (r *SupabaseRepo) PersistIngestion(
	ctx context.Context,
	event, rawData map[string]interface{},
	job domain.JobPayload,
) error {
	if !realCompanyID(job.CompanyID) || strings.TrimSpace(job.RecordID) == "" {
		return fmt.Errorf("a real company_id and record_id are required for outbox persistence")
	}
	if event["company_id"] != job.CompanyID || rawData["company_id"] != job.CompanyID ||
		event["delivery_id"] != job.RecordID || rawData["record_id"] != job.RecordID {
		return fmt.Errorf("event, raw-data, and job identities do not match")
	}
	_, err := r.callOutboxRPC(ctx, "persist_ingestion_with_outbox", map[string]interface{}{
		"p_event":    event,
		"p_raw_data": rawData,
		"p_job":      job,
	})
	return err
}

func (r *SupabaseRepo) ClaimIngestionOutbox(
	ctx context.Context,
	workerID string,
	limit int,
) ([]domain.IngestionOutboxRecord, error) {
	workerID = strings.TrimSpace(workerID)
	if workerID == "" {
		return nil, fmt.Errorf("outbox worker_id is required")
	}
	response, err := r.callOutboxRPC(ctx, "claim_ingestion_outbox", map[string]interface{}{
		"p_worker_id":     workerID,
		"p_limit":         limit,
		"p_lease_seconds": 180,
	})
	if err != nil {
		return nil, err
	}
	var rows []struct {
		ID         string            `json:"id"`
		JobPayload domain.JobPayload `json:"job_payload"`
	}
	if err := json.Unmarshal(response, &rows); err != nil {
		return nil, fmt.Errorf("decode claimed ingestion outbox rows: %w", err)
	}
	records := make([]domain.IngestionOutboxRecord, 0, len(rows))
	for _, row := range rows {
		if strings.TrimSpace(row.ID) == "" {
			return nil, fmt.Errorf("claimed ingestion outbox row has no id")
		}
		records = append(records, domain.IngestionOutboxRecord{ID: row.ID, Payload: row.JobPayload})
	}
	return records, nil
}

func (r *SupabaseRepo) MarkIngestionOutboxPublished(ctx context.Context, id, workerID string) error {
	response, err := r.callOutboxRPC(ctx, "mark_ingestion_outbox_published", map[string]interface{}{
		"p_id":        id,
		"p_worker_id": workerID,
	})
	if err != nil {
		return err
	}
	var marked bool
	if err := json.Unmarshal(response, &marked); err != nil {
		return fmt.Errorf("decode outbox published status: %w", err)
	}
	if !marked {
		return fmt.Errorf("outbox publish lease was not held by worker %q", workerID)
	}
	return nil
}

func (r *SupabaseRepo) FailIngestionOutbox(ctx context.Context, id, workerID, failure string) error {
	response, err := r.callOutboxRPC(ctx, "fail_ingestion_outbox", map[string]interface{}{
		"p_id":           id,
		"p_worker_id":    workerID,
		"p_error":        boundedOutboxError(failure),
		"p_max_attempts": 12,
	})
	if err != nil {
		return err
	}
	var status string
	if err := json.Unmarshal(response, &status); err != nil {
		return fmt.Errorf("decode outbox failure status: %w", err)
	}
	if status != "pending" && status != "dead_letter" {
		return fmt.Errorf("outbox failure update returned unexpected status %q", status)
	}
	return nil
}

func (r *SupabaseRepo) callOutboxRPC(ctx context.Context, function string, args map[string]interface{}) ([]byte, error) {
	body, err := json.Marshal(args)
	if err != nil {
		return nil, fmt.Errorf("marshal %s arguments: %w", function, err)
	}
	endpoint, err := url.JoinPath(r.projectURL, "rest", "v1", "rpc", function)
	if err != nil {
		return nil, fmt.Errorf("build %s endpoint: %w", function, err)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, strings.NewReader(string(body)))
	if err != nil {
		return nil, fmt.Errorf("create %s request: %w", function, err)
	}
	request.Header.Set("apikey", r.apiKey)
	request.Header.Set("Authorization", "Bearer "+r.apiKey)
	request.Header.Set("Content-Type", "application/json")
	response, err := r.httpClient.Do(request)
	if err != nil {
		return nil, fmt.Errorf("call Supabase RPC %s: %w", function, err)
	}
	defer response.Body.Close()
	responseBody, err := io.ReadAll(io.LimitReader(response.Body, (4<<20)+1))
	if err != nil {
		return nil, fmt.Errorf("read Supabase RPC %s response: %w", function, err)
	}
	if len(responseBody) > 4<<20 {
		return nil, fmt.Errorf("Supabase RPC %s response exceeded size limit", function)
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, fmt.Errorf("Supabase RPC %s returned status %d: %s", function, response.StatusCode, strings.TrimSpace(string(responseBody)))
	}
	return responseBody, nil
}

func realCompanyID(companyID string) bool {
	companyID = strings.TrimSpace(companyID)
	return companyID != "" && !strings.EqualFold(companyID, "default")
}

func boundedOutboxError(message string) string {
	const maxErrorBytes = 1000
	if len(message) <= maxErrorBytes {
		return message
	}
	return message[:maxErrorBytes]
}

var _ domain.IngestionOutboxRepository = (*SupabaseRepo)(nil)

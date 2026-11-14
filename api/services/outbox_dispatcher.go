package services

import (
	"context"
	"errors"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/nahom-zewdu/kMS/api/domain"
)

const (
	outboxDispatchBatchSize = 5
	outboxPollInterval      = time.Second
)

type IngestionOutboxDispatcher struct {
	outbox   domain.IngestionOutboxRepository
	redis    domain.RedisStream
	workerID string
}

func NewIngestionOutboxDispatcher(outbox domain.IngestionOutboxRepository, redis domain.RedisStream) *IngestionOutboxDispatcher {
	return &IngestionOutboxDispatcher{
		outbox:   outbox,
		redis:    redis,
		workerID: "go-outbox-" + uuid.NewString(),
	}
}

func (d *IngestionOutboxDispatcher) Run(ctx context.Context) {
	ticker := time.NewTicker(outboxPollInterval)
	defer ticker.Stop()
	for {
		if err := d.DispatchOnce(ctx); err != nil && !errors.Is(err, context.Canceled) {
			log.Printf("Ingestion outbox dispatch batch failed: %v", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func (d *IngestionOutboxDispatcher) DispatchOnce(ctx context.Context) error {
	records, err := d.outbox.ClaimIngestionOutbox(ctx, d.workerID, outboxDispatchBatchSize)
	if err != nil {
		return fmt.Errorf("claim ingestion outbox: %w", err)
	}

	var failures []error
	for _, record := range records {
		job := record.Payload
		if err := validateOutboxJob(job); err != nil {
			failures = append(failures, d.failRecord(ctx, record.ID, err))
			continue
		}
		stream := job.Source + "_jobs"
		publishCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
		err := d.redis.Publish(publishCtx, stream, job)
		cancel()
		if err != nil {
			failures = append(failures, d.failRecord(ctx, record.ID, fmt.Errorf("publish to %s: %w", stream, err)))
			continue
		}
		if err := d.outbox.MarkIngestionOutboxPublished(ctx, record.ID, d.workerID); err != nil {
			failures = append(failures, fmt.Errorf("mark outbox %s published after Redis accepted job: %w", record.ID, err))
		}
	}
	return errors.Join(failures...)
}

func (d *IngestionOutboxDispatcher) failRecord(ctx context.Context, id string, failure error) error {
	if err := d.outbox.FailIngestionOutbox(ctx, id, d.workerID, failure.Error()); err != nil {
		return fmt.Errorf("%v; persist outbox failure: %w", failure, err)
	}
	return failure
}

func validateOutboxJob(job domain.JobPayload) error {
	companyID := strings.TrimSpace(job.CompanyID)
	if companyID == "" || strings.EqualFold(companyID, "default") {
		return fmt.Errorf("outbox job requires a real company_id")
	}
	if strings.TrimSpace(job.RecordID) == "" {
		return fmt.Errorf("outbox job requires a record_id")
	}
	if job.Source != "slack" && job.Source != "github" {
		return fmt.Errorf("outbox job has unsupported source %q", job.Source)
	}
	return nil
}

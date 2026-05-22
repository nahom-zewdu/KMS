// services/playbook.go
// Package services implements the PlaybookService for generating onboarding playbooks for new hires.
// It integrates with the knowledge graph to pull relevant context about people, systems, and recent activity,
// creating a comprehensive playbook tailored to the new hire's role. The service is designed to be called
// from an API endpoint, which will trigger the generation process and return a link to the generated playbook.
package services

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

// PlaybookService implements domain.PlaybookService
type PlaybookService struct {
	generator *playbooks.PlaybookGenerator // We'll import from Python later via API
}

// NewPlaybookService creates a new playbook service
func NewPlaybookService() domain.PlaybookService {
	return &PlaybookService{}
}

// GeneratePlaybook calls the Python generator (we'll use HTTP call for now)
func (p *PlaybookService) GeneratePlaybook(ctx context.Context, role string, employeeName string) (string, error) {
	start := time.Now()
	log.Printf("Generating playbook for role: %s, employee: %s", role, employeeName)

	// TODO: Call Python service via HTTP (we'll implement this next)
	// For now, return a placeholder
	playbookURL := fmt.Sprintf("https://kms.company.com/onboard/%s-%s", role, employeeName)

	log.Printf("Playbook generated in %.3fs", time.Since(start).Seconds())
	return fmt.Sprintf("✅ Onboarding playbook for **%s** is ready!\n\nView it here: %s", role, playbookURL), nil
}

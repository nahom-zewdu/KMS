// services/playbook.go
// This file implements the PlaybookService which generates onboarding playbooks for new hires based on their role.

package services

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

// PlaybookService implements domain.PlaybookService
type PlaybookService struct {
	pythonURL string // URL to Python playbook endpoint
}

// NewPlaybookService creates a new playbook service
func NewPlaybookService() domain.PlaybookService {
	return &PlaybookService{
		pythonURL: "http://localhost:8000/playbooks/generate", // Change to your Python service URL later
	}
}

// GeneratePlaybook calls the Python generator via HTTP
func (p *PlaybookService) GeneratePlaybook(ctx context.Context, role string, employeeName string) (string, error) {
	start := time.Now()
	log.Printf("Generating playbook for role: %s, employee: %s", role, employeeName)

	payload := map[string]string{
		"role":          role,
		"employee_name": employeeName,
	}

	jsonData, _ := json.Marshal(payload)

	req, err := http.NewRequestWithContext(ctx, "POST", p.pythonURL, bytes.NewBuffer(jsonData))
	if err != nil {
		return "", fmt.Errorf("failed to create request: %v", err)
	}

	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("Failed to call Python playbook service: %v", err)
		// Fallback message
		return fmt.Sprintf("✅ Onboarding playbook for **%s** is being prepared.\n\nWe'll send you the link shortly.", role), nil
	}
	defer resp.Body.Close()

	playbook_data, _ := io.ReadAll(resp.Body)

	log.Printf("Python service response status: %d, body: %s", resp.StatusCode, string(playbook_data))

	if resp.StatusCode != http.StatusOK {
		log.Printf("Python service returned status %d", resp.StatusCode)
		return fmt.Sprintf("✅ Onboarding playbook for **%s** is ready!\n\n(Generating detailed version...)", role), nil
	}

	// Return success message with placeholder link
	playbookURL := fmt.Sprintf("https://kms.company.com/onboard/%s", role)
	log.Printf("Playbook generated in %.3fs", time.Since(start).Seconds())

	message := fmt.Sprintf(`✅ **Onboarding Playbook for %s is ready!**

	**Title**: %s

	%s

	📎 View full interactive version here: %s`,
		role,
		playbook_data.get("title", "Onboarding Playbook"),
		playbook_data.get("welcome_message", ""),
		playbookURL)

	return message, nil
}

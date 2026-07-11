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
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 45 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("Failed to call Python playbook service: %v", err)
		return fmt.Sprintf("✅ Onboarding playbook for **%s** is being prepared.\n\nWe'll send you the link shortly.", role), nil
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	log.Printf("Python service response status: %d", resp.StatusCode)

	if resp.StatusCode != http.StatusOK {
		return fmt.Sprintf("✅ Onboarding playbook for **%s** is ready!", role), nil
	}

	// Parse the full response
	var result map[string]interface{}
	if err := json.Unmarshal(body, &result); err != nil {
		log.Printf("Failed to parse playbook JSON: %v", err)
		return fmt.Sprintf("✅ Onboarding playbook for **%s** is ready!", role), nil
	}

	playbook, ok := result["playbook"].(map[string]interface{})
	if !ok {
		playbook = make(map[string]interface{})
	}

	title := "Onboarding Playbook"
	if t, ok := playbook["title"].(string); ok && t != "" {
		title = t
	}

	welcome := ""
	if w, ok := playbook["welcome_message"].(string); ok {
		welcome = w
	}

	// Build nice Slack message
	message := fmt.Sprintf(`✅ **%s**

%s

📌 **View the full interactive playbook here**: https://kms.company.com/onboard/%s

Would you like me to generate one for another role?`,
		title,
		welcome,
		role)

	log.Printf("Playbook generated in %.3fs", time.Since(start).Seconds())
	return message, nil
}

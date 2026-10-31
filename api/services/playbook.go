// services/playbook.go
// This file implements the PlaybookService which generates onboarding playbooks for new hires based on their role.

package services

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
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
		pythonURL: "http://localhost:8000/internal/playbooks/generate",
	}
}

// GeneratePlaybook calls the Python generator via HTTP
func (p *PlaybookService) GeneratePlaybook(ctx context.Context, role, employeeName, companyID string) (string, error) {
	start := time.Now()
	companyID = strings.TrimSpace(companyID)
	if companyID == "" || strings.EqualFold(companyID, "default") {
		return "", fmt.Errorf("a real company_id is required for playbook generation")
	}
	log.Printf("Generating playbook for role: %s, employee: %s", role, employeeName)

	payload := map[string]string{
		"role":          role,
		"employee_name": employeeName,
		"company_id":    companyID,
	}

	jsonData, err := json.Marshal(payload)
	if err != nil {
		return "", fmt.Errorf("marshal playbook request: %w", err)
	}
	serviceToken, err := createPlaybookServiceToken(companyID, time.Now())
	if err != nil {
		return "", err
	}

	req, err := http.NewRequestWithContext(ctx, "POST", p.pythonURL, bytes.NewBuffer(jsonData))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+serviceToken)

	client := &http.Client{Timeout: 45 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("Failed to call Python playbook service: %v", err)
		return "", fmt.Errorf("call Python playbook service: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20+1))
	if err != nil {
		return "", fmt.Errorf("read Python playbook response: %w", err)
	}
	if len(body) > 1<<20 {
		return "", fmt.Errorf("Python playbook response exceeded size limit")
	}
	log.Printf("Python service response status: %d", resp.StatusCode)

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("Python playbook service returned status %d", resp.StatusCode)
	}

	var result struct {
		Success  bool   `json:"success"`
		Error    string `json:"error"`
		Playbook *struct {
			Title          string `json:"title"`
			WelcomeMessage string `json:"welcome_message"`
		} `json:"playbook"`
	}
	if err := json.Unmarshal(body, &result); err != nil {
		return "", fmt.Errorf("decode Python playbook response: %w", err)
	}
	if !result.Success {
		if result.Error != "" {
			return "", fmt.Errorf("Python playbook service failed: %s", result.Error)
		}
		return "", fmt.Errorf("Python playbook service reported an unsuccessful response")
	}
	if result.Playbook == nil {
		return "", fmt.Errorf("Python playbook service response is missing playbook data")
	}

	title := "Onboarding Playbook"
	if result.Playbook.Title != "" {
		title = result.Playbook.Title
	}

	welcome := result.Playbook.WelcomeMessage

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

func createPlaybookServiceToken(companyID string, now time.Time) (string, error) {
	secret := os.Getenv("INTERNAL_SERVICE_SECRET")
	issuer := os.Getenv("INTERNAL_SERVICE_ISSUER")
	audience := os.Getenv("INTERNAL_SERVICE_AUDIENCE")
	if len(secret) < 32 || strings.TrimSpace(issuer) == "" || strings.TrimSpace(audience) == "" {
		return "", fmt.Errorf("internal service token configuration is incomplete")
	}

	header, err := json.Marshal(map[string]string{"alg": "HS256", "typ": "JWT"})
	if err != nil {
		return "", fmt.Errorf("marshal internal token header: %w", err)
	}
	claims, err := json.Marshal(map[string]interface{}{
		"iss":        issuer,
		"aud":        audience,
		"sub":        "kms-go-api",
		"role":       "service",
		"company_id": companyID,
		"iat":        now.Unix(),
		"exp":        now.Add(time.Minute).Unix(),
	})
	if err != nil {
		return "", fmt.Errorf("marshal internal token claims: %w", err)
	}
	unsigned := base64.RawURLEncoding.EncodeToString(header) + "." +
		base64.RawURLEncoding.EncodeToString(claims)
	mac := hmac.New(sha256.New, []byte(secret))
	if _, err := mac.Write([]byte(unsigned)); err != nil {
		return "", fmt.Errorf("sign internal service token: %w", err)
	}
	signature := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	return unsigned + "." + signature, nil
}

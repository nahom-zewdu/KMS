// api/handlers/tenant_test.go
// This file contains unit tests for the tenant resolution logic defined in tenant.go.
// It tests the behavior of the resolveSlackTenant and resolveGitHubTenant functions under various scenarios, including unresolved tenants and conflicting mappings.
package handlers

import (
	"context"
	"errors"
	"testing"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type tenantStorage struct {
	installation string
	owner        string
}

func (s tenantStorage) Insert(context.Context, string, map[string]interface{}) error { return nil }
func (s tenantStorage) Query(context.Context, string, map[string]interface{}) ([]map[string]interface{}, error) {
	return nil, nil
}
func (s tenantStorage) QueryKnowledgeGraphSupabase(context.Context, string) (string, error) {
	return "", nil
}
func (s tenantStorage) ResolveCompanyByIntegration(context.Context, string, string) (string, error) {
	return s.owner, nil
}
func (s tenantStorage) ResolveCompanyByInstallation(context.Context, string) (string, error) {
	return s.installation, nil
}

var _ domain.StoragePort = tenantStorage{}

func TestResolveSlackTenantRejectsUnresolved(t *testing.T) {
	companyID, err := resolveSlackTenant(context.Background(), tenantStorage{}, "T1")
	if !errors.Is(err, errTenantNotFound) || companyID != "" {
		t.Fatalf("expected unresolved tenant, got company=%q err=%v", companyID, err)
	}
}

func TestResolveTenantRejectsDefault(t *testing.T) {
	companyID, err := resolveSlackTenant(context.Background(), tenantStorage{owner: " default "}, "T1")
	if !errors.Is(err, errTenantNotFound) || companyID != "" {
		t.Fatalf("expected default tenant to be rejected, got company=%q err=%v", companyID, err)
	}

	companyID, err = resolveGitHubTenant(context.Background(), tenantStorage{installation: "default"}, "I1", "")
	if !errors.Is(err, errTenantNotFound) || companyID != "" {
		t.Fatalf("expected default installation tenant to be rejected, got company=%q err=%v", companyID, err)
	}
}

func TestResolveGitHubTenantUsesInstallationAndRejectsConflict(t *testing.T) {
	companyID, err := resolveGitHubTenant(context.Background(), tenantStorage{
		installation: "company-installation",
		owner:        "company-owner",
	}, "I1", "owner")
	if !errors.Is(err, errTenantConflict) || companyID != "" {
		t.Fatalf("expected conflict, got company=%q err=%v", companyID, err)
	}

	companyID, err = resolveGitHubTenant(context.Background(), tenantStorage{
		installation: "company-installation",
	}, "I1", "")
	if err != nil || companyID != "company-installation" || companyID == "default" {
		t.Fatalf("expected installation tenant, got company=%q err=%v", companyID, err)
	}
}

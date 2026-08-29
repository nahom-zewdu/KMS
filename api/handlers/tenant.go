// api/handlers/tenant.go
// This file contains the tenant resolution logic for different integrations (Slack and GitHub).
// It defines functions to resolve the company ID associated with a given integration based on the provided identifiers (team ID for Slack, installation ID and owner login for GitHub).
// It also handles error cases such as tenant not found and tenant mappings conflict.
package handlers

import (
	"context"
	"errors"
	"strings"

	"github.com/nahom-zewdu/kMS/api/domain"
)

var (
	errTenantNotFound = errors.New("tenant not found")
	errTenantConflict = errors.New("tenant mappings conflict")
)

func resolveSlackTenant(ctx context.Context, storage domain.StoragePort, teamID string) (string, error) {
	companyID, err := storage.ResolveCompanyByIntegration(ctx, "slack", teamID)
	if err != nil {
		return "", err
	}
	companyID = normalizeCompanyID(companyID)
	if isUnresolvedCompany(companyID) {
		return "", errTenantNotFound
	}
	return companyID, nil
}

func resolveGitHubTenant(ctx context.Context, storage domain.StoragePort, installationID, ownerLogin string) (string, error) {
	var installationCompanyID string
	if installationID != "" {
		var err error
		installationCompanyID, err = storage.ResolveCompanyByInstallation(ctx, installationID)
		if err != nil {
			return "", err
		}
		installationCompanyID = normalizeCompanyID(installationCompanyID)
	}

	var ownerCompanyID string
	if ownerLogin != "" {
		var err error
		ownerCompanyID, err = storage.ResolveCompanyByIntegration(ctx, "github", ownerLogin)
		if err != nil {
			return "", err
		}
		ownerCompanyID = normalizeCompanyID(ownerCompanyID)
	}

	if isResolvedCompany(installationCompanyID) && isResolvedCompany(ownerCompanyID) && installationCompanyID != ownerCompanyID {
		return "", errTenantConflict
	}
	if isResolvedCompany(installationCompanyID) {
		return installationCompanyID, nil
	}
	if isResolvedCompany(ownerCompanyID) {
		return ownerCompanyID, nil
	}
	return "", errTenantNotFound
}

func isResolvedCompany(companyID string) bool {
	companyID = normalizeCompanyID(companyID)
	return companyID != "" && companyID != "default"
}

func isUnresolvedCompany(companyID string) bool {
	return !isResolvedCompany(companyID)
}

func normalizeCompanyID(companyID string) string {
	return strings.TrimSpace(companyID)
}

# Tenancy Architecture

## Model

KMS is company-scoped. A user can belong to companies through `company_members`, and integrations are associated with companies.

Company scope is propagated into ingestion and knowledge data, including raw data, entities, edges, repositories, and codebase records.

## Resolution

- Slack: provider team identity resolves through the company's Slack integration.
- GitHub: installation identity is authoritative when available; owner lookup is a fallback only when installation mapping does not resolve, and conflicting mappings must be rejected.

## Security invariant

No production event should be assigned to a shared `default` company. User-facing reads must derive and validate company membership rather than trusting an arbitrary client-provided company ID.

## Future security work

The live database does not currently have RLS enabled on every tenant-owned table. A complete membership-based RLS model is required before exposing those tables directly to untrusted clients. Until then, server-side service-role access must remain deliberate and isolated.

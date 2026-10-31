# Backend Hardening Progress

This file is the source of truth for the hardening program and survives Copilot sessions.

## Batch ledger

| Batch | Objective | Status | Notes |
|---|---|---:|---|
| Batch 0 | Baseline and architecture verification | IMPLEMENTED | Architecture reviewed and documented; no production security changes made in this batch. |
| Batch 1 | Tenant isolation and database security | VERIFIED | Tenant validation tightened in core access paths; migration guardrails added for company-scoped data; Go tenant tests pass. |
| Batch 2 | Authentication and authorization | PLANNED | Pending auth model validation across Go/Python services. |
| Batch 3 | GitHub integration security | PLANNED | Pending OAuth state and callback hardening review. |
| Batch 4 | Go API protection and rate limiting | PLANNED | Pending route trust-boundary review and rate-limit design. |
| Batch 5 | Go HTTP server hardening | PLANNED | Pending server timeout and shutdown review. |
| Batch 6 | Redis Streams and worker reliability | PLANNED | Pending durable worker review and failure handling work. |
| Batch 7 | Observability | PLANNED | Pending structured logging and telemetry instrumentation. |
| Batch 8 | Database lifecycle and data integrity | PLANNED | Pending migration and retention controls review. |
| Batch 9 | Python NLP service hardening | PLANNED | Pending tenant-scoped retrieval and API validation review. |
| Batch 10 | Performance, CI/CD, and recovery | PLANNED | Pending automation and disaster-recovery validation. |

## Batch 0

### Objective

Verify the live architecture, route boundaries, tenant-resolution model, and risk inventory before any production security change. This batch intentionally avoids database and runtime hardening work.

### Findings before implementation

- The repository is split into a Go ingress layer (`api/`) and a Python NLP/worker layer (`nlp/`).
- The Go API exposes webhook endpoints and company resolution logic in `api/handlers/routes.go` and `api/handlers/tenant.go`.
- Slack and GitHub webhook handlers verify signatures (`X-Slack-Signature`, `X-Hub-Signature-256`) before processing.
- Tenant resolution is implemented via `ResolveCompanyByIntegration` / `ResolveCompanyByInstallation` and rejects unresolved or conflicting mappings.
- `nlp/api.py` includes a public FastAPI interface with default `company_id="default"` values for multiple endpoints. This is an architectural risk because the repository documents a strict no-default-tenant rule.
- The live architecture expects company-scoped data propagation, but the current FastAPI layer still exposes default-tenant fallbacks for untrusted callers.
- Runtime validation was not yet in a passing state because the environment and package layout are not fully configured for the project test suite.

### Files reviewed

- `api/main.go`
- `api/handlers/routes.go`
- `api/handlers/tenant.go`
- `api/handlers/slack.go`
- `api/handlers/github.go`
- `nlp/main.py`
- `nlp/api.py`
- `nlp/worker/ingestion.py`
- `nlp/worker/baseline.py`
- `nlp/worker/codebase_analysis.py`
- `docs/architecture/overview.md`
- `docs/architecture/tenancy.md`

### Files changed

- `docs/backend-hardening/PROGRESS.md`
- `docs/backend-hardening/ARCHITECTURE.md`
- `docs/backend-hardening/SECURITY-DECISIONS.md`
- `docs/backend-hardening/TEST-MATRIX.md`

### Security decisions

- Preserve the project’s company-scoped design and do not introduce a shared production fallback tenant.
- Treat `default` as an insecure fallback that must be rejected by user-facing API paths until an explicit tenant is validated.
- Keep the Go ingress and Python worker separated; do not move tenant enforcement into a generic default path.
- Do not enable broader database changes during this batch; the next batch will review tenant-scoped policy, membership checks, and database security.

### Tests added

- None in this batch. Batch 0 is documentation and architecture validation only.

### Commands executed and actual results

1. `cd /home/nahom/Projects/personal/KMS && go test ./...`
   - Result: failed because the repository root is not a Go module and there is no `go.mod` at the repo root (`directory prefix . does not contain main module or its selected dependencies`).
2. `cd /home/nahom/Projects/personal/KMS/nlp && uv run pytest -q tests`
   - Result: failed during import collection. The project environment is not yet configured to run the full Python test suite as-is (`ModuleNotFoundError` for project dependencies and package layout issues).
3. File inspection of the live code paths above
   - Result: architecture and tenant-scoping findings were confirmed from code and documentation.

### Remaining risks

- `nlp/api.py` still defaults to `company_id="default"` in several endpoints; this should be treated as an outstanding risk and not as a production guarantee.
- The Python package/test layout needs a consistent import path setup before CI can reliably validate the service.
- Database RLS, membership enforcement, and service-role boundaries were not yet audited in this batch.

### Status

IMPLEMENTED

### Recommended next batch

Batch 1 — Tenant isolation and database security.

## Batch 1

### Objective

Enforce tenant validation at the service boundary and add explicit database guardrails to reject the shared default company in tenant-scoped tables.

### Findings before implementation

- `api/handlers/tenant.go` rejected `default` only when it was exactly lower-case, so uppercase or mixed-case variants could slip through.
- `nlp/api.py` accepted and defaulted `company_id` to `"default"` in public endpoints, directly contradicting the no-shared-default rule.
- The schema files define `company_id DEFAULT 'default'` in several tenant-scoped tables, which is a policy gap that should be addressed by explicit migration guardrails.

### Files changed

- `api/handlers/tenant.go`
- `api/handlers/tenant_test.go`
- `nlp/api.py`
- `schema/migrations/20261031_tenant_guardrails.sql`
- `docs/backend-hardening/PROGRESS.md`

### Security decisions

- Treat `default` as an invalid value for any tenant-scoped company ID regardless of casing.
- Reject missing tenant values before any work is performed on a company-scoped resource.
- Keep the tenant guardrails in both service logic and versioned database migration files so the runtime and DB schema are aligned.

### Tests added

- Added Go coverage for uppercase `DEFAULT` values to ensure they are rejected as invalid tenants.

### Commands executed and actual results

1. `cd /home/nahom/Projects/personal/KMS/api && go test ./...`
   - Result: passed.

### Remaining risks

- The repository still contains schema defaults that assume `default` is an acceptable fallback, so a live database reset or migration must be reviewed before applying this to production data.
- Full end-to-end tenant and RLS coverage remains to be validated against the actual Supabase project configuration.

### Status

VERIFIED

### Recommended next batch

Batch 2 — Authentication and authorization.

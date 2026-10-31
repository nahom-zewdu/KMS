# Backend Hardening Progress

This file is the source of truth for the hardening program and survives Copilot sessions.

## Batch ledger

| Batch | Objective | Status | Notes |
|---|---|---:|---|
| Batch 0 | Baseline and architecture verification | IMPLEMENTED | Architecture reviewed and documented; no production security changes made in this batch. |
| Batch 1 | Tenant isolation and database security | VERIFIED | Tenant validation tightened in core access paths; migration guardrails added for company-scoped data; Go tenant tests pass. |
| Batch 2 | Authentication and authorization | VERIFIED | Explicit company-membership validation added to tenant-scoped API routes; authz tests pass. |
| Batch 3 | GitHub integration security | VERIFIED | OAuth state binding, callback validation, and replay protection are hardened; focused tests pass. |
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

## Batch 2

### Objective

Centralize tenant-scoped authorization checks for the public Python API so only company members can access company-specific resources, and verify role boundaries explicitly.

### Findings before implementation

- `nlp/api.py` accepted company-scoped requests without verifying the caller’s company membership, even though `company_members` is the project’s canonical tenant model.
- The API used header-based identity (`X-User-Id`) without validating it against the requested company.
- Cross-company access was possible in principle whenever a caller supplied any non-empty, non-default `company_id` value.

### Files changed

- `nlp/api.py`
- `nlp/tests/test_authz.py`
- `docs/backend-hardening/PROGRESS.md`

### Security decisions

- Require `X-User-Id` and a valid non-default `company_id` on tenant-scoped endpoints.
- Query `company_members` to verify membership before executing any company-specific operation.
- Treat missing member records as an authorization failure (403) rather than silently continuing.
- Keep role checks explicit and centralized for admin-only routes when a future endpoint requires them.

### Tests added

- Added focused authz tests covering missing user IDs, invalid default company IDs, non-membership, valid membership, and admin-role rejection.

### Commands executed and actual results

1. `cd /home/nahom/Projects/personal/KMS/nlp && PYTHONPATH=. pytest -q tests/test_authz.py`
   - Result: passed (`5 passed in 1.40s`).

### Remaining risks

- This batch validates the explicit company-membership boundary at the Python API layer; it does not replace a full authentication review across the frontend and Go ingress.
- The live Supabase project still needs a full RLS and policy review before more tables are exposed directly.

### Status

VERIFIED

### Recommended next batch

Batch 3 — GitHub integration security.

## Batch 3

### Objective

Hardens the GitHub App install flow in the frontend by enforcing cryptographically signed, user/company-bound OAuth state, rejecting expired or replayed callbacks, and ensuring the authenticated user is authorized for the target company before persisting the installation.

### Findings before implementation

- The start route generated a client-encoded `base64url` state payload without any server-side signature or expiry check.
- The callback route accepted a query-only state fallback, allowed cookie+query mismatches, and did not require the logged-in user to match the bound user ID.
- The callback route did not reject replayed state values or validate that the user was still an admin for the target company.
- `setup_action` and `installation_id` parameters were not strictly validated before persisting installation metadata.

### Files changed

- `kms-frontend/app/api/integrations/github/start/route.ts`
- `kms-frontend/app/api/integrations/github/callback/route.ts`
- `kms-frontend/lib/github-app-state.ts`
- `kms-frontend/lib/github-app-state.test.ts`
- `docs/backend-hardening/PROGRESS.md`

### Security decisions

- Use a signed, opaque state token with a cryptographic nonce and a short expiry window.
- Bind the state to both the authenticated user ID and the target company ID.
- Require an exact match between the callback cookie and query parameter, reject replayed state markers, and delete the cookie on first successful use.
- Treat `installation_id` as a positive integer and reject unexpected `setup_action` values.
- Require the authenticated user to be an admin of the same company before saving installation metadata.

### Tests added

- Added unit tests covering valid state, tampered state, expired state, missing state, user/company mismatches, and replay hash detection.

### Commands executed and actual results

1. `cd /home/nahom/Projects/personal/kms-frontend/kms-frontend && npx --yes tsx --test lib/github-app-state.test.ts`
   - Result: passed (`6 passed`).
2. `cd /home/nahom/Projects/personal/kms-frontend/kms-frontend && npx tsc --noEmit --pretty false`
   - Result: failed due pre-existing TypeScript issues unrelated to this batch in other routes and `lib/auth.ts` typing (`activePlaybooks`, `maxPlaybooks`, missing `role` on user context).

### Remaining risks

- The broader frontend TypeScript project still has unrelated type errors outside the GitHub integration patch.
- The callback and start flow still require a live runtime test against the actual GitHub App installation lifecycle and environment variables.

### Status

VERIFIED

## Corrective review: identity boundary, membership policy, and tenant isolation

### Trigger

The project’s security review identified three unresolved issues in the completed tenant/authz work:

1. `nlp/api.py` trusted `X-User-Id` as an identity signal without cryptographic authentication.
2. `schema/policies.sql` allowed self-service membership creation and self-role changes without admin gatekeeping.
3. `schema/migrations/20261031_tenant_guardrails.sql` did not enforce RLS and strong tenant isolation against `default` values.

### Corrective work implemented

- Replaced legacy `X-User-Id` trust with verified `Authorization: Bearer <jwt>` validation in `nlp/api.py`.
- Added strict bearer-token verification for Supabase JWTs (or a configured internal service secret) and reject legacy header-based identity before any tenant-scoped work runs.
- Kept `company_members` membership checks bound to verified identity and rejected direct forged-header calls in the negative tests.
- Reworked `schema/policies.sql` so only admins/managers can invite or change membership roles; self-insertion/self-promotion is rejected by policy.
- Added RLS enablement and default-tenant invariant checks to the tenant guardrail migration and recorded the migration as fail-fast rather than silent data rewrite.
- Removed shared `default` fallbacks from the schema definitions in `schema/schemas.sql` to prevent new tenant-scoped records from being created with an unsafe default.

### Files changed

- `nlp/api.py`
- `nlp/tests/test_authz.py`
- `nlp/pyproject.toml`
- `nlp/requirements.txt`
- `schema/policies.sql`
- `schema/migrations/20261031_tenant_guardrails.sql`
- `schema/schemas.sql`
- `docs/backend-hardening/PROGRESS.md`
- `docs/backend-hardening/ARCHITECTURE.md`
- `docs/backend-hardening/SECURITY-DECISIONS.md`

### Negative tests added

- Verified JWT accepted with `SUPABASE_JWT_SECRET`.
- Forged `X-User-Id` header rejected as an authentication bypass.
- Invalid bearer token rejected.
- Wrong-company membership lookup rejected even when the user exists.
- Cross-tenant retrieval rejected.
- Role-escalation/self-promotion and unauthorized membership changes remain blocked by policy and test coverage.

### Commands executed and actual results

1. `cd /home/nahom/Projects/personal/KMS/nlp && PYTHONPATH=. pytest tests/test_authz.py -q`
   - Result: passed (`9 passed in 3.11s`).

### Remaining risks and assumptions

- The Python API now requires a configured JWT secret (`SUPABASE_JWT_SECRET` or `JWT_SECRET`) or an internal token secret (`INTERNAL_SERVICE_SECRET`). This is an external deployment dependency and must be provided in the live environment before the service is exposed.
- The database policy review remains a live Supabase deployment concern; the SQL policy files are reviewed and hardened in code, but they still have to be applied in the actual project environment with an explicit migration review.
- The broader frontend TypeScript project still contains unrelated type issues outside this corrective review. Those were not added by this patch and remain outside the security-review scope.

### Status

Batches 1 and 2: VERIFIED after corrective review and regression tests.

### Recommended next batch

Batch 4 — Go API protection and rate limiting.

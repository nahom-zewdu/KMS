# Backend Hardening Progress

This file is the source of truth for the hardening program and survives Copilot sessions.

## Batch ledger

| Batch | Objective | Status | Notes |
|---|---|---:|---|
| Batch 0 | Baseline and architecture verification | IMPLEMENTED | Architecture reviewed and documented; no production security changes made in this batch. |
| Batch 1 | Tenant isolation and database security | IMPLEMENTED | Tenant guards and RLS policies are implemented and pass disposable PostgreSQL tests; live Supabase inventory/data preflight is BLOCKED. |
| Batch 2 | Authentication and authorization | IMPLEMENTED | JWT identity and membership boundaries are implemented and locally tested; production signer configuration and invitation-flow verification remain BLOCKED. |
| Batch 3 | GitHub integration security | VERIFIED | OAuth state binding, callback validation, and replay protection are hardened; focused tests pass. |
| Batch 4 | Go API protection and rate limiting | BLOCKED | Go authentication/webhook controls are implemented and tested by the corrective review; rate limiting remains explicitly not started. |
| Batch 5 | Go HTTP server hardening | VERIFIED | Explicit server timeouts, header bound, graceful shutdown, and Redis close handling are implemented and tested; live deployment remains unverified. |
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

### Historical status

VERIFIED when Batch 1 was first completed; superseded by the corrective review below.

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

### Historical status

VERIFIED when Batch 2 was first completed; superseded by the corrective review below.

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

This section preserves the earlier corrective-review record. Its status and implementation summaries are historical and are superseded by the final corrective review follow-up below.

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

### Historical recommended next batch

Batch 4 — Go API protection and rate limiting. This recommendation was superseded by the corrective follow-up below; Batch 4 remains blocked.

## Corrective review follow-up — 2026-10-31

This section supersedes the earlier corrective-review status above. The earlier Batch 1/2 `VERIFIED` labels were too broad because they did not include database policy execution, verified JWT claims, or complete tenant retrieval checks.

### Current status

- Batch 1: **IMPLEMENTED**. Guardrails and RLS policies are **VERIFIED** against a disposable PostgreSQL 16 database; live Supabase inventory and production data preflight are **BLOCKED**.
- Batch 2: **IMPLEMENTED**. JWT and membership behavior are **VERIFIED** by focused Python tests and disposable PostgreSQL policy tests. Production signing-key compatibility and invitation-flow verification are **BLOCKED**.
- `ACCEPTED`: no unresolved security risk is marked accepted.
- Batch 4: **BLOCKED**. Do not start rate limiting until blockers below are resolved or explicitly accepted.

### Inventory and isolation policy

The checked-in schema declares no views or materialized views. The current table and function inventory is documented in `docs/backend-hardening/ARCHITECTURE.md`. In summary:

- Authenticated members read only their company rows in companies, memberships, repositories, codebase files/modules (through their parent repository), entity/edge graph, raw knowledge, playbooks, Ramp plans, and own Ramp progress.
- Company admins manage company repository metadata, playbooks, Ramp plans, and membership roles. Managers may add member-role memberships, but cannot change roles.
- `company_integrations` and unscoped legacy/audit tables (`events`, `contributions`, `pull_requests`, `issues`, `query_logs`) are service-only; authenticated and anon grants are revoked.
- Workers and backend services use `service_role`, which bypasses RLS. Their reads and updates must therefore include explicit company filters; checked-in query/retrieval, Ramp, codebase, baseline, and backfill paths now carry those filters.
- `match_documents` and `search_edges_by_entity` require a real company filter. The graph RPC and its removal of the historical global overload were exercised in PostgreSQL. The vector RPC was not executable locally because the test database did not have pgvector.
- Membership policies call `public.is_company_member`, a fixed-search-path `SECURITY DEFINER` predicate, to avoid recursive RLS evaluation. Company and initial owner membership creation is one transactional authenticated RPC.

### Migration safety and existing data

- Guardrail and policy migrations are idempotent and were each run twice in the disposable database.
- Migrations do not delete or silently remap rows. Existing `default`, blank, orphaned, or cross-company graph data causes an explicit error and transaction rollback.
- The checked-in base schema previously omitted `raw_data.company_id`; the migration adds the column, then fails if any historical raw-data row is unmapped. Production operators must review and explicitly map existing data before retrying.
- No migration was applied to live Supabase.

### Tests and actual results

1. `cd /home/nahom/Projects/personal/KMS/nlp && PYTHONPATH=. pytest tests/test_authz.py tests/test_ramp_v2.py tests/test_evidence_composition.py tests/test_query_engine_context.py -q`
   - Passed: `35 passed`; third-party deprecation warnings only.
2. `cd /home/nahom/Projects/personal/KMS && psql 'postgresql://postgres@127.0.0.1:55432/postgres' -f schema/tests/tenant_rls.sql`
   - Passed on disposable PostgreSQL 16 with a mock `auth.uid()` implementation. Tested RLS visibility, membership policy recursion, owner creation, self-insertion/self-promotion, unauthorized cross-company role change, tenant reads/writes, graph RPC filtering, and service-role access.
3. Migration fail-safe probe with an existing `companies.id = 'default'`.
   - Expected failure observed; the default row remained and transaction changes were rolled back.

### Blockers and deployment assumptions

- **BLOCKED — live Supabase:** live objects, grants, existing policy inventory, and tenant data were not queried or modified.
- **BLOCKED — JWT signing compatibility:** Python currently permits HS256 only. Before deployment, confirm Supabase issues HS256 tokens and configure `SUPABASE_JWT_SECRET`, matching issuer, and audience. Asymmetric/JWKS signing is not implemented.
- **BLOCKED — raw-data tenant mapping:** if existing rows lack a verified company mapping, an operator-reviewed backfill is required before the guardrail migration can pass.
- **BLOCKED — pgvector test:** `match_documents` was not executed in the disposable database because pgvector was unavailable. The SQL and application filters are present but this RPC remains unverified at runtime.
- **BLOCKED — invitation lifecycle:** the repository has no persisted invitation table or complete invite-acceptance flow; the existing invite endpoint remains a placeholder. Database policies restrict direct membership additions and role changes, but the end-to-end invite token lifecycle is not verified.
- The `service_role` bypass is intentional; service code must preserve the explicit company filters described above. Unknown live objects are outside the checked-in inventory and must be reconciled before rollout.

### Next batch

Batch 4 — **BLOCKED**. Do not begin rate limiting until the deployment/data/signing/invitation blockers are resolved or explicitly accepted.

## Corrective review — Go ingress boundary — 2026-11-01

Rate limiting remains **not started**. This corrective work closes the Go user-route authentication and tenant authorization gaps, hardens webhook processing, and implements the HTTP server lifecycle controls; it does not mark the overall rate-limiting batch complete.

### Current status

- Go user-triggered route protection: **IMPLEMENTED**, focused tests **VERIFIED**.
- Webhook bounds/signature/timestamp and synchronous handler lifecycle: **IMPLEMENTED**, focused tests **VERIFIED**.
- HTTP server limits and bounded graceful shutdown: **IMPLEMENTED**, focused tests **VERIFIED**.
- Rate limiting: **BLOCKED / NOT STARTED**.
- Production security: not claimed. Supabase/Auth availability, deployed route exposure, webhook delivery behavior, and production runtime settings were not exercised.
- No live Supabase project was contacted or changed.

### Routes and controls

- `GET /health`: public health check.
- `POST /slack/events` and trailing-slash alias: Slack-signed webhook; limited body; timestamp must be within five minutes in either direction; signature uses constant-time comparison.
- `POST /github` and trailing-slash alias: GitHub HMAC-signed webhook; limited body; delivery ID must parse as UUID; existing event delivery ID uniqueness and idempotency check prevent repeat processing.
- `POST /query`: requires Supabase-verified bearer token and exact `company_members` match before subscribing/publishing; rejects missing/default company; carries the authorized company ID in both job and payload.
- `GET /github/sync-baseline`: requires the same token/membership check; resolves repository by exact repository ID or full name scoped by the authorized company; publishes only the canonical repository full name and company context.
- No other internal HTTP service routes are registered. Redis streams are internal worker boundaries, not public routes.

### Files changed

- Go API: `api/domain/domain.go`, `api/domain/github.go`, `api/domain/slack.go`, `api/handlers/auth.go`, `api/handlers/codebase.go`, `api/handlers/github.go`, `api/handlers/query.go`, `api/handlers/routes.go`, `api/handlers/slack.go`, `api/handlers/webhook_body.go`, `api/main.go`, `api/repository/supabase.go`, `api/services/codebase.go`, `api/services/slack_bot.go`, `api/services/slack_verifier.go`.
- Go tests: `api/handlers/security_test.go`, `api/handlers/tenant_test.go`, `api/main_test.go`, `api/repository/supabase_auth_test.go`, `api/services/codebase_test.go`, `api/services/core_test.go`, `api/services/slack_verifier_test.go`.
- Frontend proxy: `kms-frontend/app/api/query/route.ts` now forwards the authenticated Supabase session token to Go and fails closed if it is absent.
- Documentation: this file plus `ARCHITECTURE.md`, `SECURITY-DECISIONS.md`, and `TEST-MATRIX.md`.

### Security behavior and limitations

- Go validates bearer access tokens through Supabase Auth’s `/auth/v1/user`; user identity does not come from a caller-supplied ID or locally decoded unverified claims. Membership and repository checks use exact Supabase filters.
- Auth service/network errors fail closed with 503; invalid/expired tokens return 401; missing membership and cross-company repository access are rejected.
- Webhooks now process synchronously and respond only after processing returns. Slack AuthTest/API operations and Redis/query work receive request-bounded contexts; Slack event handling can wait up to 60 seconds for mentions and 30 seconds for ordinary messages. Failures are reported with 5xx to allow provider retry. This changes acknowledgement latency versus the prior fire-and-forget goroutines.
- GitHub duplicates are acknowledged after the existing delivery-ID check finds the stored row. The schema declares `events.delivery_id` unique; no live schema was inspected.
- HTTP server configuration: ReadHeaderTimeout 5s, ReadTimeout 30s, WriteTimeout 90s, IdleTimeout 120s, MaxHeaderBytes 1 MiB, graceful shutdown bounded to 15s. Redis is closed during process cleanup.
- External Supabase Auth availability is now required for protected Go requests. No offline JWT verification fallback was added.

### Commands executed and actual results

1. `gofmt -w api && cd api && go test ./... && go test -race ./...`
   - Passed: main, handlers, repository, and services packages; domain has no tests. Race detector passed for all packages.
2. `cd api && go vet ./...`
   - Passed with no diagnostics.
3. `cd /home/nahom/Projects/personal/kms-frontend/kms-frontend && npx tsc --noEmit --pretty false`
   - Passed with exit code 0.
4. `git diff --check && git -C /home/nahom/Projects/personal/kms-frontend/kms-frontend diff --check`
   - Passed.

### Remaining risks and recommended next work

- **BLOCKED — production verification:** no deployed Go API or live Supabase/Auth configuration was queried. Confirm API exposure, service key validity for `/auth/v1/user`, and production timeout behavior before claiming production security.
- **BLOCKED — end-to-end webhook verification:** tests use signed local requests and strict fakes; no real Slack/GitHub delivery or retry lifecycle was exercised.
- **BLOCKED — migration/schema parity:** repository ownership and delivery uniqueness rely on checked-in schema. Live table constraints/grants were not verified.
- The new synchronous webhook processing may increase response latency; monitor provider retry timing and adjust only with measured evidence. If asynchronous handling is later restored, use a durable queue and never retain Gin request state.
- Rate limiting remains **not started**. Do not begin until the Go ingress corrective review is accepted and production dependencies/assumptions are resolved.

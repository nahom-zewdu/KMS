# Security Decisions

## Decision 1: no shared default tenant in production

The architecture explicitly says that no production event should be assigned to a shared `default` company. This rule is consistent with the tenant model and should remain non-negotiable.

### Evidence

- `docs/architecture/tenancy.md` states: “No production event should be assigned to a shared `default` company.”
- `api/handlers/tenant.go` treats `default` as an unresolved or invalid company value via `isResolvedCompany` and `isUnresolvedCompany`.

### Consequence

The public API layer should not silently default a missing company to `"default"`; it should reject the request or require an authenticated, validated tenant context.

## Decision 2: provider signatures remain the ingress guardrail

Slack and GitHub webhook handlers verify request signatures before processing.

### Evidence

- `api/handlers/slack.go` verifies `X-Slack-Signature` and `X-Slack-Request-Timestamp`.
- `api/handlers/github.go` verifies `X-Hub-Signature-256`.

### Consequence

This is a necessary primitive, but it is not a complete tenant authorization model. Signature verification alone does not prove that the request belongs to a valid tenant or company.

## Decision 3: tenant resolution must come from integration metadata, not client input

The code resolves company identity by provider team ID / installation ownership and then checks for conflicts.

### Evidence

- `resolveSlackTenant` resolves the company from the Slack `team_id`.
- `resolveGitHubTenant` prefers installation identity and falls back to owner login only under explicit conditions.
- Conflicting company mappings are rejected as a `tenant conflict`.

### Consequence

A client-supplied `company_id` or query parameter should never be treated as proof of authorization. The next security batch should enforce this across public API routes.

## Decision 4: keep background workers and ingestion paths internal

Redis streams and worker consumers are internal trust boundaries.

### Evidence

- `nlp/worker/ingestion.py` publishes jobs to `codebase_analysis_jobs`.
- `nlp/worker/codebase_analysis.py` expects a verified `company_id` and rejects empty/default values.

### Consequence

This pattern is stronger than a direct daemon thread, but it still requires explicit worker validation and tenant enforcement in any user-triggered route that reaches the same code path.

## Decision 5: user identity must come from a verified token, never from a client header

The project’s earlier API patterns trusted `X-User-Id` as a user identity. That is not valid authentication.

### Evidence

- `nlp/api.py` previously read `X-User-Id` and used it as a trusted identity signal.
- The frontend called the Python API using `X-User-Id` derived from the authenticated user context rather than a verified bearer token.

### Consequence

All company-scoped Python routes now require a verified `Authorization: Bearer <jwt>` token. Legacy `X-User-Id` headers are rejected. A direct API caller without a valid token cannot satisfy the identity boundary.

## Decision 6: staff can only manage memberships through admin-controlled flows

Membership and role changes must be limited to authorized administrators, not to arbitrary users updating their own rows.

### Evidence

- `schema/policies.sql` used policies that allowed `auth.uid() = user_id` inserts and updates for `company_members`.
- This allowed self-service membership and role promotion in the same tenant row.

### Consequence

Membership creation, role changes, and deletions are restricted to administrators/managers for the target company. Self-insertion and self-promotion are explicitly rejected.

## Decision 7: do not claim production hardening before validation

The project's own guidance explicitly warns against claiming guarantees without evidence.

### Consequence

The corrective review now records the relevant negative tests, deployment secret requirements, and remaining live-environment verification tasks. We do not claim final production hardening until the live Supabase policy set is applied and reviewed in context.

## Decision 8: user JWTs and internal service tokens are separate credentials

### Decision

User-facing Python API routes accept only Supabase user JWTs. Verification is HS256-only and requires `exp`, `iat`, `iss`, `aud`, `sub`, and `role`; issuer and audience are checked, and `role` must be `authenticated`. Legacy `X-User-Id` is rejected. An independently configured service-token validator is not an alternate identity source for user routes.

### Deployment assumptions

- Configure `SUPABASE_JWT_SECRET` with at least 32 bytes.
- Configure `SUPABASE_JWT_ISSUER` or provide `SUPABASE_URL`, from which `/auth/v1` is appended.
- Configure `SUPABASE_JWT_AUDIENCE` if it differs from `authenticated`.
- The live Supabase signing algorithm has not been verified. Asymmetric/JWKS tokens are unsupported until a separate verifier is implemented.

## Decision 9: membership authorization is non-recursive and admin-controlled

### Decision

`company_members` RLS calls `public.is_company_member`, a narrowly scoped `SECURITY DEFINER` predicate with fixed `search_path`, rather than querying its own RLS-protected table in policy expressions. Users cannot insert themselves or alter their own role. Managers may add a member-only row; only admins may change another non-owner membership role. Owners cannot be modified or removed through ordinary membership policies.

Company creation and first owner membership are created atomically by `public.create_company_with_owner`, and the frontend creation route uses that RPC. There is no implemented invitation persistence/acceptance lifecycle or owner-transfer RPC; those product flows remain explicitly blocked rather than treated as secure.

## Decision 10: authenticated reads are RLS-scoped; service-role writes require explicit tenant filters

### Decision

RLS is enabled for checked-in tenant tables. Authenticated access is limited to company membership, and graph edges are constrained to endpoints in the same company. Codebase files/modules inherit tenant scope through their repository. Tables containing provider credentials and legacy unscoped event/analytics records are service-only.

The Supabase `service_role` bypasses RLS by design. Backend and worker paths must include an explicit `company_id` filter for reads and updates; RLS is not claimed as a substitute for this application boundary. `match_documents` and `search_edges_by_entity` reject missing, blank, or `default` tenant filters.

## Decision 11: tenant migrations fail closed on unmapped historical data

### Decision

Guardrail migrations do not infer company ownership, delete data, or silently backfill. They preflight blank/default/orphaned/cross-company rows, add constraints idempotently, and abort transactionally when existing rows need operator review. `raw_data.company_id` is now part of the checked-in base schema; existing raw records without a verified mapping must be backfilled explicitly before deployment.

### Verification boundary

The policies and migration behavior passed against disposable PostgreSQL 16 using a minimal Supabase `auth.uid()` compatibility stub. This does not verify the live Supabase object inventory, production grants, signing configuration, or pgvector RPC runtime. No changes were applied to live Supabase.

## Decision 12: Go user routes validate Supabase access tokens and membership

### Decision

`POST /query` and `GET /github/sync-baseline` require a bearer access token that is validated against Supabase Auth `/auth/v1/user`. Go derives the user ID from that verified response, not from caller-provided identity claims or headers. Each request must separately prove membership in the exact requested company using the backend Supabase query filtered by both `user_id` and `company_id`.

The requested company ID is a selector only. Empty and `default` values are rejected. Baseline sync additionally resolves the repository by its ID or exact full name while filtering by the authorized company; the service queues only the canonical stored name and authorized company ID. Query and baseline Redis jobs carry company context explicitly.

### Consequences

- Invalid user credentials return 401, missing membership/repository authorization returns 403, and Supabase Auth/membership service failures fail closed.
- Go API availability for protected user routes depends on Supabase Auth availability. No second JWT key or offline token verifier was introduced.
- The frontend query proxy forwards its server-verified Supabase session access token to Go and fails closed if no token is present.

## Decision 13: webhook bodies are bounded and handlers own response lifetime

Slack and GitHub webhook bodies are limited to 1 MiB before parsing. Slack timestamps must be within five minutes in the past or future, and signature comparisons use constant-time HMAC comparison. GitHub delivery headers must parse as UUIDs; the ingestion service checks stored delivery IDs and the schema declares the delivery column unique.

Slack event processing now completes synchronously within the handler's request lifetime. It retries transient processing failures and returns an error response after exhaustion; no goroutine may access Gin context or write a response after handler return. This increases acknowledgement latency but avoids silently acknowledging failed work. Durable asynchronous delivery remains a possible later design, not an implicit behavior.

## Decision 14: Go HTTP server shutdown and resource lifecycle are bounded

The API uses `http.Server` with 5s `ReadHeaderTimeout`, 30s `ReadTimeout`, 90s `WriteTimeout`, 120s `IdleTimeout`, and 1 MiB `MaxHeaderBytes`. SIGINT/SIGTERM initiates graceful shutdown bounded to 15 seconds, after which the server is force-closed and the failure surfaced. Redis is closed when the run loop exits.

### Verification boundary

Go handler/repository/service and server tests, plus the race detector, passed locally. The frontend TypeScript check passed. No live Supabase or production webhook/runtime was exercised; the exact deployed grants, repository rows, delivery constraint, API routing, key configuration, and termination window remain deployment checks. Rate limiting is explicitly not part of this change.

## Decision 15: service-role access must be explicitly tenant-scoped

The Go and Python service-role call sites were inventoried. Tenant data is filtered in database queries or by repository IDs first resolved with a company predicate; Python query/Ramp paths and graph/vector RPC calls carry verified company context. The Go graph-search helper now requires a real company ID. Contribution metrics now require a company ID and repository for reads, include company scope in writes, and use a tenant-specific upsert conflict key.

The contributions migration maps existing rows only where `repo_name` resolves to one company. It aborts transactionally for orphaned, ambiguous, default-company, or inconsistent rows and does not delete data. The migration and RLS harness passed against a disposable PostgreSQL 16 instance.

Global access is limited to declared operational/analytics cases: integration identity resolution (provider plus globally unique external identity), event idempotency (globally unique delivery ID), maintenance enumeration of company IDs before per-company backfill, and minimized query-hash analytics. `pull_requests` and `issues` have no active retrieval/write callers and remain backend-only legacy tables without company ownership; they must not be used for tenant-facing retrieval.

### Verification boundary

Application tests assert company filters in actual PostgREST request parameters, and worker query-builder tests assert repository updates include the tenant predicate. The Python focused suite passed. However, the checked-in base schema lacks `events.company_id` even though Go writes it; deployed schema parity must be verified before rollout. The pgvector `match_documents` function was inspected but not runtime-tested because the disposable database lacked pgvector. Live Supabase grants, actual service-role key configuration, and deployed object inventory were not queried. Therefore service-role isolation is **IMPLEMENTED**, locally **PARTIALLY VERIFIED**, and overall deployment verification remains **BLOCKED**.

## Decision 16: rate limiting remains a design only

Prepared controls use shared Redis atomic windows for per-user and per-company query limits, per-user/per-company baseline-sync limits, and per-integration webhook controls. Redis leases bound concurrent expensive work across replicas. Limit exhaustion should produce 429 with `Retry-After` and reset/remaining metadata; Redis failure should fail closed with retryable 503 responses rather than bypass limits. Webhook 429 retry semantics require provider-specific validation before implementation.

The proposed starting limits and failure behavior are documented in `ARCHITECTURE.md`. They are not yet product-approved or implemented. Rate limiting remains **NOT STARTED** until the prior isolation/reliability blockers are accepted or resolved.

## Decision 17: events are tenant-associated; delivery IDs remain globally unique

Raw provider event payloads contain company data and are not global data. New `events` rows therefore require a real `company_id` referencing `companies`; the company key is also part of the checked-in base schema. The globally unique delivery-ID behavior remains unchanged because provider delivery IDs are the idempotency key independent of tenant.

The versioned migration only infers historical ownership from linked `raw_data` when exactly one valid company is present. It aborts transactionally for unmapped, conflicting, default, orphaned, or duplicate delivery-ID data. An operator must explicitly map unresolved historical events before retrying. Migration tests exist but were **BLOCKED** in this session because no disposable PostgreSQL server was available. No live Supabase database was contacted or changed.

## Decision 18: Slack playbook generation uses a company-bound service identity

Slack tenant resolution in Go is the authority for the company context. The Go playbook client requires that resolved company ID, sends it in the request, and signs a one-minute HS256 internal service token with the same `company_id` claim. The dedicated Python internal endpoint accepts only the configured internal issuer/audience/secret, requires standard time and identity claims, verifies service role and exact request-company equality, then calls the existing generator with that tenant. The user-facing endpoint remains user-JWT and membership protected; internal tokens do not authenticate users.

This avoids treating network location or a caller-provided company ID as authentication. Deployment still requires matching `INTERNAL_SERVICE_SECRET`, `INTERNAL_SERVICE_ISSUER`, and `INTERNAL_SERVICE_AUDIENCE` values in Go and Python. Their live configuration and the deployed API network boundary were not verified.

CoreIngest Redis publishing inherits the request context with a ten-second upper bound. Cancellation is part of the synchronous ingest contract; publishing is not detached after caller cancellation. There is a known recovery gap: cancellation after the database inserts but before Redis publish leaves persisted rows without a job, and a duplicate delivery currently skips rather than republishes. Durable outbox/reconciliation behavior is not implemented and must be addressed before claiming reliable recovery. Slack callback delivery identity is the provider `event_id`, not the message timestamp; missing IDs are rejected, and the database keeps a global unique delivery key.

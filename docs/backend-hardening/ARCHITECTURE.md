# Backend Architecture Verification

## System boundary

The current codebase confirms a two-runtime architecture:

- Go ingress: `api/`
- Python worker and services: `nlp/`

The application stores tenant-scoped state in Supabase/Postgres and move asynchronous work through Redis streams.

## Runtime map

### Go API (`api/`)

- `api/main.go` loads environment variables, initializes the Supabase client, initializes the Redis client, and starts `gin` routes.
- `api/handlers/routes.go` wires the route table:
  - `POST /slack/events`
  - `POST /github`
  - `GET /github/sync-baseline`
  - `POST /query`
  - `GET /health`
- `api/handlers/slack.go` verifies the Slack signature, resolves the team tenant, and then handles app mentions or message events.
- `api/handlers/github.go` verifies the GitHub webhook signature, parses supported events, and enriches payload content before inserting it into the event pipeline.
- `api/handlers/tenant.go` resolves `company_id` from Slack team IDs and GitHub installation/owner mappings, rejecting unresolved or conflicting mappings.

### Python worker (`nlp/`)

- `nlp/main.py` starts the worker process and handles SIGINT/SIGTERM gracefully.
- `nlp/worker/ingestion.py` is responsible for ingesting Slack/GitHub data, extracting entities/relations, inserting raw data, and publishing durable codebase-analysis jobs to Redis when a GitHub push event occurs.
- `nlp/worker/baseline.py` handles baseline synchronization for a repository and rejects missing `company_id` or repo entries.
- `nlp/worker/codebase_analysis.py` handles durable codebase analysis jobs from Redis and raises if `company_id` is missing or analysis returns failure.
- `nlp/api.py` exposes a FastAPI surface for Ramp generation, playbook generation, visualizer endpoints, and repository baseline sync.

## Company/tenant resolution flow

The architecture intends the following operating model:

1. Webhook arrives from Slack or GitHub.
2. The ingress verifies the provider signature.
3. The ingress resolves a company from integration metadata, using installation mapping when possible.
4. The resolved `company_id` is attached to the ingest request and propagation chain.
5. The worker writes tenant-scoped knowledge data and queries only company-scoped records.

This is implemented in the current code path and is consistent with the tenancy model defined in `docs/architecture/tenancy.md`.

## Corrective tenant-object inventory

The inventory below is derived from checked-in `schema/*.sql`, migrations, and NLP/frontend access paths. No views or materialized views are declared in those SQL files. The live Supabase catalog was not queried, so production-only objects remain unknown.

| Object | Tenant scope | Intended caller | Isolation / write policy |
|---|---|---|---|
| `companies` | Company root | Authenticated member; trusted creation RPC | Members select only companies they belong to. Direct inserts are revoked; `create_company_with_owner` atomically creates the company and initial admin/owner membership. |
| `company_members` | `company_id`, `user_id`, `role` | Authenticated user and company admins/managers | Own membership or admin/manager company roster reads; self-insert and self-role updates denied; manager may add member role; admin manages other non-owner roles/members. Policies use `is_company_member` SECURITY DEFINER helper to avoid recursive RLS. |
| `company_integrations` | `company_id` | Trusted frontend/server integrations | Service-only because rows contain access tokens and webhook secrets; no authenticated table grant/policy. User-facing server routes must authorize an admin before using privileged access. |
| `company_repos` | `company_id` | Authenticated members/admins | Members read; company admins write. |
| `repositories` | `company_id` | Authenticated members; workers write | Members read their companies; worker writes are service-role only. |
| `codebase_files`, `codebase_modules` | Inherited from `repository_id` | Authenticated members; workers write | RLS resolves the parent repository and checks its company. Application fetches first resolve repository IDs for the company and filter by those IDs. |
| `file_entity_links` | Inherited from file/repository and entity | Authenticated members; workers write | RLS requires linked file and entity to resolve to the same member company; writes are service-role only. |
| `entities` | `company_id` | Authenticated members; workers write | Member-only reads; service-role writes. |
| `edges` | `company_id` and both endpoint companies | Authenticated members; workers write | Member reads require source and target entities to share edge company. Composite foreign keys enforce same-company endpoints; service-role writes carry explicit company filters. |
| `raw_data` | `company_id` | Authenticated members; workers write | Member-only reads; service-role writes; vector/keyword retrieval includes a mandatory company filter. Historical rows without a verified company mapping block migration. |
| `playbooks` | `company_id` | Authenticated members/admins; backend generator | Members read; admins write through direct authenticated access. Python generation uses service role after verified user/company membership. |
| `ramp_plans` | `company_id` | Authenticated members/admins; backend generator | Members read; admins write; API and store query by explicit company ID. |
| `ramp_step_progress` | `company_id`, `user_id` | Authenticated member; backend API | Member reads/writes own progress; admins may access company progress; application query filters plan, company, and user. |
| `events` | Globally unique delivery ID; Go associates rows with a company, but checked-in base schema has no `company_id` column | Trusted Go/NLP services | Backend-only idempotency and event processing; no authenticated grants/policies. Schema parity is **BLOCKED** until reconciled with the deployed database. |
| `contributions` | `company_id`, repository, contributor | Trusted Go metrics service | Service-only; the metrics service requires company and repository filters for reads and uses a tenant-specific conflict target. `20261101_contributions_tenant_scope.sql` maps historical rows only when repository ownership is unique; ambiguous/orphaned rows abort. |
| `pull_requests`, `issues` | No company column in checked-in schema; legacy repository-keyed rows | No active Go/Python query or write caller found; trusted backend only | RLS enabled, no authenticated policy/grant. The generic Go writer no longer accepts these unscoped tables. They must not be used for tenant retrieval until ownership is modeled. |
| `query_logs` | System-wide anonymized question hash and query telemetry; no company or plaintext question | Python analytics worker | Intentionally global, service-only analytics; this table is not a knowledge retrieval source. |
| `profiles` | User-owned, not the canonical tenant membership source | Authenticated user and trusted profile flows | Own-profile RLS; company membership and role must come from `company_members`, not profile columns. |

### Functions and RPCs

| Function/RPC | Caller | Tenant/security rule |
|---|---|---|
| `assert_real_company(text)` | RLS/check policies | Immutable validation helper; rejects null, blank, and `default`. |
| `is_company_member(text, text[])` | RLS policies | SECURITY DEFINER membership predicate; fixed `search_path`, no recursive policy evaluation. |
| `create_company_with_owner(text, text)` | Authenticated user | Requires `auth.uid()`, rejects `default`, atomically creates company and owner/admin membership. |
| `search_edges_by_entity(text, text[], text)` | Authenticated/service role | Requires `filter_company_id`; filters edge and both endpoint entity rows; historical unscoped overload is removed. |
| `match_documents(vector, float, int, text)` | Authenticated/service role | Requires `filter_company_id`; function rejects null/blank/default and SQL filters raw data by exact company. Runtime pgvector test remains blocked locally. |

RLS is enabled on the listed tenant tables and on the listed service-only tables (which have no authenticated policies). `service_role` explicitly has backend grants and bypasses RLS; application-level tenant filtering remains mandatory for every service-role retrieval path.

### Service-role access-path audit

The configured Python Supabase client is documented as using the service-role key. That credential selection is an environment/deployment assumption, not something established by local tests. The Go repository similarly uses its configured backend key for privileged operations.

| Backend path | Objects and operations | Tenant treatment / audit result |
|---|---|---|
| Go webhook ingestion (`CoreIngest`) | Global `events.delivery_id` idempotency lookup; insert event and `raw_data` | Delivery IDs are globally unique by schema and the lookup only returns whether one exists. Company context is included on writes, but `events.company_id` is missing from the checked-in base schema; deployment compatibility is **BLOCKED**. `raw_data` inserts carry company ID. |
| Go integration resolution | `company_integrations` lookup by provider + external ID or installation ID | Intentional global identity-to-company lookup; uniqueness constraints are expected to bind the integration identity to one company. Returned tenant context is then propagated to jobs. Live uniqueness/configuration is **BLOCKED**. |
| Go user authorization | `company_members` by exact user + company; `repositories` by exact company + requested repository | Database-level filters are applied before membership/repository authorization. |
| Go graph search | `raw_data` content search | Requires a real company ID and applies `company_id` in the PostgREST query. No current production caller was found; regression test asserts the actual request filter. |
| Go contribution metrics | `contributions` query/upsert | Requires and filters `company_id` plus `repo_name`; upsert key includes company. Historical ownership migration is implemented and exercised on disposable PostgreSQL. |
| Python query/RAG | `entities`, `edges`, `raw_data`; `search_edges_by_entity` and `match_documents` RPCs | Application query builders and SQL RPCs pass exact company IDs. Related entity reads also filter at the database. pgvector RPC runtime remains **BLOCKED** because the disposable database lacks pgvector. |
| Python Ramp/visualizer/playbooks | `repositories`, `codebase_files`, `codebase_modules`, `entities`, `edges`, `raw_data`, Ramp tables | Company is checked before retrieval; repository-derived records are fetched via company-filtered repository IDs, and direct tenant tables use `company_id`. Per-user Ramp progress also filters by `user_id`. |
| Python ingestion/codebase workers | `entities`, `edges`, `raw_data`, `repositories`, `codebase_files`, `codebase_modules`; edge lifecycle update | Worker jobs carry company context; writes include the company, reads use company or company-resolved repository IDs. Repository updates now include both row ID and company predicates. Worker ingress is trusted Redis, not an end-user identity boundary. |
| Embedding backfill | Global company enumeration; per-company `raw_data` fetch and embedding update | Global enumeration is intentional maintenance behavior. Every fetch selects one explicit company, rejects `default`, and updates only IDs selected for that company. |
| Query analytics | `query_logs` insert | Intentionally system-wide and content-minimized: a question hash and operational metrics only. Not used for answers or tenant retrieval. |
| Legacy `pull_requests` / `issues` | No active service-role retrieval/write call found | Backend-only by grants, but no company key exists in the checked-in schema. Not eligible for tenant retrieval until modeled and migrated. |

This is a code and disposable-database review, not proof of deployed service-role isolation. In particular, live grants/schema parity, the event table company-column mismatch, and pgvector RPC execution remain **BLOCKED**.

## Rate-limit design prepared — not implemented

- Use Redis-backed atomic fixed-window/token-bucket counters (Lua or equivalent) so limits are shared across API instances. Keys include the dimension and stable identifier; never key only on caller-provided tenant IDs.
- Initial tuning proposal: queries 20/user/minute and 100/company/minute; baseline sync 2/user/hour and 10/company/hour; provider webhooks use per-integration burst/window controls after signature and tenant resolution, with delivery-id deduplication still authoritative. These are starting caps, not approved production values.
- Bound expensive concurrency with Redis leases: at most 2 active queries/user, 10/company, and 1 baseline sync/company. Leases need expirations and safe release on cancellation.
- Limit exhaustion returns HTTP 429 with `Retry-After` plus rate-limit remaining/reset metadata. Redis failure is fail-closed for user queries and baseline syncs (503 with retry metadata), not an unmetered bypass. Signed webhooks return retryable 503 when shared controls are unavailable; do not silently drop events. Provider-specific 429 retry behavior must be validated before rollout.
- No counters, concurrency leases, middleware, or 429 behavior were implemented in this review.

## Route and trust-boundary summary

### Public health and provider-authenticated webhook paths

- `POST /slack/events`
- `POST /slack/events/` (compatibility alias)
- `POST /github`
- `POST /github/` (compatibility alias)
- `GET /health`

Health is public and does not return tenant data. Webhooks authenticate the provider signature before parsing or acting on payloads, resolve the tenant from integration metadata, and enforce a 1 MiB body limit. Slack uses HMAC-SHA256 with constant-time comparison and rejects timestamps more than five minutes in the past or future. GitHub uses constant-time HMAC comparison and requires a UUID delivery ID.

Webhook processing is synchronous: handlers do not retain Gin request state in goroutines or write a response after returning. Slack AuthTest/API operations and Redis/query work receive request-bounded contexts. Errors return non-success responses so providers can retry. GitHub delivery IDs are checked by the ingestion service and stored under the schema's unique delivery ID constraint.

### Authenticated user routes

| Route | Authorization | Tenant enforcement |
|---|---|---|
| `POST /query` | Supabase access token validated by Supabase Auth `/auth/v1/user` | Caller must be a member of the exact requested company. Missing/default company IDs are rejected; verified company ID is propagated to the Redis job and nested payload. Request body is limited to 1 MiB. |
| `GET /github/sync-baseline` | Same Supabase access-token validation | Caller must be a member of the exact requested company. Repository ID or full name must resolve from `repositories` with an exact company filter; only the stored canonical full name and verified company ID are queued. |

Supabase Auth failures fail closed. Invalid tokens return 401; missing membership or repository ownership returns 403; auth-service failures return 503. Membership checks use the backend Supabase client with both `user_id` and `company_id` filters. Client-supplied company IDs are treated only as selectors and never as authorization evidence.

### Internal HTTP routes

No separate internal service HTTP endpoints are registered. Internal work is dispatched through Redis streams to workers; worker messages must preserve explicit tenant context.

### Internal/worker paths

- Redis streams (`slack_jobs`, `github_jobs`, `query_jobs`, `codebase_analysis_jobs` etc.)
- Python ingestion and codebase analysis handlers

These should be treated as internal trust boundaries, not as user-triggered authorization surfaces.

## Go HTTP runtime controls

The Go API uses an explicitly configured `http.Server`: `ReadHeaderTimeout` 5 seconds, `ReadTimeout` 30 seconds, `WriteTimeout` 90 seconds, `IdleTimeout` 120 seconds, and `MaxHeaderBytes` 1 MiB. SIGINT/SIGTERM initiates graceful shutdown bounded to 15 seconds; timeout forces server close and returns an error. Redis is closed as `run` exits. These settings are covered by local tests but have not been verified against production load or deployment termination windows.

The Supabase Auth `/user` request is bounded by an 8-second request context and a 10-second HTTP client timeout. Membership and repository REST lookups use the request context and the same 10-second client bound. The deployed Go API therefore depends on Supabase Auth/PostgREST availability for each protected request; no local JWT-validation fallback exists.

### Python user API

- Ramp, playbook, visualizer, and baseline-sync routes require a verified Supabase user JWT and explicit company context, then verify the exact user/company membership with the service-role membership query.
- `X-User-Id` is rejected as identity. The frontend server passes the Supabase session access token as a bearer token.
- The service-role client bypasses RLS; this API-level membership check and explicit query scoping remain necessary.

## Corrective review of the identity and tenant boundary

### Identity boundary fix

The Python API is no longer allowed to trust `X-User-Id` as its own authentication primitive. The live request path must carry a verified bearer token and a validated company context.

- Frontend server routes authenticate through Supabase and pass the Supabase access token as `Authorization: Bearer <jwt>`.
- The Python API validates user tokens with HS256, required expiration/issued-at/issuer/audience/subject/role claims, configured issuer and audience, and the `authenticated` role. It rejects legacy header-based identity.
- Internal service tokens have a separate validator and are not accepted as user identity on any current user route.

### Membership and RLS correction

The database policy set now treats `company_members` as an admin-controlled membership table instead of a user-owned self-service table.

- Members may read their own association and authorized company data.
- Admins can manage other non-owner roles; admins/managers can add member-role rows.
- Self-insertion and self-promotion are rejected by policy.
- Tenant-scoped tables are protected by RLS and default-tenant invariant checks.
- Initial company ownership is established by a single transactional RPC; a persisted invitation/acceptance lifecycle and owner-transfer flow are not implemented.

### Production assumptions and deployment dependency

The live environment must set the identity secret, issuer, and audience before the Python API is exposed beyond trusted infrastructure. This implementation supports HS256 only; the deployed Supabase signing algorithm is an unresolved assumption. The guardrail migration aborts rather than assigning unmapped historical data. No live Supabase changes were made.

## Conclusion

The checked-in code now has a tested user identity boundary and tenant policy design. Disposable PostgreSQL policy verification passed, but live Supabase inventory/data compatibility and pgvector RPC execution remain blocked. RLS does not constrain `service_role`; service-role query filters remain part of the security boundary.

## Batch 6 — Ingestion outbox and worker recovery

### Ingress-to-worker lifecycle

```text
Slack/GitHub webhook
  -> provider verification and company resolution
  -> CoreIngest
  -> PostgreSQL transaction:
       events + raw_data + ingestion_outbox
  -> Go outbox dispatcher (leased SKIP LOCKED claims)
  -> Redis source stream (XADD)
  -> Python consumer group (XREADGROUP)
  -> per-message lease + heartbeat
  -> tenant validation + idempotent DB writes
  -> optional codebase_analysis_jobs XADD for GitHub push
  -> XACK after all handler work succeeds
```

Provider event payloads, summaries, and work records are tenant-owned. `events.delivery_id` remains globally unique for cross-provider duplicate detection. The persisted outbox has a composite foreign key to `(events.id, company_id, delivery_id)`, its own globally unique delivery ID, bounded error text, claim count, and terminal state. `persist_ingestion_with_outbox` rejects tenant or delivery mismatches and commits all three DB records atomically.

The Go dispatcher claims up to five jobs with a 180-second lease, which bounds sequential per-record Redis and PostgREST operations. It publishes to Redis with a 10-second context bound and marks published only after `XADD` succeeds. DB and Redis cannot share one transaction. If the process crashes after `XADD` but before the DB status update, the lease expires and the same job is published again. That is explicitly **at-least-once**, not exactly-once. Failed dispatches use capped exponential delay and become DB `dead_letter` after 12 claims.

Python starts newly created groups at `0-0` to avoid skipping existing entries. Existing groups are not rewound. `XREADGROUP` work enters the pending-entry list; a Redis `SET NX PX` lease is renewed by a heartbeat while the handler runs. Recovery inspects `XPENDING`, requires the delivery-dependent idle backoff to elapse, checks/acquires the lease, and then `XCLAIM`s. The idle threshold alone is not authorization to reclaim active work.

The consumer validates a non-empty, non-`default` tenant and record ID before dispatching to a handler. Ingestion verifies that the exact event delivery belongs to that company. Entities and edges use tenant-derived deterministic IDs; raw-data updates and processed markers include company predicates. The codebase-analysis handler independently checks the source event's company. Query/Ramp retrieval passes company context to its query engine; codebase baseline and incremental jobs use company-scoped repository queries and writes.

Successful handlers are acknowledged once by the consumer. Query handlers no longer acknowledge or delete stream entries. Failed deliveries remain pending and retry with capped exponential idle backoff; after five deliveries the consumer atomically writes a deduplicated dead-letter entry before acknowledging the source. It does not `XDEL` source entries.

### Failure windows and guarantees

| Failure point | Recovery behavior | Guarantee / limitation |
|---|---|---|
| Before DB transaction commits | Transaction rolls back; provider may retry | No outbox job is visible before commit |
| DB transaction commits, Redis is unavailable | Outbox remains retryable; API ingestion can still succeed | Durable DB-to-Redis recovery after commit |
| Redis accepts job, dispatcher crashes before DB mark | Outbox lease expires and republishes | At-least-once; consumer side effects must be idempotent |
| Worker crashes before DB side effects | Entry remains pending; lease eventually expires and recovery claims it | Bounded retry, then DLQ |
| Worker crashes after side effects but before `XACK` | Handler repeats; deterministic IDs and scoped upserts suppress duplicate records | At-least-once, not exactly-once |
| Worker loses Redis lease and then resumes | Consumer refuses to acknowledge after observed lease loss; a replacement may already be processing | Lease is not a fencing token; external side effects must remain idempotent |
| GitHub push's follow-up analysis `XADD` fails | Source ingestion event is not marked processed and retries | DB writes may repeat; follow-up stream has no independent DB outbox |
| DLQ `XADD` succeeds but source `XACK` fails | Deduplication marker prevents immediate duplicate DLQ entry | Marker retention is 90 days; operator replay is not automated |

### Deployment prerequisites and constraints

- Apply and verify `schema/migrations/20261101_ingestion_outbox.sql` before deploying Go code that calls the outbox RPCs. The migration rejects invalid existing event ownership and does not infer or delete historical records.
- Run `schema/tests/tenant_rls.sql` only against a disposable PostgreSQL/Supabase-compatible database. In this session no server was available; no migration or live project was touched.
- Inspect existing Redis consumer-group cursors and pending entries before deployment. `0-0` changes only newly created groups; existing groups keep their current cursor and can retain unconsumed historical entries.
- Monitor both the PostgreSQL outbox terminal state and each `<source>_dead_letter` stream. This batch does not add DLQ replay tools, automatic operator paging, or service dashboards.
- An active handler is allowed to finish before the consumer exits; shutdown does not forcibly cancel an unbounded NLP or database call. Runtime termination grace must exceed the longest accepted handler duration.
- A prior global entity ID scheme may have caused cross-company ownership collisions. Tenant-specific IDs prevent new collisions but do not repair or assign ownership to legacy entity rows.

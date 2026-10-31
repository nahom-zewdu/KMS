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
| `events` | No company column in checked-in schema; global ingress audit | Trusted Go/NLP services | RLS enabled, no anon/authenticated policy or grant; service role only. |
| `contributions`, `pull_requests`, `issues`, `query_logs` | No company column in checked-in schema | Trusted backend/analytics | Legacy unscoped tables; service-only and default-deny for authenticated/anon roles. |
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

## Route and trust-boundary summary

### Public/trusted ingress paths

- `POST /slack/events`
- `POST /github`
- `GET /health`

These routes verify provider signatures and resolve the tenant from integration metadata before ingesting events.

### Internal/worker paths

- Redis streams (`slack_jobs`, `github_jobs`, `query_jobs`, `codebase_analysis_jobs` etc.)
- Python ingestion and codebase analysis handlers

These should be treated as internal trust boundaries, not as user-triggered authorization surfaces.

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

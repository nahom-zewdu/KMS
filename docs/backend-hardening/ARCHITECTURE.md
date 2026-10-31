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

## Public risk observations

The current code is not yet uniformly hardened against default-tenant fallbacks:

- `nlp/api.py` sets `company_id` defaults to `"default"` in several public endpoints.
- This violates the project’s security guidance, which explicitly says there must be no shared/default production tenant.
- The current design treats `company_id` as a trust boundary; therefore, any default fallback on a public API path is a data exposure risk.

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

### Public API surface requiring stricter validation

- `nlp/api.py` routes such as Ramp, playbook generation, visualizer, and baseline sync currently accept `company_id` defaults and are not yet hardened against missing or spoofed tenant values.

## Corrective review of the identity and tenant boundary

### Identity boundary fix

The Python API is no longer allowed to trust `X-User-Id` as its own authentication primitive. The live request path must carry a verified bearer token and a validated company context.

- Frontend server routes authenticate through Supabase and pass the Supabase access token as `Authorization: Bearer <jwt>`.
- The Python API validates the bearer token against the configured project secret (`SUPABASE_JWT_SECRET` or `JWT_SECRET`) and rejects legacy header-based identity.
- Internal service tokens can use `INTERNAL_SERVICE_SECRET`, but they still must be signed and validated before any tenant-scoped membership check runs.

### Membership and RLS correction

The database policy set now treats `company_members` as an admin-controlled membership table instead of a user-owned self-service table.

- Members may read their own association and authorized company data.
- Admins/managers can invite members and manage role assignments.
- Self-insertion and self-promotion are rejected by policy.
- Tenant-scoped tables are protected by RLS and default-tenant invariant checks.

### Production assumptions and deployment dependency

The live environment must set the identity secrets before the Python API is exposed beyond trusted infrastructure. Without a configured JWT secret, the service intentionally fails safe instead of trusting client-provided identifiers.

## Conclusion

The architecture is coherent for a small layered system, and the company-scoped tenant boundary is now enforced at the API identity layer and at the database policy layer. There remain live-environment deployment checks for the exact Supabase RLS configuration, but the code path is aligned with the explicit no-default-tenant and no-legacy-header rules.

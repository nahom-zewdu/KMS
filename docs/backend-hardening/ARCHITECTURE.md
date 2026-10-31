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

## Conclusion

The architecture is coherent for a small layered system, but the tenant enforcement model is not uniformly enforced across all public endpoints. The codebase is operationally understandable, but the production security posture still needs explicit tenant validation and policy enforcement in the user-facing API layer.

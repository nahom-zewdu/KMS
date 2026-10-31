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

## Decision 5: do not claim production hardening before validation

The project's own guidance explicitly warns against claiming guarantees without evidence.

### Consequence

The current batch stops at architecture review and documentation. We do not claim that RLS, authorization, or rate limiting is complete until those checks are actually implemented and validated.

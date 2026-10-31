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

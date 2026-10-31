# Backend Hardening Test Matrix

## Status conventions

- **IMPLEMENTED** means code or policy changes exist; it does not imply they were exercised.
- **VERIFIED** means the listed relevant tests passed in the stated environment.
- **BLOCKED** means the test could not be completed or a deployment assumption is unresolved.
- **ACCEPTED** is reserved for a risk explicitly approved by the project owner. No open risk below is marked accepted.

## Historical Batch 0 validation

| Check | Command / method | Historical result |
|---|---|---|
| Go module validation | `cd /home/nahom/Projects/personal/KMS && go test ./...` | Failed: repository root is not a Go module. |
| Python suite discovery | `cd /home/nahom/Projects/personal/KMS/nlp && uv run pytest -q tests` | Failed at collection due missing dependencies and package-import setup. |
| Architecture review | Static review of Go/Python routes and tenant code | Completed; findings are retained in `PROGRESS.md` and `ARCHITECTURE.md`. |

These are historical attempts; the focused Python command below is the later successful run.

## Corrective review — current evidence

| Area | Test / command | Result | Coverage and limits |
|---|---|---|---|
| User JWT and API authorization | `cd /home/nahom/Projects/personal/KMS/nlp && PYTHONPATH=. pytest tests/test_authz.py tests/test_ramp_v2.py tests/test_evidence_composition.py tests/test_query_engine_context.py -q` | **VERIFIED — 35 passed** | Forged identity header rejection, token expiry/issuer/audience/algorithm/role checks, wrong-company membership, service-token misuse, and tenant-filter-aware application fakes. Third-party deprecation warnings only. |
| PostgreSQL tenant policy harness | `cd /home/nahom/Projects/personal/KMS && psql 'postgresql://postgres@127.0.0.1:55432/postgres' -f schema/tests/tenant_rls.sql` | **VERIFIED — passed** on disposable PostgreSQL 16 | Applies both migrations twice. Exercises RLS tenant visibility and writes, non-recursive membership lookup, self-insertion/self-promotion rejection, unauthorized role change, company creation with owner, graph RPC filtering, and service-role access. Uses a minimal `auth.uid()` compatibility stub; this is not a live Supabase test. |
| Migration fail-closed behavior | Disposable-database probe with an existing `companies.id = 'default'` | **VERIFIED — expected failure and rollback** | Migration aborted, original row remained, and schema/data changes in the failed transaction were rolled back. This probe was performed manually; it is not represented as a named automated test. |
| pgvector document RPC | Runtime execution of `match_documents` | **BLOCKED** | The disposable PostgreSQL image did not include pgvector. SQL requires explicit company filtering, but runtime RPC behavior is unverified. |
| Live Supabase catalog/policies/data | No live query or migration was performed | **BLOCKED** | Need operator-reviewed inventory, existing-data mapping, grants/policy reconciliation, and deployment validation. |
| Production JWT signer | Live Supabase signing configuration not inspected | **BLOCKED** | Python verifier currently supports HS256 only. Confirm issuer, audience, and algorithm before exposure; asymmetric/JWKS support is not implemented. |
| Invitation lifecycle | No end-to-end invitation integration test exists | **BLOCKED** | Persisted invitation storage and invite acceptance are not implemented; direct unauthorized membership additions are denied by policy tests. |

## Negative test coverage

| Requirement | Evidence | Status |
|---|---|---|
| Forged `X-User-Id` / unauthenticated direct API call | Python authz tests | **VERIFIED** |
| Missing, expired, wrong-issuer, wrong-audience, wrong-algorithm, or wrong-role user token | Python authz tests | **VERIFIED** |
| Service-token misuse as user identity | Python authz tests | **VERIFIED** |
| User/company mismatch | Python membership check tests with filter-aware fakes | **VERIFIED** |
| Membership self-insertion and self-promotion | Disposable PostgreSQL policy harness | **VERIFIED** |
| Unauthorized/cross-company role change | Disposable PostgreSQL policy harness | **VERIFIED** |
| Cross-tenant reads/writes through RLS | Disposable PostgreSQL policy harness | **VERIFIED** |
| Cross-tenant retrieval through pgvector RPC | Query filters are implemented; RPC not executable without pgvector | **BLOCKED** |
| Live Supabase policy behavior and grants | Not run; production database was not contacted | **BLOCKED** |

## Batch status

| Batch | Current status | Basis |
|---|---|---|
| Batch 1 — tenant guardrails | **IMPLEMENTED**; local policy verification **VERIFIED**, live deployment **BLOCKED** | Guardrail/access migrations and disposable PostgreSQL harness; existing unmapped data requires operator review. |
| Batch 2 — identity and membership | **IMPLEMENTED**; focused test behavior **VERIFIED**, production JWT/invitation assumptions **BLOCKED** | Python negative tests and database policy harness passed. |
| Batch 3 | Retain status recorded in `PROGRESS.md`; this corrective work did not rerun its test suite. | No new verification claim. |
| Batch 4 — rate limiting | **BLOCKED — not started** | Explicitly deferred until corrective review blockers are resolved or documented as accepted. |

No live Supabase database was changed. Do not treat disposable PostgreSQL results as proof of the live schema, production grants, deployed JWT signing configuration, or pgvector extension behavior.

## Go ingress corrective review — 2026-11-01

| Area | Exact command | Result | Coverage and limits |
|---|---|---|---|
| Go API format and tests | `gofmt -w api && cd api && go test ./...` | **VERIFIED — passed** (`api`, `handlers`, `repository`, `services`; `domain` has no tests) | Tests user auth and tenant checks, exact Supabase filter construction, webhook bounds/signatures/timestamps, duplicate delivery idempotency, job tenant propagation, and server settings/shutdown. |
| Go race detector | `cd api && go test -race ./...` | **VERIFIED — passed** for all Go packages | Includes a blocked-until-released Slack mention handler test verifying handler completion waits for work and race-free response lifetime. |
| Go vet | `cd api && go vet ./...` | **VERIFIED — passed**, no diagnostics | Static checks for the Go API. |
| Frontend TypeScript | `cd /home/nahom/Projects/personal/kms-frontend/kms-frontend && npx tsc --noEmit --pretty false` | **VERIFIED — passed**, exit code 0 | Checks the query proxy forwarding the Supabase session bearer token. No frontend runtime integration was run. |
| Diff whitespace validation | `git diff --check` and `git -C /home/nahom/Projects/personal/kms-frontend/kms-frontend diff --check` | **VERIFIED — passed** | No whitespace errors found. |

### Go regression coverage

| Requirement | Evidence | Status |
|---|---|---|
| Missing/invalid Supabase bearer token | Handler auth tests; invalid token rejected by fake auth provider | **VERIFIED** |
| Non-member company / missing or default company | Query and baseline route tests | **VERIFIED** |
| Cross-company repository and unauthorized baseline sync | Strict company/repository fake plus real Supabase query parameter assertions | **VERIFIED** |
| Authorized company context propagated into query/baseline Redis jobs | Handler and service tests inspect both top-level and nested job fields | **VERIFIED** |
| Body size limit on Slack and GitHub webhook endpoints | Oversize requests return 413 | **VERIFIED** |
| Invalid Slack signature; Slack timestamps beyond past/future tolerance | Handler and service-verifier signed-body tests | **VERIFIED** |
| GitHub delivery ID format and duplicate delivery behavior | UUID validation and core ingestion idempotency test with filter-aware storage double | **VERIFIED** |
| No Gin context writes after handler return | Slack processing blocks until released; handler responds afterward; `go test -race` passes | **VERIFIED** |
| HTTP timeout/header configuration and graceful shutdown | Server configuration and cancellation/shutdown tests | **VERIFIED** |
| Live Supabase Auth and database grants/rows | Not contacted | **BLOCKED** |
| Real Slack/GitHub provider delivery, retry schedule, and production termination window | Not run | **BLOCKED** |

Unit and local HTTP tests do not establish production security. Supabase service key permissions, Auth endpoint behavior, the deployed `events.delivery_id` unique constraint, Go API network exposure, and shutdown timing must be checked in the target environment before production security is claimed. Rate limiting remains **BLOCKED / NOT STARTED**.

## Post-ingress service-role and Slack reliability review

| Area | Exact command | Result | Coverage and limits |
|---|---|---|---|
| Go API tests | `cd api && go test -count=1 ./...` | **VERIFIED — passed** | Includes actual PostgREST parameter assertions for company-scoped graph search and contribution reads/upserts; Slack subscribe-before-publish and lifecycle cases. |
| Go race detector | `cd api && go test -race -count=1 ./...` | **VERIFIED — passed** | All Go packages pass under the race detector, including immediate/delayed Slack responses, publish failure, worker failure/no result, worker result-channel close, cancellation, timeout, and subscription cleanup. |
| Go static analysis | `cd api && go vet ./...` | **VERIFIED — passed** | No diagnostics. |
| Python query/Ramp/worker tenant checks | `cd nlp && PYTHONPATH=. pytest tests/test_authz.py tests/test_ramp_v2.py tests/test_evidence_composition.py tests/test_query_engine_context.py tests/test_relationships.py tests/test_repository_updates_are_scoped.py -q` | **VERIFIED — 45 passed, 2 deprecation warnings** | Includes repository update tests asserting both the row ID and `company_id` predicates. Fakes record and enforce the query chain rather than dropping filters. |
| Python expanded focused attempt | `cd nlp && PYTHONPATH=. pytest tests/test_authz.py tests/test_ramp_v2.py tests/test_evidence_composition.py tests/test_query_engine_context.py tests/test_relationships.py tests/test_failure_semantics.py tests/test_repository_updates_are_scoped.py -q` | **BLOCKED — collection error** | `tests/test_failure_semantics.py` imports `sentence_transformers`, which is not installed. No dependency was installed for an unrelated test module; rerunning the applicable suite without that module passed (45 tests). |
| RLS and tenant migration harness | `PGPASSWORD=kms-local-review psql -h 127.0.0.1 -p 55432 -U postgres -d postgres -v ON_ERROR_STOP=1 -f schema/tests/tenant_rls.sql` | **VERIFIED — passed** on disposable PostgreSQL 16 | Applied the tenant guardrail and access-policy migrations twice and the new contributions tenant migration twice; verified membership/RLS behavior and mapped a historical contribution only through its company-owned repository. The disposable container was stopped afterward. |
| `match_documents` pgvector RPC | No runtime command available | **BLOCKED** | The disposable image lacked pgvector. SQL and caller both include company filtering, but RPC execution was not verified. |
| Live Supabase schema, grants, key role, and data | No live query or migration was performed | **BLOCKED** | In particular, checked-in `events` lacks `company_id` although Go event writes include it. Production schema parity and service-role configuration require operator verification. |
| Rate limiting | Documentation review only | **NOT STARTED** | Shared Redis counter/lease design and proposed limits are documented; no middleware, counters, leases, or 429 behavior were implemented. |

### Post-ingress security regression coverage

| Requirement | Evidence | Status |
|---|---|---|
| Slack fast-worker response cannot beat subscription setup | Fake Redis rejects publish until its result subscription is established; immediate-response test passes | **VERIFIED** |
| Delayed Slack worker response, publish failure, worker failure/no result, result-channel closure, cancellation, and timeout | `api/services/slack_bot_test.go`; operation context cancellation observed by subscription fake | **VERIFIED** |
| Go graph search requires a real tenant and applies the filter in the HTTP request | Supabase repository tests inspect `company_id=eq.company-a`; empty/default rejection covered | **VERIFIED** |
| Contribution query and write are tenant-scoped | Go tests assert company/repository filters, company value, and `company_id,person_name,repo_name` conflict target | **VERIFIED** |
| Baseline and incremental repository updates preserve tenant predicates | Python query-builder tests record actual filters and require both repository ID and company ID | **VERIFIED** |
| Cross-tenant vector retrieval at the live RPC boundary | `match_documents` SQL has a tenant predicate; no pgvector runtime test environment | **BLOCKED** |
| End-to-end service-role isolation against deployed Supabase | No live project access by design | **BLOCKED** |

## Ingestion and tenant-context corrective work — 2026-10-31

| Area | Exact command | Result | Coverage and limits |
|---|---|---|---|
| Go API regression tests | `cd api && go test -count=1 ./...` | **VERIFIED — passed** | Includes CoreIngest event `company_id`, cancellation/deadline propagation, Slack provider event-ID use, company-bound internal playbook JWT, and SlackBot tenant propagation. |
| Go race detector | `cd api && go test -race -count=1 ./...` | **VERIFIED — passed** | All Go packages pass under the race detector. |
| Go static analysis | `cd api && go vet ./...` | **VERIFIED — passed** | No diagnostics. |
| Python auth and internal playbook tests | `cd nlp && PYTHONPATH=. pytest tests/test_authz.py -q` | **VERIFIED — 22 passed, 2 third-party deprecation warnings** | Checks missing/user/service tokens, token scope, company-bound internal tokens, and cross-company rejection. |
| Python related query/Ramp tests | `cd nlp && PYTHONPATH=. pytest tests/test_authz.py tests/test_ramp_v2.py tests/test_evidence_composition.py tests/test_query_engine_context.py -q` | **VERIFIED — 40 passed, 2 third-party deprecation warnings** | Focused auth, tenant filtering, retrieval, evidence, and Ramp paths. |
| Events migration/RLS harness | `pg_isready -h 127.0.0.1 -p 55432; psql 'postgresql://postgres@127.0.0.1:55432/postgres' -v ON_ERROR_STOP=1 -f schema/tests/tenant_rls.sql` | **BLOCKED — no PostgreSQL server responded; psql connection refused** | Neither repeat application, historical mapping, global delivery-ID uniqueness, nor unmapped-data rollback has been executed in this session. |
| Live Supabase schema or migration | Not run | **BLOCKED** | No live database was contacted or changed. |

### New regression assertions

| Requirement | Evidence | Status |
|---|---|---|
| CoreIngest observes parent cancellation and inherits its deadline while enforcing the 10-second maximum | `api/services/core_test.go` | **VERIFIED** |
| Slack ingestion uses provider `event_id`; missing event IDs are rejected | `api/handlers/security_test.go` | **VERIFIED** |
| Slack playbook service receives the integration-resolved company ID | `api/services/playbook_test.go` | **VERIFIED** |
| Go playbook call carries a signed, short-lived, company-bound service JWT | `api/services/playbook_test.go` | **VERIFIED** |
| Python internal playbook route rejects absent tokens, user tokens, missing/default companies, and mismatched company claims | `nlp/tests/test_authz.py` | **VERIFIED** |
| Historical events map only from one unambiguous linked `raw_data` company; unmapped rows abort without deletion | `schema/tests/tenant_rls.sql`, `schema/tests/events_tenant_migration_unmapped.sql` | **IMPLEMENTED; database verification BLOCKED** |

The migration has not been applied to a live or disposable database in this run; schema/database behavior must not be reported as verified. Rate limiting remains **BLOCKED / NOT STARTED**.

CoreIngest cancellation verification covers propagation to Redis, not durable recovery after the database inserts. A cancellation in that interval can leave stored rows without a queued job; duplicate delivery currently does not republish. Durable outbox/reconciliation behavior remains **BLOCKED**.

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

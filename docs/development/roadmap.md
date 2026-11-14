# KMS Development Roadmap

> Canonical execution ledger for KMS product development.
> Product contract: `docs/product/ramp-prd.md`.
> Current intelligence objects: `docs/product/ramp-intelligence-model.md`.
> Current Ramp runtime: `docs/architecture/ramp.md`.
> Scoring spec vs implemented subset: `docs/product/ramp-candidate-scoring.md`.

**Last updated:** 2026-11-14
**Current branch:** `feat/krt-00-tenant-isolation`
**Current milestone:** KRT — Knowledge Reliability & Trust
**Current objective:** Prove that Ramp can move a new engineer from unfamiliarity to useful, safe contribution faster than normal onboarding.

---

## Documentation map

| Document | Authority |
|---|---|
| `docs/product/ramp-prd.md` | Customer outcome and product contract |
| `docs/product/ramp-redesign.md` | Accepted design direction (historical RID plan; not execution status) |
| `docs/product/ramp-intelligence-model.md` | Current evidence/candidate objects and epistemic rules |
| `docs/product/ramp-candidate-scoring.md` | Scoring/sequencing spec; notes where code differs |
| `docs/architecture/ramp.md` | Current Ramp intelligence and API boundary |
| `docs/product/ramp-candidate-evaluation-2026-09-20.md` | Read-only live candidate-quality snapshot |
| `docs/decisions/ADR-003-deterministic-ramp.md` | Deterministic fact/selection layer |
| `docs/decisions/ADR-004-imports-are-not-workflows.md` | Import edges are structural, not behavioral proof |
| `docs/architecture/knowledge-reliability.md` | Current knowledge-pipeline audit and target architecture |\n| `docs/development/milestones/2026-11-14-knowledge-reliability.md` | Specified implementation milestone and acceptance criteria |\n| this file | Task state, verified status, selected next work |

Do not copy pipeline diagrams into every document. Link here or to the intelligence model.

---

## Execution rules

```text
PLANNED → SPECIFIED → IN_PROGRESS → IMPLEMENTED → VERIFIED → ACCEPTED
                              ├→ BLOCKED
                              ├→ DEFERRED
                              └→ REJECTED
```

Implementation is not verification. Acceptance requires appropriate tests, runtime/manual verification, and review against the task's acceptance criteria. Do not advance a state without evidence in this repository or a dated evaluation artifact.

---

## Product direction

Ramp is an evidence-backed progression of bounded engineering outcomes:

```text
ORIENT → BUILD MENTAL MODEL → UNDERSTAND ROLE SURFACE
      → TRACE A REAL WORKFLOW → LEARN HOW CHANGES HAPPEN
      → MAKE A SAFE CONTRIBUTION → BECOME INDEPENDENTLY USEFUL
```

The First 7 Days framing is a time horizon, not a requirement to produce seven filler steps.

The central product question is:

> Given everything KMS knows about a company and a new engineer's role, what is the smallest sequence of understanding and real work that gets that engineer to their first safe, meaningful contribution?

A Ramp step is a learning/work outcome. Files, modules, and import edges are evidence, not the unit of onboarding.

An `IMPORTS` edge (`A imports B`) is a structural dependency. It does not, by itself, prove runtime execution order, a business workflow, ownership, or that a path is useful to a new engineer. See `docs/decisions/ADR-004-imports-are-not-workflows.md`.

---

## Current status

| Area | Status | Notes |
|---|---|---|
| Reliability Batch 1 | ACCEPTED | Tenant/failure semantics hardened. Unchanged by this branch; not re-verified on 2026-09-21. |
| Reliability Batch 2 | ACCEPTED | Redis pending-message recovery/ACK semantics hardened. Not re-verified on 2026-09-21. |
| Reliability Batch 3 | ACCEPTED | Durable codebase-analysis lifecycle and failure propagation. Not re-verified on 2026-09-21. |
| Ramp progress | ACCEPTED | User-specific progress persists and hydrates (code + prior tests). Not re-verified on 2026-09-21. |
| Ramp contextual Ask | IMPLEMENTED | Query engine can pass Ramp context into synthesis (`nlp/tests/test_query_engine_context.py`). Live worker usefulness is unverified. |
| Ramp frontend rendering | UNVERIFIED | Frontend lives in `kms-frontend`, outside this repository. |
| RID-01 evidence model | ACCEPTED | Target reasoning objects and evidence strength defined. |
| RID-02 evidence inventory | ACCEPTED | Existing KMS evidence and limitations mapped; inventory has grown since acceptance (see RID-05). |
| RID-03 real KMS proof | ACCEPTED | GitHub ingestion is a manual proof of a real workflow. Generated candidates are not this proof. |
| RID-04 candidate scoring + sequencing | ACCEPTED (spec) / IMPLEMENTED (subset) | Spec remains authoritative. Weighted learning scores, learning/contribution gates, and prerequisite-aware selection exist. See scoring gaps below. |
| RID-05 clean Ramp intelligence rewrite | IN_PROGRESS | Production path is `RampPlanner`. Workflow candidates are bounded import-path graphs, not validated workflows. |
| RID-06 legacy before/after fixture | REJECTED | The module-first generator is gone, so a before/after vs that output cannot be reproduced. Superseded by the 2026-09-20 live candidate evaluation. |
| Live candidate-quality evaluation | VERIFIED (structural snapshot) | `docs/product/ramp-candidate-evaluation-2026-09-20.md`. Human usefulness is not validated. |
| RID-07 Go route/handler corroboration | VERIFIED | Read-only extractor + focused tests + dated evaluation. Local verification: 3 route-evidence tests and 9 Ramp-v2 tests passed. Not yet accepted for product usefulness. No graph or plan writes. |
| Customer validation | NOT STARTED | No repository evidence of an engineer-who-did-not-build-KMS using Ramp. |
| Live DB/schema reconciliation | PLANNED | Live Supabase schema is ahead of repo SQL; not a current Ramp blocker. |
| RLS/security reconciliation | PLANNED | Required before broad customer exposure. |
| Canonical migration workflow | PLANNED | Required before future schema changes accumulate. |

---

## Ramp rewrite decision

The previous implementation strategy was incremental extension of `RampPlanGenerator`. That strategy remains rejected.

**Decision:** rewrite the Ramp intelligence layer around normalized evidence, workflow *candidates*, deterministic gates/scoring/sequencing, and a thin persistence/API boundary.

`RampPlanner` (`nlp/ramp/generator_v2.py`) is the production intelligence entrypoint, instantiated from `nlp/api.py`. There is no `nlp/ramp/generator.py` compatibility module on this branch.

---

## RID-01 — Target evidence model — ACCEPTED

Defined internal reasoning objects for company context, implementation surfaces, implementation relationships, capabilities, workflows, ownership/history, risk/verification, role relevance, learning candidates, and contribution candidates.

Evidence strength is classified as `direct`, `derived`, `inferred`, or `missing`.

---

## RID-02 — Current evidence inventory — ACCEPTED

KMS provides company-scoped repositories/files/modules, ownership edges, GitHub-derived `raw_data`, and (as of this branch) deterministic Python/Go `IMPORTS` edges written during baseline sync.

It still does not provide route/handler/call/queue/persistence/test evidence that would distinguish a structural dependency path from a runtime workflow. Do not invent that intelligence.

---

## RID-03 — Real KMS workflow proof — ACCEPTED

The GitHub ingestion path is a **manually established** behavioral proof:

```text
GitHub webhook
  → request/signature validation
  → event validation
  → core ingestion
  → idempotency check
  → events persistence
  → raw_data persistence
  → Redis github_jobs publication
```

This supports a backend learning outcome such as tracing one GitHub event through those boundaries.

It does **not** mean `WorkflowDiscoverer` currently emits this chain. Live candidates on 2026-09-20 were import paths labeled `api implementation flow` / `nlp implementation flow`, not this ingestion sequence.

It does **not** justify an autonomous first coding task.

---

## RID-04 — Candidate scoring + sequencing — ACCEPTED (spec)

Defined deterministic learning gates, weighted scoring, contribution readiness gates, prerequisite ordering, stage progression, redundancy handling, risk blocking, and explainability metadata.

Implemented subset (code, 2026-09-21):

- weighted 0–100 learning score on `RampCandidate`;
- learning eligibility gates (company scope, evidence, action, verification, non-high/unknown risk);
- contribution eligibility gates; the planner emits **no** contribution candidates;
- prerequisite + stage-order selection.

Not implemented (do not claim otherwise):

- evidence corroboration bonus;
- role-relevance trust ladder beyond path/module keyword tokens;
- contribution readiness score and 70/100 threshold;
- redundancy penalty;
- explicit shorter-sequence cap (selection currently keeps every eligible candidate whose prerequisites are satisfied);
- LLM explanation (`polish_why` is accepted by the API and unused by `RampPlanner`).

---

## RID-05 — Clean Ramp intelligence rewrite — IN_PROGRESS

### Architecture

See `docs/architecture/ramp.md` and `docs/product/ramp-intelligence-model.md`. Short form:

```text
KMS indexed knowledge
        ↓
  RampEvidenceStore
        ↓
 WorkflowDiscoverer (bounded directed import paths)
        ↓
  RampCandidateEngine
        ↓
     RampPlanner → RampStore / API
```

### Verified on this branch

| Claim | Evidence |
|---|---|
| Production API uses `RampPlanner` | `nlp/api.py` |
| No module-first generator on the production path | no `nlp/ramp/generator.py`; planner does not inherit a legacy generator |
| Company scoping at evidence extraction | `RampEvidenceStore` filters by `company_id` |
| Contribution candidates are not emitted | `RampPlanner._build_candidates` |
| Bounded directed paths, caps, cycle fallback, isolated-file ignore, weak-relation abstention | `nlp/ramp/workflows.py` + `nlp/tests/test_ramp_v2.py` |
| Python/Go `IMPORTS` extraction and indexing | `nlp/codebase/relationships.py`, `relationship_indexer.py`, `nlp/tests/test_relationships.py`; indexer called from baseline sync |
| Planner does not invent workflows without relationship evidence | `test_planner_does_not_fabricate_workflow_without_relationship_evidence` |

### Current limitation (verified)

Workflow *candidates* are bounded directed paths over graph edges whose endpoints are FILE entities, excluding `PART_OF` and `OWNS`. On the live evaluation snapshot, every supporting signal was a direct `IMPORTS` edge.

`IMPORTS` with extractor confidence `1.0` is stored as a direct graph fact. `WorkflowDiscoverer` then labels the path `<first-module-segment> implementation flow` and sets workflow confidence from relation strength (`direct` when confidence ≥ 0.8). That confidence describes the **import edges**, not a verified control/data-flow workflow.

Go package imports resolve to the first sorted non-test `.go` file in the package, not a specific symbol. Unresolved/external imports are dropped, not stored as inferred facts.

`RampCandidateEngine.select` does not cap sequence length or penalize redundant shared-leaf paths. A company with many import paths can therefore receive many workflow-learning steps.

Role surface selection still uses path/module keyword tokens. That is a discovery heuristic, not ownership proof. The generated action text says so; scoring still treats a keyword match as high role relevance.

### Acceptance criteria (unchanged; not all met)

RID-05 is accepted only when:

1. the production API uses the new planner;
2. no production Ramp intelligence inherits from the deleted module-first generator;
3. company scoping is enforced at evidence extraction and persistence boundaries;
4. selected steps are outcomes, not directory tours;
5. evidence strength is truthful and uncertainty is explicit;
6. prerequisite ordering is deterministic;
7. unsupported contribution candidates are not emitted;
8. stable step IDs and existing progress behavior continue to work;
9. focused and relevant backend tests pass locally;
10. a real populated company smoke test produces a coherent Ramp with customer-indexed evidence **that a new engineer can use as onboarding, not merely an import-path dump**.

Items 1–3, 6–7, and 9 have repository evidence. Item 4 is partial (titles are outcome-shaped; workflow names are module-segment labels). Item 5 is partial (import facts are direct; calling the path a workflow is not). Item 8 is implemented in code (UUID5 step IDs, `RampStore` progress) but not re-verified in this pass. Item 10 fails the 2026-09-20 snapshot: no candidate was a confirmed recognizable responsibility.

---

## RID-06 — Legacy before/after evaluation fixture — REJECTED

Original plan: compare module-first generator output to the new planner.

That comparison is no longer possible: the legacy generator is gone and its output is not checked in.

**Superseding artifact:** `docs/product/ramp-candidate-evaluation-2026-09-20.md` (read-only live snapshot for company `comp_1785181837594`, repository `nahom-zewdu/KMS`). Structural classification only. Human usefulness is explicitly not validated.

---

## RID-08 — Go handler → direct service-call corroboration — IMPLEMENTED

Chosen because the largest evidence-backed gap is not missing path heuristics. It is that Ramp cannot yet tell a new engineer **what a component does** or **what to inspect next** with evidence stronger than `A imports B`. The 2026-09-20 snapshot classified all live candidates as fragments, ordinary dependency chains, or merely potentially useful exploration paths. Adding more import-ranking rules would not close that gap.

### Objective

Determine whether explicit direct calls from an already-resolved HTTP handler through its declared dependency fields provide materially stronger onboarding evidence than `IMPORTS` or route→handler evidence, without claiming a full workflow and without writing to the graph or Ramp plans.

### Scope

In:

- already-resolved Go HTTP handlers from RID-07;
- direct `h.<field>.<method>(...)` calls through fields declared on the handler struct;
- a **read-only** extractor, focused tests, and dated evaluation report.

Out:

- generic Go call graphs;
- SSA/CFG/DFG analysis;
- interface implementation resolution;
- new graph relation types in production indexing;
- changes to `WorkflowDiscoverer`, scoring, or persistence;
- contribution candidates;
- mutating the live Supabase project.

### Acceptance criteria

1. The extractor reports handler symbol, declared receiver field, called method, source file, and line for direct dependency calls when those facts are present.
2. It abstains rather than guessing unresolved handler fields, methods, or implementations.
3. Tests cover direct detection, unrelated package calls, missing fields, multiple calls, and interface-boundary non-resolution.
4. The dated evaluation compares `IMPORTS` → route→handler → route→handler→direct-operation evidence.
5. No production data or Ramp behavior is mutated.
6. The evaluation states whether the signal is strong enough for a narrow promotion and identifies the smallest next product experiment.

### Verification method

- Focused handler-call extractor tests.
- Existing RID-07 route-evidence tests.
- Existing focused Ramp-v2 tests.
- `git diff` review confirming no planner/indexer/persistence behavior change.

### Non-goal

Do not treat a direct interface call as proof of the concrete implementation, complete workflow, ownership, or safe contribution.

---

## RID-09 — Route → handler → direct-operation evidence composition — IMPLEMENTED

RID-07 and RID-08 established two read-only source signals: explicit Gin route → handler resolution and explicit handler-field → dependency-method calls. RID-09 composes those facts without changing graph indexing, WorkflowDiscoverer, scoring, planner behavior, or persistence.

### Objective

Test whether:

```text
HTTP route → concrete handler → explicitly called dependency operation
```

forms a more actionable onboarding boundary than import paths or route-only evidence.

### Scope

In:

- composition of `RouteEvidence` + `HandlerCallEvidence`;
- deterministic joins on handler symbol and handler source file;
- source-backed next-inspection target equal to the observed dependency field/method;
- focused unit tests and a dated structural evaluation.

Out:

- interface implementation resolution;
- generic call graphs / SSA / CFG / DFG;
- runtime ordering;
- ownership or contribution-safety inference;
- graph writes, Ramp-plan writes, planner/scoring changes.

### Current status

Implemented as `nlp/ramp/evidence_composition.py` with focused tests in `nlp/tests/test_evidence_composition.py`.

The evaluation artifact is `docs/product/ramp-evidence-composition-evaluation-2026-09-22.md`.

The structural decision is **PROMOTE TO HUMAN USEFULNESS TEST, not production integration**. The signal is most useful for domain-service boundaries such as GitHub ingestion and baseline synchronization; shared Redis operations are weaker because they describe transport mechanics rather than business responsibility.

### Verification / acceptance

Local execution is still required before marking RID-09 VERIFIED. Acceptance additionally requires a dated human usefulness evaluation with an engineer who did not build KMS. Until then the composition layer remains read-only and unintegrated.

---

## Known limitations and unresolved questions

| Item | State |
|---|---|
| Import paths as Ramp workflow steps | Implemented; **not** validated as useful onboarding |
| Semantic correctness of candidate labels | Labels are first module-path segment + `implementation flow` |
| Live full `RampPlanner.generate` output for the evaluated company | Unverified in this pass; evaluation inspected discoverer inputs/outputs, not a persisted plan |
| Frontend rendering of v2 step shapes | Unverified (separate repo) |
| Contextual Ask live usefulness | Unverified |
| Customer / new-engineer validation | Not started |
| `company_id` API fallback `"default"` | Present in `nlp/api.py`; production tenant-safety of that fallback is unverified here |
| Score weights and contribution threshold | Calibration parameters; not empirically tuned |

---

## Deferred infrastructure

Live Supabase schema reconciliation, RLS/security hardening, and canonical migration workflow remain separate workstreams. Do not pull them into RID-07, RID-08, or RID-09.


---

# 2026-11-14 — Milestone transition: KMS Knowledge Reliability & Trust

**Current branch:** `feat/implementation-relations`  
**Current milestone:** MVP-1 Ramp intelligence/evidence work — handoff pending  
**Next milestone:** KRT — Knowledge Reliability & Trust  
**Status:** SPECIFIED; implementation has not started  
**Specification:** `docs/development/milestones/2026-11-14-knowledge-reliability.md`

## Current milestone record

The current branch extends the Ramp intelligence model with Python/Go import indexing, read-only Go route/handler evidence, direct handler-operation evidence, and evidence composition. The roadmap and related evaluation artifacts explicitly distinguish structural dependencies from behavioral proof.

The work is not accepted as customer-ready Ramp intelligence. RID-05 remains in progress; RID-09's structural evidence composition is implemented but still requires local verification and a human usefulness test. Customer validation remains not started. See the task sections and dated evaluation artifacts above for exact boundaries.

## Branch and merge gate

The next repository integration step is to merge `feat/implementation-relations` **into** `feat/ramp`. PR #20 is not that merge: it merged `feat/ramp` into `feat/implementation-relations`.

Do not start KRT implementation on this branch. After the requested merge:
1. Verify the updated `feat/ramp` head and relevant backend/frontend checks.
2. Create a fresh KRT implementation branch from that merged `feat/ramp` head.
3. Start KRT-00 (tenant isolation/security) only.

## KRT milestone overview

| ID | Workstream | Priority | Status | Exit condition |
|---|---|---:|---|---|
| KRT-00 | Supabase tenant isolation and RPC security | P0 | SPECIFIED | Cross-tenant access is denied and covered by role-aware tests |
| KRT-01 | Durable source snapshots and provenance | P1 | PLANNED | Source is retrievable by exact commit/path/hash and stale deletions reconcile |
| KRT-02 | Code intelligence (symbols and behavioral evidence) | P1 | PLANNED | Source-backed symbol/reference evidence is available for supported languages |
| KRT-03 | Hybrid retrieval (SQL, FTS, path, vector, graph) | P1 | PLANNED | Retrieval benchmark shows correct scope and relevant evidence |
| KRT-04 | Typed query planning and grounded synthesis | P1 | PLANNED | Correct tool routing, claim-level citations, and reliable abstention |
| KRT-05 | Evaluation and observability | P1 | PLANNED | Versioned benchmark and end-to-end traces gate query changes |

**Why KRT-00 comes first:** the live Supabase audit reported RLS/grant/RPC configurations that may permit cross-tenant access. This must be re-verified against the active project and corrected before adding more retrieval surfaces or exposing real customer data.

**Architecture decision:** retain the existing Go, Python, Redis Streams, Supabase/Postgres, and pgvector stack. Improve data contracts, provenance, indexing, retrieval orchestration, and evaluation before considering new infrastructure.

**Scope discipline:** this is not a commitment to build every phase at once. KRT-00 is the only first implementation batch. Each later phase is activated only after the prior acceptance gate and an updated review of the evidence.


---

# KRT execution update — 2026-11-14

**Backend repository:** `nahom-zewdu/KMS`  
**Backend branch:** `feat/krt-00-tenant-isolation`  
**Base commit:** `68ad38f4d2b40f9e9cb535243f1a2dab4ab1ea9b`  
**Frontend repository:** `nahom-zewdu/kms-frontend`  
**Frontend branch:** `feat/krt-00-tenant-isolation`  
**KRT-00 status:** IN_PROGRESS — critical findings confirmed; frontend hardening and database migration/test changes committed; none have been runtime-verified or applied to live Supabase.

## Verified merge and branch state

PR #21 merged successfully. The resulting `feat/ramp` head is `68ad38f4d2b40f9e9cb535243f1a2dab4ab1ea9b`. GitHub compare confirms the new backend branch was created from that exact head. A separate frontend branch was created from its `feat/ramp` head.

## KRT-00 live audit — 2026-11-14

The active Supabase project `iqafzuthrjfykfxndres` was audited read-only. Security Advisor reports 11 public tables with RLS disabled:
`events`, `raw_data`, `edges`, `contributions`, `pull_requests`, `issues`, `query_logs`, `repositories`, `codebase_files`, `file_entity_links`, and `codebase_modules`.

Confirmed policy/RPC defects:
- `company_members` permits self-insert (`WITH CHECK auth.uid() = user_id`) and self-update without a restrictive `WITH CHECK`; a user may be able to self-enroll or alter their own membership role/company.
- `entities` has two permissive `FOR ALL USING (true)` policies.
- `playbooks` has a permissive public `FOR ALL USING (true)` policy.
- `companies` is readable by the public through `USING (true)`.
- `match_documents` is callable by `anon` and `authenticated`, allows a NULL company filter, and has mutable search_path.
- `search_edges_by_entity(text,text[])` is callable by `anon` and `authenticated`, has no company filter, and has mutable search_path. The current Python caller passes a third company filter, so the deployed signature does not match.
- `reconcile_repository_files(uuid,text,text[])` and `replace_implementation_edges(text,uuid[],jsonb)` are callable by browser roles. The former does not verify that the supplied repository belongs to the supplied company before deleting stale rows.
- Integration table grants expose direct browser-role table privileges even though it contains access tokens, refresh tokens, and webhook secrets. This table must become backend-only.

Security Advisor additionally reports mutable search_path on both query RPCs and leaked-password protection disabled. Password protection is tracked separately from the KRT data-boundary gate.

## Live data-integrity snapshot

Read-only counts/consistency checks:
- 2 companies; 2 company memberships, both admins.
- 422 entities; zero null/default company IDs.
- 611 edges; zero null company IDs and zero source/target company mismatches.
- 153 raw_data rows; zero null/default company IDs.
- 149 events; zero null/default company IDs.
- 237 codebase files and 96 modules; no missing repository references.
- 0 file_entity_links.
- 0 contributions; live `contributions` table lacks `company_id`, although current application code expects it.

These are dated audit counts, not durable product metrics. The empty contributions table makes a tenant-column migration feasible without a historical row backfill, but the migration still needs an explicit constraint and verification plan.

## Application access-path findings

- Frontend `GET /api/codebase` used the public anon client without authentication or company/repository scope. It is now changed on the frontend KRT branch to require a verified user and filter file inventory through repositories belonging to the active company.
- Frontend `/api/integrations` now uses the server-only admin client only after membership/role checks and selects non-secret integration metadata.
- Legacy `/onboard/[slug]` queried public playbooks by role only, which could return another company's latest playbook. It now requires a verified session and filters by active company. Public role-slug sharing is disabled until a revocable, unguessable share-token design exists.
- Go/Python workers use service-role credentials; database access must remain service-role-only for raw events, outbox, query logs, legacy analytics, and integration secrets.
- Frontend server routes using the admin client must continue to perform explicit membership and role checks because service_role bypasses RLS.

## Work committed so far

Frontend branch `feat/krt-00-tenant-isolation` (draft PR #3):
- `app/api/codebase/route.ts`: authentication + active-company repository scope; no anon-client query.
- `app/api/integrations/route.ts`: admin-client use behind membership/admin checks; no credential columns in responses.
- `app/onboard/[slug]/page.tsx`: authenticated active-company playbook query.
- Slack OAuth state is now HMAC-signed/time-limited and callback rechecks the authenticated initiating user and company-admin role.
- Active-company switching now verifies the requested company belongs to the authenticated user.
- Added Slack OAuth state tests and frontend security docs.

Backend branch now includes `supabase/migrations/20261114150000_enforce_company_tenant_isolation.sql` and expanded `schema/tests/tenant_rls.sql`. The migration is authored but not run; the SQL harness, frontend lint/build, and backend suites remain unverified. No live database DDL or data/policy changes have been made.

## Remaining KRT-00 work

1. Design and commit one canonical Supabase migration: correct membership/company/playbook/entity policies; enable RLS on all exposed public tables; revoke browser grants on backend-only tables and integration secrets; grant only required member reads; restrict all sensitive RPCs to service_role; fix graph RPC tenant signature; harden repository reconciliation ownership checks and search_path.
2. Resolve schema drift: add `contributions.company_id` with a safe FK/unique key; verify events/raw_data/entities/edges ownership constraints and composite edge endpoint constraints.
3. Extend `schema/tests/tenant_rls.sql` to cover anon denial, membership self-enrollment/self-promotion, cross-company reads/writes, RPC execute privileges, and repository ownership checks.
4. Run migration + SQL harness against disposable PostgreSQL, then run backend and frontend suites/builds.
5. Apply the reviewed migration to the active Supabase project only after disposable verification and explicit deployment approval; re-run Advisors and role-based live checks.
6. Update both roadmaps and open coordinated PRs only when code/tests/docs are ready.

**Do not mark KRT-00 VERIFIED or ACCEPTED until the migration is tested and live database role checks prove the boundary.**


### 2026-11-14 implementation checkpoint

- Supabase remediation migration authored: `supabase/migrations/20261114150000_enforce_company_tenant_isolation.sql`.
- Migration scope: remove permissive company/member/entity/playbook policies; deny self-enrollment/self-promotion; enable RLS on all public tenant/knowledge tables; revoke browser access to integration credentials, raw events, analytics, and worker queues; grant only scoped member reads; require company ID for vector/graph RPCs; restrict sensitive RPCs to service_role; verify repository ownership before file reconciliation; add tenant and composite ownership constraints; add missing `contributions.company_id`.
- Test harness now includes the migration plus anonymous denial, RPC privilege, tenant-scoped graph, membership self-insert, and self-promotion assertions.
- The migration and test harness have **not** been executed. Do not infer correctness from successful GitHub file writes.
- Frontend hardening continues in the separate draft PR #3: Slack OAuth callback authorization and active-company switch validation were added after the initial codebase/playbook changes.

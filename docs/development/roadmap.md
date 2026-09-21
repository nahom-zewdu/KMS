# KMS Development Roadmap

> Canonical execution ledger for KMS product development.
> Product contract: `docs/product/ramp-prd.md`.
> Current intelligence objects: `docs/product/ramp-intelligence-model.md`.
> Current Ramp runtime: `docs/architecture/ramp.md`.
> Scoring spec vs implemented subset: `docs/product/ramp-candidate-scoring.md`.

**Last updated:** 2026-09-21
**Current branch:** `feat/implementation-relations`
**Current milestone:** MVP-1 — New Engineer Ramp
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
| this file | Task state, verified status, selected next work |

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
| RID-07 Go route/handler corroboration | SPECIFIED | Selected next task. Read-only; no graph or plan writes. |
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

## Selected next task — RID-07 — Read-only Go route/handler corroboration — SPECIFIED

Chosen because the largest evidence-backed gap is not missing path heuristics. It is that Ramp cannot yet tell a new engineer **what a component does** or **what to inspect next** with evidence stronger than `A imports B`. The 2026-09-20 snapshot classified all live candidates as fragments, ordinary dependency chains, or merely potentially useful exploration paths. Adding more import-ranking rules would not close that gap.

### Objective

Determine which existing import-path candidates can be corroborated by one behavioral source signal—Go HTTP route registration and the handler/service files those routes reference—without claiming a full workflow and without writing to the graph or Ramp plans.

### Scope

In:

- `api/handlers/routes.go` and referenced Go handler/service files in this repository;
- the 16-candidate fixture in `docs/product/ramp-candidate-evaluation-2026-09-20.md`;
- a **read-only** extractor (tests + local report). The extractor may parse source in the working tree or a fetched snapshot; it must not `upsert`/`delete` `edges`, entities, or `ramp_plans`.

Out:

- new graph relation types in production indexing;
- changes to `WorkflowDiscoverer` caps, labels, or scoring weights;
- contribution candidates;
- frontend work;
- Python call-graph extraction;
- mutating the live Supabase project.

### Acceptance criteria

1. The extractor reports route method, path, and referenced handler symbol/file when those facts are present in source; it abstains rather than guessing missing links.
2. Each of the 16 fixture candidates is reclassified using the evaluation's criteria (recognizable responsibility, potentially useful exploration path, ordinary dependency chain, fragment), now allowing route/handler corroboration as additional evidence.
3. The report states, for each candidate, whether corroboration was found, what exact source span supports it, and which claims remain unsupported.
4. No production data is written. Tests cover parse success, abstention on unsupported files, and stability of output for `api/handlers/routes.go`.
5. A follow-up recommendation is written only after the report: either promote corroborated facts into Ramp evidence, or document why this signal is still too weak.

### Verification method

- Unit tests for the read-only extractor against `api/handlers/routes.go` and at least one negative fixture.
- A checked-in evaluation addendum (new dated file or a clearly marked section) comparing the 16 candidates before vs after corroboration.
- `git diff` review confirming no indexer, discoverer, or persistence behavior change unless a documentation inconsistency cannot be resolved otherwise (not expected).

### Non-goal

Do not treat a Gin route registration as proof of runtime execution order, ownership, or a safe first contribution.

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

Live Supabase schema reconciliation, RLS/security hardening, and canonical migration workflow remain separate workstreams. Do not pull them into RID-07.

# KMS Development Roadmap

> Canonical execution ledger for KMS product development.

**Last updated:** 2026-09-12
**Current branch:** `feat/ramp`
**Current milestone:** MVP-1 — New Engineer Ramp
**Current objective:** Prove that Ramp can move a new engineer from unfamiliarity to useful, safe contribution faster than normal onboarding.

---

## Execution rules

```text
PLANNED → SPECIFIED → IN_PROGRESS → IMPLEMENTED → VERIFIED → ACCEPTED
                              ├→ BLOCKED
                              ├→ DEFERRED
                              └→ REJECTED
```

Implementation is not verification. Acceptance requires appropriate tests, runtime/manual verification, and review against the task's acceptance criteria.

---

## Product direction

Ramp is not an attractive checklist. It is an evidence-backed progression of bounded engineering outcomes that moves a new engineer from:

```text
ORIENT → BUILD MENTAL MODEL → UNDERSTAND ROLE SURFACE
      → TRACE A REAL WORKFLOW → LEARN HOW CHANGES HAPPEN
      → MAKE A SAFE CONTRIBUTION → BECOME INDEPENDENTLY USEFUL
```

The First 7 Days framing is a time horizon, not a requirement to produce seven filler steps.

The central product question is:

> Given everything KMS knows about a company and a new engineer's role, what is the smallest sequence of understanding and real work that gets that engineer to their first safe, meaningful contribution?

A Ramp step is a learning/work outcome, not a module, directory, feature, technology, or file. Those are evidence and implementation entities that a step may reference.

---

## Current status

| Area | Status | Notes |
|---|---|---|
| Reliability Batch 1 | ACCEPTED | Tenant/failure semantics hardened. |
| Reliability Batch 2 | ACCEPTED | Redis pending-message recovery/ACK semantics hardened. |
| Reliability Batch 3 | ACCEPTED | Durable codebase-analysis lifecycle and failure propagation. |
| Ramp progress | ACCEPTED | User-specific progress persists and hydrates. |
| Ramp contextual Ask | IMPLEMENTED / VERIFYING | Structured question/context path exists; live worker verification remains required. |
| Ramp frontend rendering compatibility | IN PROGRESS | Normalize historical/current target-file shapes at the UI boundary. |
| RID-01 evidence model | ACCEPTED | Target reasoning objects and evidence strength defined. |
| RID-02 evidence inventory | ACCEPTED | Existing KMS evidence and limitations mapped. |
| RID-03 real KMS proof | ACCEPTED | GitHub ingestion demonstrates a real workflow proof; contribution remains unqualified. |
| RID-04 candidate scoring + sequencing | ACCEPTED | Gates, scoring, prerequisites, risk, explainability defined. |
| RID-05 clean Ramp intelligence rewrite | IN_PROGRESS | Legacy module-first intelligence is being replaced, not incrementally decorated. |
| RID-06 evaluation fixture | PLANNED | Before/after quality measurement after the new planner is coherent. |
| Customer validation | NOT STARTED | Begins once the new planner produces credible company-specific outcomes. |
| Live DB/schema reconciliation | PLANNED | Live Supabase schema is ahead of repo SQL; not a current Ramp blocker. |
| RLS/security reconciliation | PLANNED | Required before broad customer exposure. |
| Canonical migration workflow | PLANNED | Required before future schema changes accumulate. |

---

## Ramp rewrite decision

The previous implementation strategy was incremental extension of `RampPlanGenerator`. That strategy is now rejected.

The old generator was fundamentally module/directory-first:

```text
modules + files + ownership + importance + path heuristics
                    ↓
             rank modules
                    ↓
              select up to 7
                    ↓
             generate prose
```

Adding more fields or adapters around that architecture would preserve the wrong abstraction and increase legacy coupling.

**Decision:** rewrite the Ramp intelligence layer around normalized evidence, behavioral workflow candidates, deterministic gates/scoring/sequencing, and a thin persistence/API boundary. Preserve working infrastructure and external data/API contracts only where they are actually useful.

The old intelligence implementation has been removed from the production path. `RampPlanner` is the new intelligence entrypoint.

---

## RID-01 — Target evidence model — ACCEPTED

Defined internal reasoning objects for company context, implementation surfaces, implementation relationships, capabilities, workflows, ownership/history, risk/verification, role relevance, learning candidates, and contribution candidates.

Evidence strength is explicitly classified as `direct`, `derived`, `inferred`, or `missing`.

---

## RID-02 — Current evidence inventory — ACCEPTED

KMS already provides company-scoped repositories/files/modules, ownership signals, GitHub-derived history, and source-code-backed ingestion behavior. It does not yet provide a normalized Ramp intelligence graph containing reliable workflow relationships, change precedent, and verification evidence.

Do not invent missing intelligence. Extract what KMS actually knows and represent uncertainty explicitly.

---

## RID-03 — Real KMS workflow proof — ACCEPTED

The GitHub ingestion path provides the first concrete behavioral proof:

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

This supports a backend learning outcome such as tracing one GitHub event through those boundaries and explaining where invalid or duplicate deliveries are stopped.

It does **not** yet justify an autonomous first coding task because bounded-change, history, ownership, and verification evidence are not sufficiently integrated.

---

## RID-04 — Candidate scoring + sequencing — ACCEPTED

Defined deterministic learning gates, weighted scoring, contribution readiness gates, prerequisite ordering, stage progression, redundancy handling, risk blocking, and explainability metadata.

Important decisions:

- gates precede scores;
- contribution readiness is separate from learning relevance;
- inferred evidence may support learning but never qualifies an unsupported contribution;
- prerequisite-aware selection replaces global top-N module ranking;
- shorter meaningful Ramps beat seven-step filler;
- deterministic metadata survives into the generated plan;
- LLM output may explain evidence but cannot invent or override company facts.

---

# RID-05 — Clean Ramp intelligence rewrite — IN PROGRESS

### Architecture

```text
KMS indexed knowledge
        ↓
  RampEvidenceStore
        ↓
 normalized evidence
        ↓
 WorkflowDiscoverer + role reasoning
        ↓
  RampCandidateEngine
        ↓
 gates → score → prerequisites → sequence
        ↓
     RampPlanner
        ↓
   RampStore / API contract
```

### Implemented slices

- `nlp/ramp/models.py` — typed evidence, implementation, workflow, and candidate models.
- `nlp/ramp/evidence.py` — company-scoped extraction from `codebase_files`, `codebase_modules`, `edges`, and GitHub `raw_data`.
- `nlp/ramp/workflows.py` — workflow candidate discovery over normalized implementation evidence; inferred relationships remain explicitly inferred.
- `nlp/ramp/candidates.py` — deterministic gates, scoring, contribution gate, prerequisite-aware selection.
- `nlp/ramp/store.py` — isolated plan/progress persistence boundary.
- `nlp/ramp/generator_v2.py` — new Ramp planner; no inheritance from the legacy generator.
- `nlp/api.py` — production Ramp endpoints now instantiate `RampPlanner`.
- Legacy `evidence_generator.py` and legacy generator implementation have been removed from the production design.

### Current limitation

The first rewrite slice still discovers workflows from indexed structural vocabulary. That is a deliberate uncertainty boundary, not a claim of full call-graph understanding. A workflow candidate must direct the engineer to verify relationships in source. The next implementation work is to increase the quality of normalized implementation relationships and workflow evidence rather than adding presentation prose.

### Acceptance criteria

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
10. a real populated company smoke test produces a coherent Ramp with customer-indexed evidence.

---

# RID-06 — Before/after evaluation fixture — PLANNED

Compare the legacy output captured before the rewrite against the new planner using:

- meaningfulness;
- role relevance;
- workflow coherence;
- evidence strength;
- actionability;
- unsupported claims;
- cognitive load;
- contribution readiness.

The fixture should expose whether the redesign is genuinely better rather than merely longer or more structured.

---

## Deferred infrastructure

Live Supabase schema reconciliation, RLS/security hardening, and canonical migration workflow remain separate workstreams. Do not use them as reasons to preserve incorrect Ramp abstractions, and do not pull them into the Ramp rewrite unless the current implementation actually requires them.

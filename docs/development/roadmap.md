# KMS Development Roadmap

> **Canonical execution ledger for KMS product development.** The repository is the durable source of truth for work performed by ChatGPT, Copilot, Cursor, Claude, and humans.

**Last updated:** 2026-09-12  
**Current branch:** `feat/ramp`  
**Current milestone:** MVP-1 — New Engineer Ramp  
**Current objective:** Prove that Ramp can move a new engineer from unfamiliarity to useful, safe contribution faster than normal onboarding.

---

## 1. Execution rules

Task lifecycle:

```text
PLANNED → SPECIFIED → IN_PROGRESS → IMPLEMENTED → VERIFIED → ACCEPTED
                              ├→ BLOCKED
                              ├→ DEFERRED
                              └→ REJECTED
```

An agent reporting success is not verification. `ACCEPTED` requires review against acceptance criteria plus appropriate tests/build/manual verification.

Every implementation task must record task ID, status, owner/agent, repository/branch, acceptance criteria, verification, changes, and material decisions.

Agents must receive only the scope needed for the current task. Newly discovered work is recorded separately rather than silently added to the active task.

---

# 2. Current product direction

Ramp is the first customer-facing KMS workflow. Its job is not to generate an attractive checklist. Its job is to reduce the time and senior-engineer effort required for a new engineer to understand an unfamiliar engineering system and begin meaningful work.

The central product question is:

> **Given everything KMS knows about a company and a new engineer's role, what is the smallest sequence of understanding and real work that gets that engineer to their first safe, meaningful contribution?**

The First 7 Days framing is a time horizon, not a requirement to generate seven arbitrary steps.

The canonical product contract remains in `docs/product/ramp-prd.md`.

The intelligence model and redesign plan are in `docs/product/ramp-redesign.md` and `docs/product/ramp-intelligence-model.md`.

---

# 3. Current status

| Area | Status | Notes |
|---|---|---|
| Reliability Batch 1 | ACCEPTED | Tenant/failure semantics hardened. |
| Reliability Batch 2 | ACCEPTED | Redis pending-message recovery/ACK semantics hardened. |
| Reliability Batch 3 | ACCEPTED | Durable codebase-analysis job lifecycle and failure propagation. |
| Ramp generation foundation | ACCEPTED | Company/role scope, stable IDs, evidence/resource resolution, ownership signals. |
| Ramp progress | ACCEPTED | User-specific step progress persists and hydrates. |
| Ramp contextual Ask | IMPLEMENTED / VERIFYING | Structured question/context path exists; live end-to-end verification remains required before acceptance. |
| Ramp frontend rendering compatibility | IN_PROGRESS | Current generated target files use richer objects while older plans may contain strings; normalize at the UI boundary. |
| RID-01 target evidence model | ACCEPTED | Minimum reasoning objects/signals defined. |
| RID-02 current evidence inventory | ACCEPTED | Existing KMS evidence mapped with strength and limitations. |
| RID-03 real KMS proof | ACCEPTED | GitHub ingestion workflow proves the intended feature → workflow → implementation → role → learning chain; contribution gate remains unqualified. |
| **RID-04 candidate scoring + sequencing** | **ACCEPTED** | Deterministic eligibility, scoring, prerequisite ordering, redundancy, and contribution gates defined. |
| **RID-05 narrow implementation slice** | **NEXT** | Implement the smallest evidence/candidate path proving one workflow-oriented Ramp step. |
| RID-06 before/after evaluation fixture | PLANNED | Must demonstrate actual quality improvement. |
| Customer validation | NOT STARTED | Begins as soon as a credible redesigned Ramp slice exists. |
| Live DB/schema reconciliation | PLANNED | Live Supabase schema is ahead of repository SQL. Not a blocker unless current work requires it. |
| RLS/security reconciliation | PLANNED | Required before broad customer exposure. |
| Canonical migration workflow | PLANNED | Required before schema changes accumulate. |

---

# 4. Completed Ramp foundation

## Ramp generation foundation

The existing generator provides company/role-scoped plans, stable deterministic step identity, repository/file evidence resolution, ownership signals, risk tiers, structured step fields, and role-aware prioritization.

## Ramp progress

Implemented backend persistence and frontend workspace behavior for user-specific `not_started`, `in_progress`, and `completed` step state, including API proxying and optimistic UI behavior. Manual persistence was confirmed.

## Ramp contextual Ask

The frontend sends a user question plus current-step context. The backend/query engine is designed to retrieve using the actual question while treating Ramp context as interpretation-only context, not evidence. The remaining acceptance requirement is live verification that the worker receives the fields separately and retrieval is performed only against the actual question.

## Known frontend compatibility issue

Historical Ramp plans may represent `target.files` as strings while current plans may represent files as objects containing path/repository/module/GitHub metadata. The frontend must normalize this boundary rather than rendering objects directly.

---

# 5. Critical redesign decision

The previous plan treated **Batch A — Make the Step Useful** as the next implementation batch. That is now superseded.

The current generator is primarily a **module/directory selection algorithm dressed as onboarding**:

```text
modules + files + ownership + importance + path heuristics + role keywords
                    ↓
             rank modules
                    ↓
              select up to 7
                    ↓
             generate prose
```

This is not sufficient for the product outcome. Adding more `why`, `do`, `done_when`, or resource fields to the same selection algorithm would improve presentation while preserving the underlying conceptual failure.

Therefore:

> **Do not continue implementing generator features until the Ramp intelligence model has been specified and evaluated against a real repository.**

See `docs/product/ramp-redesign.md`, `docs/product/ramp-intelligence-model.md`, and `docs/architecture/ramp.md`.

---

# 6. Active phase — Ramp Intelligence Discovery

RID-01 through RID-04 are now complete as a discovery/design baseline. Their durable outputs are:

- `docs/product/ramp-intelligence-model.md`
- `docs/product/ramp-candidate-scoring.md`

## RID-01 — Define target evidence model — ACCEPTED

Defined minimum internal reasoning objects for company context, implementation surfaces, relationships, capabilities, workflows, ownership/history, risk/verification, role relevance, learning candidates, and contribution candidates.

Key decision: entities such as modules/files/features are evidence objects; the Ramp step is a bounded learning/work outcome.

Evidence strength is explicitly classified as `direct`, `derived`, `inferred`, or `missing`.

## RID-02 — Inventory current KMS evidence — ACCEPTED

Mapped current evidence sources and limitations. KMS already has company/repository/file/module/ownership signals and actual source-code behavior that can support a workflow proof. It does not yet expose a normalized Ramp relationship/candidate layer, and Ramp does not currently consume Git history/PR patterns/tests as integrated contribution evidence.

Key conclusion: do not invent missing intelligence. Build the smallest evidence layer that closes the highest-value gap.

## RID-03 — Real KMS end-to-end example — ACCEPTED

The KMS GitHub ingestion path provides the first concrete proof:

```text
GitHub webhook
  → request/signature validation
  → GitHub event validation
  → core ingestion
  → idempotency check
  → events persistence
  → raw_data persistence
  → Redis github_jobs publication
```

This supports a backend onboarding outcome such as:

> Trace one GitHub event from webhook entry through validation, persistence, and queue publication, and explain where failures or duplicate deliveries are stopped.

The contribution candidate is deliberately **not qualified** yet. The source proves implementation behavior, but the integrated history + verification + bounded-change evidence needed for a safe first coding task is not currently part of the Ramp candidate model.

## RID-04 — Candidate scoring and sequence rules — ACCEPTED

Defined deterministic hard gates, learning relevance scoring, contribution readiness scoring, prerequisite-aware sequence construction, redundancy penalties, stage ordering, explainability metadata, and conservative contribution eligibility.

Key decisions:

- hard gates precede scoring;
- contribution readiness is separate from learning relevance;
- risk can block first contribution regardless of relevance;
- prerequisite-aware selection replaces global top-N module ranking;
- shorter meaningful Ramps beat seven-step filler;
- deterministic selection metadata must survive into the generated plan;
- the LLM may explain evidence-backed candidates but cannot override factual eligibility or invent company knowledge.

Exact weights and thresholds are calibration parameters, not permanent product truths.

## RID-05 — Narrow implementation slice — NEXT

Implement only enough backend reasoning to prove the following path:

```text
existing KMS evidence
      ↓
small internal candidate objects
      ↓
eligibility gates
      ↓
score + prerequisite ordering
      ↓
GitHub ingestion workflow candidate
      ↓
existing Ramp step serializer
```

Do **not** rewrite the whole generator, add a new database schema, build universal AST analysis, add semantic embeddings for candidate selection, or add contribution generation in this slice.

**Acceptance:** For a backend role on the KMS repository, the redesigned path can construct and serialize at least one workflow-oriented learning candidate whose evidence points to the actual GitHub ingestion chain, while preserving existing company scoping and stable step identity. The candidate must carry deterministic selection metadata. No unsupported contribution task may be emitted.

## RID-06 — Before/after evaluation fixture — PLANNED

After RID-05, compare old and redesigned output on meaningfulness, role relevance, workflow coherence, evidence strength, actionability, contribution readiness, unsupported claims, and cognitive load.

**Acceptance:** The fixture can expose whether the redesign is genuinely better, not merely more verbose.

---

# 7. Target Ramp model

A Ramp is an **evidence-backed progression of engineering outcomes**.

A step is a **bounded learning/work outcome**. It is not a module, directory, feature, technology, or file.

A step may reference those entities as evidence.

Default progression:

```text
Orient
  ↓
Build mental model
  ↓
Understand role surface
  ↓
Trace a real workflow
  ↓
Learn how changes happen
  ↓
Make a safe contribution
  ↓
Become independently useful
```

A generated step should provide, as applicable:

- objective;
- why now;
- system/workflow context;
- supporting evidence;
- concrete action;
- verification/done-when;
- credible help/ownership;
- next capability unlocked.

A contribution is **not mandatory**. If KMS lacks sufficient evidence for a safe, bounded change and verification path, it should stop at readiness rather than invent a task.

---

# 8. Target intelligence architecture

```text
Company knowledge
      ↓
Structural extraction
      ↓
Implementation relationships
      ↓
Feature / workflow inference
      ↓
Role relevance
      ↓
Learning + contribution candidates
      ↓
Sequence / prerequisite reasoning
      ↓
Evidence gate
      ↓
Ramp steps
      ↓
LLM explanation / presentation
```

Deterministic logic owns facts, evidence, mechanically derivable relationships, stable identity, risk/verification signals, candidate traceability, and company scoping.

LLM reasoning may synthesize evidence-backed explanations, compare candidates, express tradeoffs, and formulate readable objectives. It must not invent company facts, ownership, workflows, files, or contribution tasks.

---

# 9. Superseded / deferred Ramp work

The following earlier roadmap items are not deleted; their purpose has changed under the redesign.

| Former task | Status | Reason |
|---|---|---|
| RAMP-A-01 through RAMP-A-07 | SUPERSEDED | They improved step presentation without fixing module-first candidate selection. |
| RAMP-A-08 frontend StepWorkspace polish | DEFERRED | UI should follow the new step model. |
| RAMP-A-09 batch verification | SUPERSEDED | Replaced by the before/after intelligence evaluation. |
| RAMP-B progress persistence | ACCEPTED | Already implemented and manually verified. |
| RAMP-C feedback/manager visibility | DEFERRED | Product feedback is valuable, but generator quality must first be credible. |
| RAMP-D polish | DEFERRED | Must be driven by actual customer usage. |

Existing progress and Ask capabilities should be retained where compatible with the redesigned model.

---

# 10. Customer validation

Validation begins as soon as the redesigned Ramp is credible enough to put in front of a real engineer.

Primary question:

> Does Ramp help a real engineer understand an unfamiliar codebase and begin meaningful work faster than the team's normal onboarding process?

Hypotheses:

1. Evidence-backed guidance reduces time-to-context.
2. Role-specific paths are more useful than generic onboarding.
3. Evidence transparency increases trust.
4. Action-oriented steps outperform passive recommendations.
5. Managers value reduced senior-engineer onboarding effort and credible progress visibility.

Do not treat internal demos or generated-plan quality as proof of product-market fit.

---

# 11. Deferred technical debt

| ID | Item | Priority | Status |
|---|---|---:|---|
| TECH-001 | Deleted-file lifecycle in codebase knowledge graph | P1 | DEFERRED |
| TECH-002 | Large GitHub push batching/orchestration | P1 | DEFERRED |
| TECH-003 | Repository uniqueness migration | P1 | DEFERRED |
| TECH-004 | Live Supabase schema vs repository SQL reconciliation | P0 | PLANNED |
| TECH-005 | RLS/security policy reconciliation | P0 | PLANNED |
| TECH-006 | Canonical Supabase migration workflow | P0 | PLANNED |
| TECH-007 | Further Redis reliability optimization | P2 | DEFERRED |

Do not reopen these unless a concrete customer-facing blocker appears or the planned reconciliation milestone is reached.

---

# 12. Documentation map

| Document | Purpose |
|---|---|
| `docs/product/ramp-prd.md` | Customer problem, product contract, MVP scope, success criteria. |
| `docs/product/ramp-redesign.md` | Target Ramp intelligence model and active redesign execution plan. |
| `docs/product/ramp-intelligence-model.md` | RID-01/02/03 evidence model, current evidence inventory, and real KMS proof. |
| `docs/product/ramp-candidate-scoring.md` | RID-04 deterministic candidate eligibility, scoring, sequencing, and contribution gate. |
| `docs/architecture/ramp.md` | Technical architecture and migration strategy. |
| `docs/decisions/ADR-003-deterministic-ramp.md` | Decision and clarified scope for deterministic/evidence-first generation. |
| `docs/development/roadmap.md` | Canonical execution ledger and current task state. |

---

# 13. Change log

| Date | Agent/person | Change | Verification |
|---|---|---|---|
| 2026-08-31 | ChatGPT/Copilot | Established Ramp product/implementation roadmap and reliability foundation tracking. | Recorded in prior roadmap. |
| 2026-09-12 | ChatGPT | Reviewed current Ramp architecture and identified module-first generation as the primary product defect. | Repository implementation reviewed against PRD and architecture docs. |
| 2026-09-12 | ChatGPT | Added `docs/product/ramp-redesign.md`. | Committed to `feat/ramp`. |
| 2026-09-12 | ChatGPT | Reworked Ramp architecture and deterministic-generation decision around outcome-first reasoning. | Committed to `feat/ramp`. |
| 2026-09-12 | ChatGPT | Added `docs/product/ramp-intelligence-model.md` with RID-01/02/03 baseline and KMS GitHub-ingestion proof. | Repository source reviewed; contribution candidate intentionally left unqualified. |
| 2026-09-12 | ChatGPT | Added `docs/product/ramp-candidate-scoring.md` and accepted RID-04. | Deterministic gates/scoring/sequence rules reviewed against the KMS proof. |
| 2026-09-12 | ChatGPT | Advanced RID-05 as the next implementation task. | Recorded in this roadmap. |

---

# 14. Immediate next action

**RID-05 — Narrow implementation slice.**

Do not implement the whole redesign.

The next engineering task is to create the smallest internal candidate/evidence path capable of producing one real workflow-oriented learning step for the KMS GitHub ingestion chain, while preserving the existing Ramp API/persistence contracts.

Only after RID-05 is verified should we run RID-06 before/after evaluation and decide whether broader workflow extraction is justified.

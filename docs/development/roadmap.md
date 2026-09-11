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

The new intelligence model and execution plan are in `docs/product/ramp-redesign.md`.

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
| **Ramp Intelligence Redesign** | **IN_PROGRESS** | Current priority. Module-first generation is being replaced conceptually before further generator expansion. |
| Customer validation | NOT STARTED | Begins as soon as a credible Ramp slice exists. |
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

See `docs/product/ramp-redesign.md` and `docs/architecture/ramp.md`.

---

# 6. Active phase — Ramp Intelligence Discovery

**Goal:** Establish the minimum intelligence model required for Ramp to produce meaningful onboarding rather than a directory tour.

## RID-01 — Define target evidence model

**Status: PLANNED**

Define the minimum internal representation for:

- capabilities/features;
- workflows;
- implementation surfaces;
- ownership;
- history;
- risk;
- verification;
- learning outcomes;
- contribution candidates.

**Acceptance:** The model clearly distinguishes entities (module/file/feature/technology) from onboarding outcomes (steps).

## RID-02 — Inventory current KMS evidence

**Status: PLANNED**

Map each required signal to evidence KMS already has, its reliability, and the missing evidence required to reason about it.

**Acceptance:** No proposed intelligence depends on an assumed data source that KMS does not actually have.

## RID-03 — Real KMS end-to-end example

**Status: PLANNED**

Using the KMS repository itself, demonstrate:

```text
feature/capability
    → workflow
    → implementation
    → role relevance
    → learning outcome
    → contribution candidate
```

**Acceptance:** Every transition is backed by identifiable evidence, or the exact missing signal is documented.

## RID-04 — Candidate scoring and sequence rules

**Status: PLANNED**

Define deterministic criteria for relevance, prerequisite value, evidence strength, risk, learning value, contribution potential, ownership/help, and verification.

**Acceptance:** The sequence can be explained without relying on arbitrary LLM preference.

## RID-05 — Narrow implementation slice

**Status: PLANNED**

Choose the smallest backend implementation that can demonstrate materially better candidate generation than the current module-first generator.

**Acceptance:** Scope is small enough for focused Copilot execution and tests.

## RID-06 — Before/after evaluation fixture

**Status: PLANNED**

For the same company/role, compare old and redesigned output on:

- meaningfulness;
- role relevance;
- workflow coherence;
- evidence strength;
- actionability;
- contribution readiness;
- unsupported claims;
- cognitive load.

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
| 2026-09-12 | ChatGPT | Rewrote `docs/architecture/ramp.md` around the target intelligence model. | Committed to `feat/ramp`. |
| 2026-09-12 | ChatGPT | Clarified ADR-003: deterministic/evidence-first remains, but module-first steps do not. | Committed to `feat/ramp`. |
| 2026-09-12 | ChatGPT | Updated this roadmap and replaced Batch A as the next implementation direction with Ramp Intelligence Discovery. | Committed to `feat/ramp`. |

---

# 14. Immediate next action

**Do not send Copilot an implementation prompt yet.**

The next task is **RID-01 + RID-02 + RID-03: design and prove the intelligence model on the actual KMS repository**.

The deliverable is a concrete, evidence-backed specification showing what KMS currently knows, what a good Ramp should infer from it, what it cannot currently infer, and the smallest implementation needed to close the most valuable gap.

Only after that deliverable is reviewed should Copilot receive an implementation task.

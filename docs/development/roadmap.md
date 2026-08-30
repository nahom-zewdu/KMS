# KMS Development Roadmap

> **Canonical execution ledger for KMS product development.**
>
> This document tracks product work, implementation batches, verification, decisions, and deferred work across ChatGPT, Copilot, Cursor, Claude, and any other engineering agent. The repository is the durable source of truth; conversational context is not.

**Last updated:** 2026-08-31  
**Current development branch:** `feat/ramp`  
**Documentation branch:** `feat/ramp-docs`  
**Current milestone:** MVP-1 — New Engineer Ramp  
**Current objective:** Make Ramp useful enough to put in front of real engineers and managers.

---

## 1. How to use this roadmap

Every meaningful piece of work must be represented here, regardless of who performs it.

### Task lifecycle

```text
PLANNED → SPECIFIED → IN_PROGRESS → IMPLEMENTED → VERIFIED → ACCEPTED
                              │
                              ├────────→ BLOCKED
                              ├────────→ DEFERRED
                              └────────→ REJECTED
```

A task is **not complete merely because an agent reports success**. `ACCEPTED` means the implementation has been reviewed against its acceptance criteria and the relevant tests/build/manual verification have passed.

### Required tracking for implementation work

Each task should record, where applicable:

- **Task ID** — stable identifier; never reuse IDs.
- **Status** — current lifecycle state.
- **Owner/agent** — ChatGPT, Copilot, Cursor, Claude, human, etc.
- **Repository/branch** — where the work was performed.
- **Acceptance criteria** — what must be true when finished.
- **Verification** — tests, builds, manual checks, or review performed.
- **Changes** — important files/components affected.
- **Notes/decisions** — assumptions, discoveries, or deviations.

### Agent handoff rule

When delegating work to an agent, give it the relevant task IDs and acceptance criteria. When it reports back, map its changes back to those IDs. Do not allow an agent's report to silently create new scope.

### Scope rule

If investigation discovers important work outside the current batch:

1. Record it under **Deferred Technical Debt** or create a future task.
2. Do not silently expand the active batch.
3. Revisit it when the roadmap reaches the relevant milestone.

---

# 2. Current product milestone — MVP-1: New Engineer Ramp

## Product objective

Turn Ramp from a generated recommendation/list into a genuinely useful onboarding workflow for a new engineer entering an unfamiliar codebase.

The target workflow is:

```text
Manager/Engineer starts Ramp
        ↓
Understand where to go
        ↓
Open a step
        ↓
Understand WHY it matters
        ↓
Inspect real evidence
        ↓
Perform a concrete action
        ↓
Know what "done" means
        ↓
Mark outcome
        ↓
Move to next step
        ↓
Give feedback
        ↓
Manager sees useful progress/value
```

The primary product question is **not** whether we can generate sophisticated recommendations. It is whether an engineer actually becomes more effective in an unfamiliar repository because of Ramp.

### MVP-1 success bar

Ramp should make it possible for a new engineer to:

- understand why a recommended area matters;
- find the relevant repository evidence;
- perform a concrete investigation/learning action;
- understand what completion means;
- persist and resume progress;
- provide lightweight feedback;
- give a manager a credible view of progress and usefulness.

---

# 3. Current execution status

| Area | Status | Notes |
|---|---|---|
| Repository/architecture documentation | IN_PROGRESS | Documentation foundation is being established. |
| Product/Ramp PRD | ACCEPTED | Canonical product requirements exist in repository documentation. |
| Live DB/schema reconciliation | PLANNED | Live Supabase DB has evolved beyond the old SQL snapshot; reconcile before relying on schema.sql as canonical. |
| Ingestion reliability Batch 1 | ACCEPTED | Tenant/failure semantics hardened and tested. |
| Ingestion reliability Batch 2 | ACCEPTED | Redis pending-message recovery/ACK semantics implemented and tested. |
| Ingestion reliability Batch 3 | ACCEPTED | Codebase analysis moved to durable Redis job lifecycle; baseline failures propagate. |
| Ramp generation foundation | ACCEPTED | Stable step IDs and role/company-aware generation exist on `feat/ramp`. |
| **Ramp Batch A — Useful Step** | **PLANNED** | **Next implementation batch.** |
| Ramp Batch B — Persistent Progress | PLANNED | Follows Batch A. |
| Ramp Batch C — Feedback + Manager Visibility | PLANNED | Follows Batch B. |
| Ramp Batch D — Product Polish | PLANNED | Only after A–C and real usage. |
| Customer validation | NOT STARTED | Must begin as soon as MVP workflow is usable; do not postpone indefinitely. |

---

# 4. Phase 0 — Foundation & Reconciliation

## 4.1 Documentation foundation

| ID | Task | Status | Verification |
|---|---|---|---|
| DOC-001 | Establish persistent KMS development roadmap/execution ledger | IN_PROGRESS | This document created from `feat/ramp`. |
| DOC-002 | Establish repository-level AI development instructions (`AGENTS.md`) | PLANNED | Review against both backend and frontend workflows. |
| DOC-003 | Maintain product/architecture/data/development documentation alongside implementation | IN_PROGRESS | Continue updating docs as product decisions become concrete. |

## 4.2 Repository ↔ live system reconciliation

| ID | Task | Status | Notes |
|---|---|---|---|
| REC-001 | Reconcile backend repository structure and runtime responsibilities | PLANNED | Produce concise authoritative architecture documentation. |
| REC-002 | Reconcile frontend architecture and Ramp implementation | PLANNED | Record actual routes/components/data flow. |
| REC-003 | Reconcile live Supabase schema against repository SQL | PLANNED | Live DB is currently ahead of stale schema snapshots. |
| REC-004 | Reconcile RLS/security model against actual application access paths | PLANNED | Do not blindly enable policies without understanding service/client boundaries. |
| REC-005 | Establish canonical migration/schema workflow | PLANNED | Avoid future live DB vs repository drift. |

> **Important:** Reconciliation is necessary, but it must not become an endless audit. Only work needed to establish trustworthy engineering context should block product development.

---

# 5. Completed reliability foundation

These items are recorded for continuity. They are **not** an invitation to continue reliability optimization unless a customer-facing feature exposes a concrete blocker.

## Reliability Batch 1

**Status: ACCEPTED**

Key outcomes:

- tenant resolution is explicit and rejects unresolved/default tenants;
- conflicting GitHub installation/owner mappings are rejected;
- Python NLP/database failures propagate instead of becoming false successes;
- successful DB fallbacks remain successful;
- duplicate relation LLM invocation was removed;
- focused failure-semantics tests were added.

## Reliability Batch 2

**Status: ACCEPTED**

Key outcomes:

- Redis pending messages can be reclaimed with `XAUTOCLAIM`;
- failed processing does not ACK the message;
- recovery behavior is covered by focused tests.

## Reliability Batch 3

**Status: ACCEPTED**

Key outcomes:

- detached daemon-thread codebase analysis was replaced by a durable Redis job;
- baseline failures propagate;
- the consumer supports async handlers;
- codebase-analysis failures remain observable/retryable through the stream lifecycle.

### Explicitly deferred from reliability work

- deleted-file lifecycle/reconciliation;
- large GitHub push orchestration/truncation limits;
- repository uniqueness migration where required;
- live schema/RLS reconciliation;
- other hardening that does not directly block customer-facing validation.

These remain tracked below rather than being repeatedly rediscovered.

---

# 6. MVP-1 Ramp implementation roadmap

## Batch A — Make the Step Useful

**Status: PLANNED**  
**Goal:** Turn a generated Ramp step into an actionable learning unit.

### Definition of Done

- [ ] Every generated step has meaningful **Why** content grounded in available evidence.
- [ ] Every step explains what the engineer should understand.
- [ ] Every step provides concrete repository resources where available.
- [ ] Evidence is understandable to an engineer rather than exposed as raw metadata only.
- [ ] Every step has an actionable **Do** objective.
- [ ] Every step has an explicit **Done when** criterion.
- [ ] Actual repository identity/links are resolved where available.
- [ ] Generated claims do not exceed the evidence available to KMS.
- [ ] Backend tests pass.
- [ ] Frontend tests/build/type checks pass as applicable.
- [ ] End-to-end/manual workflow is reviewed.
- [ ] Documentation is updated with any material implementation decision.

### Tasks

| ID | Task | Status | Owner/Agent | Verification |
|---|---|---|---|---|
| RAMP-A-01 | Populate meaningful step WHY | PLANNED | — | — |
| RAMP-A-02 | Populate understandable step context/UNDERSTAND | PLANNED | — | — |
| RAMP-A-03 | Resolve actual repository/resources and GitHub links | PLANNED | — | — |
| RAMP-A-04 | Transform evidence into human-readable evidence/explanation | PLANNED | — | — |
| RAMP-A-05 | Add concrete DO/action objective to every step | PLANNED | — | — |
| RAMP-A-06 | Add explicit DONE-WHEN completion criterion | PLANNED | — | — |
| RAMP-A-07 | Validate evidence-grounding and prevent unsupported generated claims | PLANNED | — | — |
| RAMP-A-08 | Frontend StepWorkspace presents the complete action unit clearly | PLANNED | — | — |
| RAMP-A-09 | Batch-level verification and manual workflow review | PLANNED | — | — |

### Batch A exit criterion

A new engineer can open any generated step and answer:

> **Why am I doing this? What should I understand? Where should I look? What should I do? Who/evidence can help me? How do I know I'm done?**

---

## Batch B — Persistent Progress

**Status: PLANNED**  
**Goal:** Turn Ramp from a document into a persistent workflow.

### Definition of Done

- [ ] Minimal step progress model designed without premature complexity.
- [ ] `not_started`, `in_progress`, `completed`, and `skipped` states supported where appropriate.
- [ ] Progress persists across refresh/session.
- [ ] Engineer can resume their Ramp.
- [ ] Checklist/action state is persisted where it represents meaningful progress.
- [ ] Ramp-level progress is calculated from persisted state.
- [ ] UI clearly communicates current step and overall progress.
- [ ] Authorization/tenant boundaries are respected.
- [ ] Tests cover persistence and authorization behavior.

### Tasks

| ID | Task | Status |
|---|---|---|
| RAMP-B-01 | Design minimal progress persistence model | PLANNED |
| RAMP-B-02 | Implement backend progress API/persistence | PLANNED |
| RAMP-B-03 | Implement frontend progress state and interactions | PLANNED |
| RAMP-B-04 | Implement resume/current-step behavior | PLANNED |
| RAMP-B-05 | Add progress calculation | PLANNED |
| RAMP-B-06 | Add tests and end-to-end verification | PLANNED |

---

## Batch C — Feedback + Manager Visibility

**Status: PLANNED**  
**Goal:** Close the product learning loop and expose credible progress to the manager.

### Definition of Done

- [ ] Engineer can mark a step useful/not useful.
- [ ] Optional reason can be submitted without creating friction.
- [ ] Ramp-level feedback is available where useful.
- [ ] Manager can see engineer progress.
- [ ] Manager can see basic usefulness signals.
- [ ] Metrics are tied to product hypotheses rather than vanity analytics.

### Tasks

| ID | Task | Status |
|---|---|---|
| RAMP-C-01 | Design minimal usefulness feedback model | PLANNED |
| RAMP-C-02 | Implement step feedback | PLANNED |
| RAMP-C-03 | Implement Ramp-level feedback where justified | PLANNED |
| RAMP-C-04 | Implement manager progress summary | PLANNED |
| RAMP-C-05 | Implement basic usefulness/completion metrics | PLANNED |
| RAMP-C-06 | Test feedback and manager visibility flows | PLANNED |

---

## Batch D — Product Polish

**Status: PLANNED**  
**Goal:** Remove friction discovered through actual use, not hypothetical polish.

Potential scope:

- [ ] Better loading/empty/error states.
- [ ] Regeneration flow.
- [ ] Plan/versioning behavior where required.
- [ ] Stronger role differentiation based on observed usefulness.
- [ ] UX refinement from real user feedback.
- [ ] Remove dead/placeholder fields and implementation remnants.
- [ ] Improve contextual Q&A only where it demonstrably helps the Ramp workflow.

**Rule:** Do not start Batch D merely because the UI could look better. Customer usage and feedback should determine priority.

---

# 7. Customer validation

This section becomes active as soon as the core Ramp workflow is usable.

## Validation objective

Determine whether Ramp creates enough value for a real engineering team that they would continue using it and, eventually, pay for it.

### Product hypotheses to test

1. **Onboarding-time hypothesis:** Evidence-backed guidance helps a new engineer understand an unfamiliar codebase faster than unguided exploration.
2. **Manager-value hypothesis:** Managers value visibility into onboarding progress and where engineers are getting stuck.
3. **Trust hypothesis:** Engineers trust recommendations more when KMS explains the evidence behind them.
4. **Actionability hypothesis:** Concrete actions and completion criteria are more useful than a passive list of recommended files/modules.
5. **Retention hypothesis:** Engineers return to Ramp during their first weeks because it remains useful after the initial introduction.

### Customer validation ledger

| Customer/Team | Status | Engineer | Manager | Started | Completed | Feedback | Product changes |
|---|---|---|---|---|---|---|---|
| — | NOT STARTED | — | — | — | — | — | — |

### Validation rule

Do not interpret internal enthusiasm or successful demos as proof of product-market fit. We need behavior from people who did not build KMS.

---

# 8. Metrics

Metrics should answer whether Ramp is solving the intended pain, not merely whether users clicked things.

### Initial metrics

- Ramp started → first useful interaction.
- Time to first completed step.
- Steps completed within first session/week.
- Ramp completion rate.
- Step usefulness positive/negative rate.
- Feedback themes.
- Repeat usage during onboarding period.
- Manager engagement with progress view.
- Qualitative evidence of reduced time-to-productivity.

### Guardrail

Do not build a large analytics subsystem before we have users. Instrument only what is needed to answer the current product hypotheses.

---

# 9. Deferred technical debt

These items are intentionally recorded so they are not forgotten while keeping the MVP moving.

| ID | Item | Priority | Status | Revisit when |
|---|---|---:|---|---|
| TECH-001 | Deleted-file lifecycle in codebase knowledge graph | P1 | DEFERRED | Codebase freshness affects Ramp trust or query correctness |
| TECH-002 | Large GitHub push batching/orchestration | P1 | DEFERRED | Real repositories expose the current truncation limit |
| TECH-003 | Repository uniqueness migration to company-scoped constraint | P1 | DEFERRED | Live schema reconciliation / affected workflow |
| TECH-004 | Live Supabase schema vs repository SQL reconciliation | P0 | PLANNED | Phase 0 reconciliation; should not remain indefinitely |
| TECH-005 | RLS/security policy reconciliation | P0 | PLANNED | Before exposing multi-tenant customer data broadly |
| TECH-006 | Canonical Supabase migration workflow | P0 | PLANNED | Before production schema changes accumulate |
| TECH-007 | Further Redis reliability optimization | P2 | DEFERRED | Only if production/customer evidence identifies a concrete failure |

---

# 10. Architectural/product decisions

Material decisions should be recorded here and, when sufficiently significant, promoted to individual ADRs.

| Date | Decision | Reason | Impact |
|---|---|---|---|
| 2026-08-31 | Keep product development ahead of non-blocking infrastructure optimization | MVP had begun over-optimizing reliability before customer validation | Reliability batches are closed; focus shifts to Ramp usefulness |
| 2026-08-31 | Repository documentation is the durable AI/project context | Conversational memory cannot reliably preserve implementation state across agents/sessions | Agents must read docs before changing architecture/product behavior |
| 2026-08-31 | Update documentation in the active development branch as implementation evolves | Avoid branch proliferation for documentation-only changes | `feat/ramp` remains the main Ramp development line; docs evolve with it |
| 2026-08-31 | Ramp steps should be evidence-backed action units, not passive recommendations | This is the core product differentiation and trust mechanism | Drives Batch A design |

---

# 11. Change log

Record meaningful work performed through any agent or manually.

| Date | Agent/person | Task IDs | Repository/branch | Change | Verification |
|---|---|---|---|---|---|
| 2026-08-31 | ChatGPT | DOC-001 | `nahom-zewdu/KMS:feat/ramp-docs` | Created initial execution ledger from `feat/ramp` | Branch created; document committed |
| 2026-08-31 | Copilot | Reliability Batch 1 | `feat/ingestion-reliability-clean` | Tenant and failure semantics hardening | 8 Python tests; Go tests; compile/format checks passed |
| 2026-08-31 | Copilot | Reliability Batch 2 | `feat/ingestion-reliability-clean` | Redis pending-message recovery/ACK semantics | 5 recovery tests passed |
| 2026-08-31 | Copilot | Reliability Batch 3 | `feat/ingestion-reliability-clean` | Durable codebase analysis jobs and baseline failure propagation | 11 reliability tests; full 24-test suite reported passing |

---

# 12. Current next action

**Next implementation batch: `RAMP-A` — Make the Step Useful.**

Before delegating implementation:

1. Ensure the relevant PRD and architecture documentation are available to the agent.
2. Give Copilot only the small set of `RAMP-A-*` tasks needed for the current sub-batch.
3. Require it to report exact files changed, tests run, and task IDs completed.
4. Review the implementation against the acceptance criteria.
5. Update this roadmap immediately with status, verification, and change-log entries.
6. Move directly to the next sub-batch once verified; do not reopen closed reliability work without a concrete reason.

**Current state: `RAMP-A` is ready to begin.**

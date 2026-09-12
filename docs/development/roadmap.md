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
| **RID-05 narrow implementation slice** | **IMPLEMENTED / VERIFYING** | Added an evidence-first generator that derives a workflow candidate from company-scoped indexed files/modules/history; API now uses it. Runtime test execution is still required before acceptance. |
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

## RID-05 — Narrow implementation slice — IMPLEMENTED / VERIFYING

Implemented the smallest current evidence-first path for one workflow-oriented learning candidate:

```text
company-scoped codebase_files
          + codebase_modules
          + GitHub raw_data history
                    ↓
          deterministic evidence adapter
                    ↓
          workflow signals + implementation refs
                    ↓
          learning eligibility gate
                    ↓
          deterministic score + metadata
                    ↓
          existing Ramp step contract
```

The implementation lives in `nlp/ramp/evidence_generator.py` and is exposed through the existing `/ramp-plans/generate` endpoint. It deliberately does **not** add a database schema, universal AST analysis, semantic candidate embeddings, or contribution generation.

Important boundary: workflow labels such as webhook/handler/service/ingest/redis are derived from indexed codebase vocabulary and are marked as inferred workflow signals. The generator does not claim relationships that are absent from the indexed evidence. If the index cannot provide enough implementation/workflow evidence, it returns an explicit empty plan instead of falling back to hardcoded customer facts.

A focused test file, `nlp/tests/test_ramp_evidence.py`, covers indexed-path derivation, evidence metadata, insufficient-evidence refusal, and company scoping.

**Verification still required:** run the focused RID-05 tests plus the existing Ramp generator suite in the backend environment. Do not mark RID-05 `ACCEPTED` until those tests pass and a real company-scoped generation smoke test confirms the selected step's evidence comes from Supabase-indexed records.

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
structural extraction
      ↓
implementation relationships
      ↓
feature / workflow inference
      ↓
role relevance
      ↓
learning / contribution candidates
      ↓
sequence + dependency reasoning
      ↓
evidence check
      ↓
Ramp steps
      ↓
LLM presentation / explanation
```

Deterministic logic owns factual evidence, candidate identity, scoring, eligibility, risk, verification signals, company scoping, and traceability. LLM output may explain or compare already-supported candidates but cannot manufacture company facts.

---

# 9. Deferred work / guardrails

Do not expand into autonomous code changes, universal language AST support, a giant agent loop, semantic candidate selection, or schema redesign merely to make Ramp appear smarter.

Do not treat directory/module enumeration as feature/workflow understanding.

Do not emit a first coding task unless the contribution hard gates in `docs/product/ramp-candidate-scoring.md` are satisfied.

Do not accept implementation based solely on agent reports; verify tests and real evidence paths.

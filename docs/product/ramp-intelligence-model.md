# Ramp Intelligence Model — Evidence, Candidates, and First Proof

**Status:** Discovery baseline accepted / implementation not started
**Branch:** `feat/ramp`
**Last updated:** 2026-09-12
**Scope:** RID-01, RID-02, RID-03

## 1. Purpose

This document turns the Ramp redesign into an implementable reasoning model and proves the model against the KMS repository itself.

The objective is not to make the current generator's prose smarter. The objective is to establish the minimum evidence chain required for Ramp to recommend a meaningful learning or contribution outcome.

The core chain is:

```text
company evidence
  → capability / feature
  → workflow / behavior
  → implementation surface
  → role relevance
  → learning outcome
  → contribution candidate (only when evidence permits)
```

A broken link must be visible. The generator must not silently invent the missing link.

## 2. RID-01 — Target evidence model

The internal model should remain small and composable. These are reasoning objects, not necessarily new database tables.

### 2.1 Company context

```text
CompanyContext
- company_id
- repositories
- available_people
- available_documents
- available_history
```

All downstream evidence must remain company-scoped.

### 2.2 Implementation surface

```text
ImplementationSurface
- id / stable reference
- repository_id
- path
- module_path
- symbol (optional)
- kind: repository | module | file | symbol | route | handler | service | component | test
- language (optional)
- description (optional)
- importance (optional)
```

Files and modules are evidence-bearing implementation entities. They are not automatically Ramp steps.

### 2.3 Relationship evidence

```text
ImplementationRelation
- source
- target
- relation: calls | imports | handles | publishes | consumes | persists | tests | part_of | depends_on
- evidence_reference
- confidence
```

Only mechanically derivable or explicitly stored relationships should be treated as factual relationships.

### 2.4 Capability / feature

```text
CapabilityCandidate
- id
- name
- description
- implementation_refs[]
- evidence_refs[]
- confidence
```

A capability describes what the system provides or accomplishes. It must be supported by implementation, documentation, history, or other company evidence.

### 2.5 Workflow

```text
WorkflowCandidate
- id
- name
- trigger
- stages[]
- implementation_refs[]
- data/event_refs[]
- evidence_refs[]
- confidence
```

A workflow describes behavior across boundaries. It is stronger than a list of neighboring directories.

### 2.6 Human/change context

```text
OwnershipSignal
- subject_ref
- person_ref
- source
- confidence

HistorySignal
- subject_ref
- commit/pr/issue reference
- author
- changed_surface[]
- recency
```

Ownership and history are supporting signals for role relevance, help, risk, and change patterns. They must not be fabricated when unavailable.

### 2.7 Risk and verification

```text
RiskSignal
- subject_ref
- level: low | medium | high | unknown
- reason
- evidence_refs[]

VerificationSignal
- subject_ref
- method: test | endpoint | command | observable_behavior | review | unknown
- evidence_refs[]
```

Path names such as `core`, `auth`, or `payment` are not sufficient evidence for business risk. They may be weak hints until stronger evidence exists.

### 2.8 Role relevance

```text
RoleRelevance
- role
- subject_ref
- score
- signals[]
- evidence_refs[]
```

Signals can include ownership, historical changes, implementation position in relevant workflows, explicit role metadata, and only secondarily path/technology hints.

### 2.9 Learning outcome candidate

```text
LearningCandidate
- id
- objective
- why_now
- capability_refs[]
- workflow_refs[]
- implementation_refs[]
- action
- verification
- help_refs[]
- prerequisite_refs[]
- evidence_refs[]
- confidence
```

The candidate is the unit Ramp sequences. It is not a module.

### 2.10 Contribution candidate

```text
ContributionCandidate
- id
- problem_or_improvement
- implementation_refs[]
- expected_change
- verification
- risk
- ownership_refs[]
- history_refs[]
- evidence_refs[]
- confidence
```

A contribution candidate is valid only when its implementation surface, change target, verification path, risk, and reasonable help signal are sufficiently supported.

## 3. Evidence strength

Use a simple explicit evidence classification during the first implementation:

| Level | Meaning | Allowed use |
|---|---|---|
| `direct` | Explicitly present in code/data/document/history | State as fact |
| `derived` | Mechanically derived from direct evidence | State with traceability |
| `inferred` | Plausible interpretation requiring judgment | Explain as inference; do not present as fact |
| `missing` | KMS cannot establish it | Qualify or abstain |

The first generator implementation should prefer `direct` and `derived` evidence. `inferred` evidence can help ranking/explanation but cannot unlock a contribution candidate by itself.

## 4. RID-02 — Current KMS evidence inventory

The current repository already provides useful evidence, but the coverage is uneven.

| Target signal | Current KMS evidence | Strength | Current limitation |
|---|---|---|---|
| Company scope | `company_id` on ingestion/storage and Ramp queries | Direct | Some legacy/default paths remain |
| Repository | `repositories` and repository-scoped codebase files | Direct | Depends on baseline/index state |
| Module | `codebase_modules.module_path`, importance, metadata | Direct | Module semantics are not behavior |
| File | `codebase_files.file_path`, module, language, author, repository | Direct | Key-file selection is currently shallow |
| Ownership | `edges` with `type=OWNS`, entity lookup; `last_author` | Direct | Coverage depends on indexed KG/history |
| Importance | `codebase_modules.importance_score` | Direct | Importance is not role relevance |
| Architecture | file path grouping in Visualizer | Derived | Mostly directory topology |
| Role relevance | role/path keyword boost plus module importance | Derived/weak | Not yet responsibility/workflow based |
| Risk | Visualizer path keyword heuristics | Inferred/weak | Not reliable business-risk evidence |
| Implementation relationships | Code contains actual call/storage/publish chains | Direct in source; not yet normalized for Ramp | No dedicated Ramp relationship extraction layer |
| Workflow | Can be reconstructed from source code | Derived by human review | Not yet represented as a first-class candidate |
| Git history | GitHub repository history exists externally | Direct when retrieved | Not currently consumed by Ramp generator |
| PR/change pattern | GitHub PR/commit data can provide it | Direct when retrieved | Not currently consumed by Ramp generator |
| Tests/verification | Test files exist in repository where present | Direct when indexed/retrieved | Not yet connected to Ramp candidates |
| Contribution opportunity | No reliable first-class candidate model yet | Missing | Must not be fabricated |

### Important conclusion

KMS already contains enough raw material to prove the **workflow and implementation** part of the model manually. It does not yet contain enough normalized evidence to automatically produce high-confidence contribution candidates.

That is a useful boundary, not a failure.

## 5. RID-03 — Real KMS proof

The first proof uses a backend engineer role and the GitHub ingestion path because the current repository contains a concrete implementation chain.

### 5.1 Capability

**Capability candidate:** ingest GitHub engineering events into KMS for downstream knowledge processing.

Evidence:

- `api/handlers/github.go` receives GitHub webhook requests, validates the request, extracts event information, and delegates ingestion. cite-internal:github-handler
- `api/services/github.go` validates the GitHub ingest request and delegates to the shared core ingestion service. cite-internal:github-service
- `api/services/core.go` stores the event and summarized content and publishes a job to Redis for Python processing. cite-internal:core-ingest

### 5.2 Workflow

**Workflow candidate:**

```text
GitHub webhook
  → signature / request validation
  → GitHub event normalization
  → Core ingestion validation
  → idempotency check
  → events persistence
  → raw_data persistence
  → Redis job publication
  → downstream Python processing
```

This is a real behavior chain, not a directory-name inference.

Evidence:

1. `GitHubHandler.HandleGitHubWebhook` checks the HTTP method, reads the body, verifies `X-Hub-Signature-256`, requires a delivery ID, and proceeds to event handling. cite-internal:github-handler
2. `GitHubIngest.IngestGitHubEvent` requires source `github`, non-empty content, a delivery ID, and one of `push`, `pull_request`, or `issues`, then delegates to `CoreIngest.Ingest`. cite-internal:github-service
3. `CoreIngest.Ingest` checks duplicate delivery IDs, requires a real company ID, stores the raw event in `events`, stores summarized content in `raw_data`, and publishes a `github_jobs` Redis message containing the company ID and payload. cite-internal:core-ingest

### 5.3 Implementation surface

The relevant implementation surface for a backend engineer is not simply `api/handlers` or `api/services`.

It is the bounded chain:

```text
api/handlers/github.go
        ↓
api/services/github.go
        ↓
api/services/core.go
        ↓
Supabase: events + raw_data
        ↓
Redis: github_jobs
```

The key learning value is the behavior across these boundaries.

### 5.4 Role relevance

For a backend engineer, this surface is materially relevant because it contains HTTP handling, validation, persistence, and asynchronous job publication.

Current evidence for this role is partly direct from implementation responsibility and partly derived from the role-to-surface relationship. The current production generator cannot establish this reasoning reliably because it primarily uses path/module ranking and role keywords.

Therefore this proof establishes the desired reasoning shape, but not yet an automated role-relevance implementation.

### 5.5 Learning outcome

A strong Ramp candidate for this evidence would be:

> **Trace one GitHub event from webhook entry through validation, persistence, and queue publication, and explain where failures or duplicate deliveries are stopped.**

Why this is a better onboarding unit than `Learn api/handlers`:

- it teaches a real system behavior;
- it crosses implementation boundaries;
- it has a bounded evidence set;
- it exposes important backend responsibilities;
- it gives the engineer a mental model they can reuse when debugging or changing ingestion.

### 5.6 Contribution candidate

**Current automated status: NOT QUALIFIED.**

The repository source establishes the implementation and behavior, but the current Ramp evidence model does not yet have enough integrated history/change-pattern and verification signals to safely recommend a specific first coding change.

We therefore must **not** turn this proof into an invented task such as "add better GitHub validation" or "improve ingestion".

A future contribution candidate could become eligible if KMS can establish:

```text
concrete bounded problem
+ exact implementation surface
+ existing change/history precedent
+ reliable test/verification path
+ low/known risk
+ credible owner/help
```

Until then, the correct Ramp outcome is readiness through workflow understanding.

## 6. What this proves

The redesign has a viable intelligence shape:

```text
Implementation evidence
        ↓
real workflow
        ↓
role-relevant surface
        ↓
bounded learning outcome
        ↓
contribution gate
```

It also exposes the first implementation gap precisely:

> **KMS needs a lightweight evidence/relationship layer that can turn existing indexed codebase facts into workflow and candidate objects without requiring a universal code-understanding system.**

## 7. Immediate implementation consequence

Do not rewrite `RampPlanGenerator` yet.

The first code slice should build the smallest internal representation needed to express the proof above, using existing KMS data and deterministic extraction. It should be possible to produce a candidate whose evidence points to the real GitHub ingestion chain before adding broader feature inference.

The next design task is RID-04: define the deterministic candidate scoring and sequencing rules over these objects.

## 8. Source files reviewed for this proof

- `nlp/ramp/generator.py` — current module-first generator.
- `nlp/visualizer/service.py` — current structure/module/ownership/risk signals.
- `api/handlers/github.go` — GitHub webhook boundary and validation.
- `api/services/github.go` — GitHub-specific ingestion validation/delegation.
- `api/services/core.go` — persistence, idempotency, and Redis publication.

The current generator and Visualizer confirm that Ramp currently ranks modules and files and adds prose around them rather than constructing workflow outcomes. The ingestion files provide the first concrete cross-boundary behavior suitable for a redesigned Ramp candidate.

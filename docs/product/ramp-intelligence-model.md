# Ramp Intelligence Model — Evidence to Engineering Outcomes

**Status:** Active implementation baseline
**Branch:** `feat/implementation-relations`
**Last updated:** 2026-09-21
**Scope:** RID-01 through RID-05; next work is RID-07 in `docs/development/roadmap.md`

## 1. Product question

> Given everything KMS knows about a company and a new engineer's role, what is the smallest sequence of understanding and real work that gets that engineer to their first safe, meaningful contribution?

A Ramp step is a bounded learning/work outcome. It is not a module, directory, feature, technology, file, or import path.

---

## 2. Knowledge model

```text
COMPANY
├── repositories / modules / files
├── implementation relationships
├── capabilities / workflows
├── people / ownership
├── Git history / PRs / changes
├── documentation / decisions / incidents
└── tests / verification signals
```

These are evidence entities. Ramp reasons over them; it does not turn each entity into a step.

---

## 3. Evidence strength

Every signal is classified as:

- `direct` — explicitly represented by a KMS record or directly observed source fact;
- `derived` — mechanically derived from direct records;
- `inferred` — a plausible interpretation that still requires verification;
- `missing` — KMS does not currently support the claim.

An inferred workflow shape may create a learning candidate, but it must be presented as a hypothesis to verify. Inferred evidence never qualifies an autonomous first-contribution candidate.

A **direct** `IMPORTS` edge is a direct fact about a structural dependency. Direct import evidence does not make the enclosing path a direct workflow, execution trace, or ownership claim. See `docs/decisions/ADR-004-imports-are-not-workflows.md`.

---

## 4. Internal reasoning objects

The implementation uses four core layers:

### Evidence

`Evidence` identifies the source, strength, detail, repository, module, and metadata for a company fact.

### ImplementationSurface

`ImplementationSurface` represents an indexed file with repository/module/language/importance/history metadata.

### WorkflowCandidate

A bounded directed path over implementation-relation evidence (today: resolved `IMPORTS` edges). It is a **candidate exploration path**, not a confirmed business workflow. It contains evidence refs, signals, confidence (of those relations), role relevance, action, verification, risk, and prerequisites. Names are labels such as `api implementation flow`, not a feature taxonomy.

### RampCandidate

The common candidate representation used by deterministic gates, scoring, and sequencing.

The public Ramp step is produced only after candidate selection.

---

## 5. Deterministic pipeline

```text
KMS indexed knowledge
        ↓
RampEvidenceStore
        ↓
normalized Evidence + ImplementationSurface
        ↓
WorkflowDiscoverer / role relevance
        ↓
WorkflowCandidate
        ↓
RampCandidateEngine
        ↓
hard gates → weighted score → prerequisites → sequence
        ↓
RampPlanner
        ↓
RampStore
        ↓
existing API / frontend contract
```

The planner has no inheritance relationship with the former module-first generator.

---

## 6. Current implementation

The new implementation lives under `nlp/ramp/`:

- `models.py` — normalized reasoning objects;
- `evidence.py` — company-scoped evidence access;
- `workflows.py` — bounded directed-path candidate discovery over implementation relations;
- `candidates.py` — deterministic eligibility, scoring, and sequencing;
- `store.py` — persistence/progress boundary;
- `generator_v2.py` — `RampPlanner`, the production intelligence entrypoint.

`nlp/api.py` instantiates `RampPlanner` directly.

The historical module-first intelligence implementation has been removed. There is no `nlp/ramp/generator.py` on this branch.

File-to-file `IMPORTS` extraction lives under `nlp/codebase/relationships.py` and is indexed during baseline sync. Unresolved imports are omitted. Go packages resolve to the first sorted non-test `.go` file in the package.

---

## 7. Manual workflow proof vs generated candidates

KMS has a concrete GitHub ingestion behavior that can support a backend learning outcome. That chain was established by reading the implementation (RID-03), not by `WorkflowDiscoverer`:

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

Generated candidates on the 2026-09-20 live snapshot were import paths grouped as `api implementation flow` / `nlp implementation flow`. They are not this ingestion sequence and are not validated workflows. Source-level **import** extraction exists; source-level **behavioral** extraction (routes, calls, queues, tests) does not.

The generated learning action requires source verification and recording unsupported control/data-flow links as unknown. That hedging is required; it does not make the path a verified workflow.

Live classification: `docs/product/ramp-candidate-evaluation-2026-09-20.md`.

---

## 8. Candidate rules

Learning candidates require company-scoped evidence, implementation surfaces, a concrete action, and an observable verification method. Risk and evidence strength are represented separately from relevance.

Contribution candidates require substantially stronger evidence: bounded change surface, verification path, controlled risk, credible help, and sufficient history/change precedent. The current planner intentionally emits no contribution candidate when those signals are missing.

The score weights and thresholds are calibration parameters defined in `docs/product/ramp-candidate-scoring.md`.

---

## 9. LLM boundary

LLM use is optional presentation support only. It may explain or compare already evidence-backed candidates.

It may not:

- invent company facts;
- invent files, owners, workflows, or architecture;
- upgrade inferred evidence to direct evidence;
- qualify a contribution that deterministic gates reject.

---

## 10. Next implementation frontier

Import-path relationship evidence is **implemented**. It is not sufficient onboarding intelligence.

The next quality increase is **behavioral corroboration of existing candidates**, not more import heuristics or onboarding prose. Selected task: RID-07 in `docs/development/roadmap.md`.

```text
indexed files/modules
       ↓
IMPORTS (implemented; structural only)
       ↓
route/call/queue/test corroboration (not implemented)
       ↓
verified workflow structure
       ↓
change/history/verification evidence
       ↓
credible contribution candidates
```

Do not return to the old module-first generator or add adapters that recreate its behavior.

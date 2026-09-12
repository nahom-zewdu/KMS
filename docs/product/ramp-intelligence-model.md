# Ramp Intelligence Model — Evidence to Engineering Outcomes

**Status:** Active implementation baseline
**Branch:** `feat/ramp`
**Last updated:** 2026-09-12
**Scope:** RID-01 through RID-05

## 1. Product question

> Given everything KMS knows about a company and a new engineer's role, what is the smallest sequence of understanding and real work that gets that engineer to their first safe, meaningful contribution?

A Ramp step is a bounded learning/work outcome. It is not a module, directory, feature, technology, or file.

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

---

## 4. Internal reasoning objects

The implementation uses four core layers:

### Evidence

`Evidence` identifies the source, strength, detail, repository, module, and metadata for a company fact.

### ImplementationSurface

`ImplementationSurface` represents an indexed file with repository/module/language/importance/history metadata.

### WorkflowCandidate

A behavioral candidate derived from multiple implementation surfaces. It contains evidence refs, signals, confidence, role relevance, action, verification, risk, and prerequisites.

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
- `workflows.py` — behavioral workflow candidate discovery;
- `candidates.py` — deterministic eligibility, scoring, and sequencing;
- `store.py` — persistence/progress boundary;
- `generator_v2.py` — `RampPlanner`, the production intelligence entrypoint.

`nlp/api.py` instantiates `RampPlanner` directly.

The historical module-first intelligence implementation has been removed. The `generator.py` module is now only a compatibility import surface and contains no legacy intelligence.

---

## 7. First workflow proof

KMS has a concrete GitHub ingestion behavior that can support a backend learning outcome:

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

The current normalized workflow discovery may identify this as a GitHub-ingestion candidate from indexed implementation structure. The workflow relationship itself remains an inferred signal until source-level relationship extraction is available.

Therefore the generated learning action explicitly requires source verification and records unsupported links as unknown.

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

The next quality increase is **relationship evidence**, not more onboarding prose:

```text
indexed files/modules
       ↓
implementation relationships
       ↓
verified workflow structure
       ↓
change/history/verification evidence
       ↓
credible contribution candidates
```

Do not return to the old module-first generator or add compatibility adapters that recreate its behavior.

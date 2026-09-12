# Ramp Redesign — Engineering Onboarding Intelligence

**Status:** Accepted direction / pre-implementation design
**Branch:** `feat/ramp`
**Last updated:** 2026-09-12
**Scope:** Ramp generation and the knowledge model it depends on

## 1. Why this document exists

The first Ramp implementation proved that KMS can assemble a company-scoped, role-scoped onboarding plan with stable step identity, repository evidence, ownership signals, progress, and contextual Ask.

It also exposed a more important problem: those capabilities do not automatically produce useful onboarding.

The current generator primarily selects codebase modules/directories using importance, role-word matches, ownership, file counts, and safe/risky path heuristics, then turns those selections into prose. That is useful infrastructure, but it is not yet a sufficiently intelligent model of how a new engineer learns an unfamiliar system and reaches a first meaningful contribution.

This document freezes the redesign direction before more generator features are implemented.

## 2. The product outcome

Ramp exists to move a new engineer from:

> "I do not understand this system well enough to work safely."

to:

> "I understand the relevant part of this system well enough to make a useful change with reasonable confidence."

Therefore the quality of a Ramp must be judged by **time-to-context and readiness for meaningful contribution**, not by the number of files, modules, technologies, or onboarding steps it displays.

## 3. The central design question

The generator should answer:

> **Given everything KMS knows about a company and a new engineer's role, what is the smallest sequence of understanding and real work that gets that engineer to their first safe, meaningful contribution?**

This is the core problem. "Should a step represent a module, feature, or stack?" is a secondary implementation question.

## 4. What a Ramp is

A Ramp is an **evidence-backed progression of engineering outcomes**.

It is not:

- a directory tour;
- a list of important modules;
- a technology curriculum;
- a static checklist;
- seven arbitrary tasks;
- an LLM-generated course.

The "First 7 Days" label is a time horizon and product framing, not a requirement to create exactly seven steps.

A good Ramp should contain only as many steps as are necessary to move the engineer through the relevant learning and contribution path.

## 5. What a step means

A step is a **bounded learning/work outcome** that changes the engineer's ability to operate in the system.

A step may be centered on a feature, workflow, service, module, incident, document, change pattern, or small contribution depending on what is most useful. The underlying entity is not the unit of onboarding; the **outcome** is.

A step should answer:

1. **Objective** — What capability should the engineer gain?
2. **Why now** — Why is this the right thing to learn/do at this point?
3. **Context** — What system behavior or workflow does this illuminate?
4. **Evidence** — What customer-specific facts support the recommendation?
5. **Action** — What should the engineer actually inspect, trace, run, explain, or change?
6. **Verification** — What observable result shows the objective was achieved?
7. **Help** — Who/what can help when reliable evidence identifies it?
8. **Next transition** — What capability does this unlock?

Example progression:

**Weak:** `Learn api/handlers`

**Better:** `Trace how an incoming GitHub event becomes persisted engineering knowledge`

**Strong:** `Trace one real GitHub event from HTTP entry through validation, persistence, queueing, and NLP processing; then make a small safe change in the part owned by this role.`

The last example is not always the correct first contribution. The generator must determine what the repository actually supports rather than manufacture a task.

## 6. The onboarding progression

The default conceptual progression is:

```text
ORIENT
  ↓
BUILD MENTAL MODEL
  ↓
UNDERSTAND ROLE SURFACE
  ↓
TRACE A REAL WORKFLOW
  ↓
LEARN HOW CHANGES HAPPEN
  ↓
MAKE A SAFE CONTRIBUTION
  ↓
BECOME INDEPENDENTLY USEFUL
```

Not every Ramp needs one step for every stage. Some stages can be combined when evidence shows the engineer can cross them efficiently.

### Stage 0 — Orient

Give the minimum system map needed to stop the repository from looking like an undifferentiated tree.

Useful evidence:

- repositories;
- top-level architectural boundaries;
- services/processes;
- major domains/features;
- entry points;
- high-level ownership.

### Stage 1 — Build mental model

Explain how the relevant part of the system behaves, not just where files live.

Useful evidence:

- routes/handlers;
- calls/imports;
- queues/events;
- persistence operations;
- service boundaries;
- configuration/deployment boundaries;
- representative files/symbols.

### Stage 2 — Understand role surface

Identify the subset of system behavior the engineer is likely to touch.

Role relevance should be based on system responsibility and workflows, not merely matching words such as `backend`, `frontend`, or a technology name in a path.

### Stage 3 — Trace a real workflow

The engineer should follow a concrete system behavior end-to-end or through the most relevant bounded slice.

The generator should prefer real workflows over disconnected component tours.

### Stage 4 — Learn how changes happen

Use repository history, pull requests, tests, ownership, and existing changes when available to show how engineers actually modify this system.

This answers a crucial onboarding question that a directory tour cannot:

> "How does someone safely change this part of the system here?"

### Stage 5 — Safe contribution

Recommend a small contribution only when KMS has enough evidence to identify a bounded, low-risk change.

A contribution candidate should have:

- a clear problem or improvement target;
- bounded implementation surface;
- identifiable verification path;
- reasonable ownership/help signal;
- evidence that the area is safe enough for a new engineer.

If KMS cannot establish these, it should stop at investigation/readiness rather than invent a coding task.

## 7. The knowledge model Ramp requires

Ramp should reason over multiple layers of company knowledge:

```text
COMPANY
  ├── FEATURES / CAPABILITIES
  │     └── WORKFLOWS
  │            ├── SERVICES / MODULES
  │            │      ├── SYMBOLS
  │            │      └── FILES
  │            ├── DATA / EVENTS / QUEUES
  │            └── EXTERNAL SYSTEMS
  │
  ├── PEOPLE / OWNERSHIP
  ├── DOCUMENTATION
  ├── GIT HISTORY / COMMITS / PRs
  ├── INCIDENTS / DECISIONS / KNOWLEDGE
  └── TESTS / VERIFICATION SIGNALS
```

This does **not** mean every layer must become a new database table immediately. It is the reasoning model the implementation should work toward.

### Required distinction

A module is an implementation entity.

A feature is a user/system capability.

A workflow is behavior across one or more entities.

A stack item is a technology.

A Ramp step is an onboarding outcome that may reference any combination of those entities.

Confusing these levels is the main reason the current generator produces directory-oriented onboarding.

## 8. Generation pipeline

The target architecture is:

```text
KMS COMPANY KNOWLEDGE
        ↓
STRUCTURAL EXTRACTION
        ↓
IMPLEMENTATION RELATIONSHIPS
        ↓
FEATURE / WORKFLOW INFERENCE
        ↓
ROLE RELEVANCE
        ↓
LEARNING / CONTRIBUTION CANDIDATES
        ↓
SEQUENCE + DEPENDENCY REASONING
        ↓
EVIDENCE CHECK
        ↓
RAMP STEPS
        ↓
LLM PRESENTATION / EXPLANATION
```

### 8.1 Structural extraction

Deterministically collect facts KMS can verify:

- repositories;
- directories/modules;
- files;
- languages/frameworks;
- routes/handlers;
- classes/functions where extraction supports them;
- imports/calls/interfaces where extraction supports them;
- database access;
- queues/events;
- tests;
- configuration and entry points.

### 8.2 Implementation relationships

Connect the structural facts into useful implementation paths.

Examples:

```text
route → handler → service → database
handler → event → queue → consumer
component → API client → endpoint
feature → multiple modules/files
```

The generator should not infer these relationships from directory names when actual code evidence can establish them.

### 8.3 Feature/workflow inference

Identify meaningful capabilities and behaviors from implementation evidence, documentation, history, and existing knowledge.

A feature/workflow candidate should cite the implementation that supports it.

The system must be allowed to say:

> "I can identify these components, but I cannot reliably infer a complete workflow."

That is preferable to a confident but fabricated workflow.

### 8.4 Role relevance

Rank capabilities/workflows based on the role's likely responsibilities.

Signals may include:

- role-to-component relationships;
- ownership;
- recent changes by relevant engineers;
- APIs/routes/components associated with the role;
- dependency position in important workflows;
- tests and change history;
- explicit organizational context when available.

Simple keyword matching can be one signal, but never the complete role model.

### 8.5 Candidate generation

Generate candidate learning and contribution outcomes from the knowledge model.

Candidates should be evaluated on:

- relevance;
- prerequisite value;
- evidence strength;
- risk;
- expected learning value;
- contribution potential;
- ownership/help availability;
- verification availability.

### 8.6 Sequence reasoning

Select a small sequence whose prerequisites make sense.

The generator should prefer:

```text
high learning value
+ high role relevance
+ strong evidence
+ low unnecessary cognitive load
+ increasing contribution readiness
```

over maximum coverage.

### 8.7 Evidence gate

Every important claim in the final Ramp must be traceable to company evidence.

Generated prose can summarize or explain evidence. It must not silently upgrade inference into fact.

## 9. Intelligence boundary: deterministic system + LLM

The existing deterministic-generation decision remains correct, but its scope must be interpreted properly.

Determinism should own:

- entity selection;
- evidence retrieval;
- relationship construction where mechanically derivable;
- stable identity;
- risk/verification signals;
- candidate scoring;
- traceability.

LLM reasoning can own:

- synthesizing explanations from evidence;
- comparing candidate learning paths;
- expressing tradeoffs;
- turning verified relationships into readable learning objectives;
- identifying uncertainty;
- proposing sequence alternatives **only within evidence-backed candidates**.

The LLM must not become the source of company facts.

## 10. First-contribution design

First contribution is a target outcome, not a mandatory generated coding task.

A contribution candidate should be generated only when KMS can establish enough of the following:

| Signal | Purpose |
|---|---|
| Relevant surface | Confirms the area matters to the engineer's role |
| Concrete change target | Prevents vague "improve X" tasks |
| Existing implementation evidence | Shows where/how the change belongs |
| Tests or verification path | Gives the engineer a safe feedback loop |
| Ownership/help signal | Gives a credible escalation path |
| Low/known risk | Avoids throwing a new hire into critical paths |
| Recent change/history evidence | Shows how similar changes are made |

If the evidence is insufficient, the Ramp should end in **readiness**, not fabricate a first contribution.

## 11. What should happen to the current generator

Do not incrementally decorate the current directory-selection algorithm with more prose fields.

Instead:

1. Preserve the current stable plan/step contract where doing so avoids unnecessary UI churn.
2. Introduce a richer internal candidate/evidence model behind that contract.
3. Replace directory-first selection with outcome-first candidate generation.
4. Add real implementation/workflow signals incrementally.
5. Keep existing evidence-grounding, company scoping, ownership, stable IDs, progress, and Ask capabilities.
6. Retire path-name heuristics when stronger evidence can replace them.

The existing generator is therefore treated as a **foundation/prototype**, not as the conceptual model to optimize indefinitely.

## 12. What not to build yet

Do not begin by building:

- a giant autonomous codebase agent;
- a complete AST compiler/indexer for every language;
- a new knowledge-graph schema for every possible entity;
- a generic agentic planner;
- autonomous code changes;
- complex contribution task tracking;
- a large analytics platform.

The first redesign implementation should prove that richer reasoning produces materially better Ramp candidates on a real repository.

## 13. The next execution phase

The next phase is **Ramp Intelligence Discovery**, not another UI or persistence batch.

### RID-01 — Define the target evidence model

Write down the minimum internal objects/signals needed to represent:

- capability/feature;
- workflow;
- implementation surface;
- ownership;
- history;
- risk;
- verification;
- candidate learning outcome;
- candidate contribution.

### RID-02 — Map current KMS evidence to the model

For each target signal, identify what KMS already has, what is reliable, and what is missing.

### RID-03 — Build one real end-to-end example

Use the KMS repository itself as the first test case. Manually demonstrate how the system should go from repository evidence to:

```text
feature → workflow → implementation → role relevance → learning outcome → contribution candidate
```

If the chain cannot be established from available evidence, document exactly which missing extraction or knowledge signal blocks it.

### RID-04 — Define candidate scoring and sequence rules

Specify the minimum deterministic scoring model before implementation.

### RID-05 — Define a narrow implementation slice

Choose the smallest generator change that can prove the new model is better than the current module-first generator.

### RID-06 — Create a before/after evaluation fixture

For the same company and role, compare old and redesigned output using explicit criteria:

- meaningfulness;
- role relevance;
- workflow coherence;
- evidence strength;
- actionability;
- contribution readiness;
- unsupported claims;
- cognitive load.

No broad refactor should begin until this fixture can expose whether the redesign actually improves output.

## 14. Acceptance bar for the redesign

The redesign is not successful because the generated prose sounds smarter.

A redesigned Ramp must demonstrate that:

1. steps represent meaningful engineering outcomes rather than directory locations;
2. at least one step can explain a real system behavior/workflow using evidence;
3. role relevance changes the selected path materially;
4. repository files are supporting evidence, not the primary conceptual unit;
5. the path has a clear progression toward contribution/readiness;
6. a contribution candidate is only proposed when its evidence and verification path are sufficient;
7. weak evidence causes qualification or abstention rather than invention;
8. the same company knowledge can support different Ramps for different roles.

## 15. Product test

Before declaring the new generator customer-ready, give the resulting Ramp to someone who did not build KMS and ask them to use it against an unfamiliar repository.

Observe:

- where they hesitate;
- what they ignore;
- whether they can explain the system behavior after a step;
- whether they can find the relevant code;
- whether they can identify what to do next without asking a senior engineer;
- whether the first proposed contribution is actually understandable and appropriately scoped.

The final test is behavior, not generated text quality.

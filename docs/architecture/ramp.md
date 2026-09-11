# Ramp Architecture

**Status:** Redesign in progress
**Branch:** `feat/ramp`
**Last updated:** 2026-09-12

## Purpose

Ramp is the current customer-facing wedge for KMS. Its purpose is to move a new engineer from unfamiliarity with a customer's engineering system toward safe, meaningful contribution.

The First 7 Days framing is a time horizon, not a requirement to generate seven arbitrary steps.

## Current implementation baseline

`RampPlanGenerator` currently builds a deterministic plan from company-scoped Visualizer/codebase signals and ownership signals. The existing implementation can resolve repository/file evidence, stable step identity, role-aware prioritization, risk signals, progress, and contextual Ask.

The current generator is nevertheless **module-first**: it primarily ranks modules/directories and turns those selections into onboarding prose. This is now treated as a prototype/foundation rather than the target intelligence model.

## Target generation architecture

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

### Knowledge layers

1. **Structure** — repositories, modules, files, languages, entry points.
2. **Implementation** — routes, handlers, functions/classes, imports/calls, interfaces, database operations, queues/events, tests.
3. **Behavior** — workflows and data flows across implementation boundaries.
4. **Capabilities** — features/domains linked to the implementation that provides them.
5. **Human context** — owners, contributors, history, PRs, documentation, decisions, incidents, and other connected engineering knowledge.
6. **Contribution signals** — bounded change opportunities with evidence and verification paths.

## Step model

A step is a **bounded learning/work outcome**, not a repository location.

A step may reference a feature, workflow, service, module, file, document, historical change, or contribution candidate. Those are evidence/entities; the onboarding unit is the capability the engineer gains.

Every meaningful step should expose:

- objective;
- why now;
- relevant system/workflow context;
- supporting evidence;
- concrete action;
- verification / done-when;
- credible help/ownership where available;
- transition to the next capability.

## Onboarding progression

The default conceptual progression is:

```text
Orient → Build mental model → Understand role surface
      → Trace real workflow → Learn how changes happen
      → Make safe contribution → Become independently useful
```

The generator may combine or omit stages when evidence shows that doing so reduces unnecessary cognitive load.

## Determinism and LLM responsibilities

Deterministic logic owns company facts, evidence selection, relationship extraction where mechanically derivable, stable identity, risk/verification signals, and traceability.

LLM reasoning may synthesize explanations, compare evidence-backed candidates, express tradeoffs, and formulate readable objectives. It must not invent people, files, ownership, system behavior, or contribution tasks unsupported by company evidence.

Determinism is a trust mechanism, not the product outcome.

## First-contribution rule

A first contribution is a target outcome, not a mandatory generated coding task. KMS may recommend a contribution only when the relevant surface, concrete change target, implementation evidence, verification path, risk, and reasonable ownership/help signals are sufficient.

If evidence is insufficient, Ramp should stop at investigation/readiness rather than fabricate a coding task.

## Migration strategy

Do not keep decorating the module-first generator with additional prose fields. Preserve useful existing contracts where possible, but introduce a richer internal candidate/evidence model and replace directory-first selection incrementally.

Existing stable IDs, company scoping, evidence grounding, progress, and contextual Ask should be retained unless the redesigned product model requires a deliberate contract change.

## Current next phase

**Ramp Intelligence Discovery (RID)** is the active phase. No further generator implementation should begin until the target evidence model, current evidence inventory, real KMS example, candidate scoring rules, and before/after evaluation fixture are documented.

See `docs/product/ramp-redesign.md` for the detailed design and execution plan.

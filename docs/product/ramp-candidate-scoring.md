# Ramp Candidate Scoring and Sequencing

**Status:** RID-04 accepted / implementation not started  
**Branch:** `feat/ramp`  
**Last updated:** 2026-09-12  
**Scope:** Deterministic ranking, sequencing, and contribution eligibility for Ramp candidates

## 1. Purpose

Ramp needs to choose **outcomes**, not modules, and it must be able to explain why one outcome was selected before another.

This document defines the first deterministic selection model over the evidence and candidate objects defined in `docs/product/ramp-intelligence-model.md`.

The model is deliberately simple. It is a ranking and gating system, not a general-purpose planner or autonomous agent.

## 2. Candidate types

Ramp works with two candidate classes:

1. **Learning candidates** — bounded outcomes that improve the engineer's understanding or operating ability.
2. **Contribution candidates** — bounded real changes an engineer may safely attempt.

A contribution candidate is also a learning candidate, but the reverse is not true.

Therefore the generator may produce a useful Ramp with zero contribution candidates.

## 3. Hard eligibility gates

Scoring must never rescue an ineligible candidate.

### 3.1 Learning candidate eligibility

A learning candidate requires:

- at least one company-scoped evidence reference;
- at least one implementation, capability, or workflow reference;
- a concrete action;
- an observable verification method, or an explicit `unknown` verification state;
- no company fact that depends solely on unsupported inference.

If these conditions fail, discard the candidate rather than improving its prose.

### 3.2 Contribution candidate eligibility

A contribution candidate must pass **all** of these gates:

```text
company scope
+ concrete bounded problem/improvement
+ exact implementation surface
+ expected change is understandable
+ verification path exists
+ risk is low or explicitly known/controlled
+ credible help/ownership signal exists
+ sufficient history/change evidence OR another direct company signal supporting the opportunity
```

If any required gate is missing, the candidate is `not_qualified`.

`inferred` evidence alone can never qualify a contribution.

### 3.3 Risk is a gate, not a score booster

High or unknown-risk surfaces must not become recommended first contributions merely because they score highly on relevance.

Risk can be refined later, but the first implementation should be conservative:

- `low` → eligible if all other contribution gates pass;
- `medium` → not a first-contribution candidate unless explicitly marked safe by stronger evidence;
- `high` → not eligible for first contribution;
- `unknown` → not eligible for first contribution.

## 4. Learning candidate score

For eligible learning candidates, calculate a deterministic score from 0–100:

| Dimension | Weight | Meaning |
|---|---:|---|
| Role relevance | 25 | How directly this outcome serves the engineer's role/responsibilities. |
| Prerequisite value | 20 | How much this unlocks later understanding or work. |
| Evidence strength | 20 | Quality and traceability of supporting evidence. |
| Workflow/system value | 15 | Whether it teaches real behavior across meaningful boundaries. |
| Actionability | 10 | Whether the engineer can perform a bounded, concrete action. |
| Verification | 5 | Strength of the observable done-when condition. |
| Help availability | 5 | Whether credible ownership/help is available. |

### 4.1 Evidence scoring

Evidence strength should be calculated from the strongest supporting evidence while rewarding multiple independent sources.

Initial deterministic mapping:

```text
direct    = 1.00
derived   = 0.80
inferred  = 0.40
missing   = 0.00
```

For a candidate with multiple evidence items, do not simply sum them. Use the strongest item plus a bounded corroboration bonus so duplicate evidence cannot dominate the ranking.

A practical first rule:

```text
base = strongest evidence level
corroboration = up to +0.20 from independent evidence sources
final = min(1.00, base + corroboration)
```

The implementation may use a simpler equivalent calculation as long as the behavior is deterministic and tested.

### 4.2 Role relevance scoring

Use signals in this order of trust:

1. explicit organizational/role relationship;
2. ownership or maintained responsibility;
3. historical changes by people performing the relevant role;
4. implementation position in a role-relevant workflow;
5. explicit API/component/service responsibility;
6. technology/path keyword hints.

Keyword matches are weak evidence and must not dominate the score.

### 4.3 Prerequisite value

A candidate receives high prerequisite value when completing it unlocks multiple later candidates or reduces uncertainty required by later steps.

Examples:

- understanding the event flow before changing event processing;
- understanding an API boundary before modifying its service behavior;
- learning the test/verification path before attempting a change.

A candidate that is merely important but unlocks nothing should not receive a prerequisite bonus.

### 4.4 Workflow/system value

Prefer outcomes that explain behavior over outcomes that enumerate locations.

Examples:

```text
Weak:   Learn api/services
Strong: Trace a GitHub event through validation, persistence, and queue publication
```

A candidate spanning a real workflow boundary receives more value than a candidate limited to an isolated directory, all else equal.

## 5. Contribution readiness score

After a candidate passes the hard eligibility gates, calculate a separate readiness score. This score determines which qualified contribution is preferred; it does not make an ineligible candidate eligible.

Initial 0–100 dimensions:

| Dimension | Weight | Meaning |
|---|---:|---|
| Boundedness | 25 | Small, clearly scoped change surface. |
| Verification strength | 20 | Existing reliable way to prove the change works. |
| Evidence strength | 20 | Direct/derived evidence supporting the opportunity. |
| Role relevance | 15 | Fit for the engineer's responsibilities. |
| History/change precedent | 10 | Existing company precedent for modifying this area. |
| Help/ownership | 5 | Credible person/team to unblock the engineer. |
| Risk | 5 | Low/controlled operational risk. |

A first contribution should normally require a readiness score of at least **70/100** after all hard gates pass.

The threshold is an MVP safety control, not a scientifically calibrated number. It must be evaluated with real examples.

## 6. Sequence construction

Do not sort all candidates by score and take the top seven.

Instead, construct a sequence using prerequisite relationships and stage progression.

### 6.1 Candidate dependency graph

Represent explicit prerequisites as directed edges:

```text
candidate A → candidate B
```

meaning A should normally occur before B.

The graph should be acyclic for the first implementation. If a cycle is detected, break it conservatively by choosing the candidate with stronger prerequisite independence and record the broken dependency rather than looping.

### 6.2 Stage constraints

Use the Ramp progression as a soft ordering prior:

```text
ORIENT
  → MENTAL_MODEL
  → ROLE_SURFACE
  → WORKFLOW
  → CHANGE_MODEL
  → CONTRIBUTION
```

Stages are not mandatory seven steps. A candidate may satisfy multiple stages.

A later-stage candidate can be selected early only when its prerequisites are already satisfied by evidence or earlier candidates.

### 6.3 Selection algorithm

Initial algorithm:

1. Generate eligible candidates.
2. Remove candidates whose evidence is insufficient for their candidate type.
3. Assign each candidate its deterministic score and stage.
4. Establish explicit prerequisite edges.
5. Select the highest-scoring candidate among those whose prerequisites are satisfied.
6. After selecting a candidate, mark its unlocked prerequisites/capabilities as satisfied.
7. Penalize candidates that substantially duplicate already-selected learning value.
8. Continue until the target sequence has enough meaningful outcomes or no useful eligible candidate remains.
9. Prefer a shorter sequence over filler.
10. If a qualified contribution candidate becomes available, prefer it after the engineer has enough relevant prerequisite context.

### 6.4 Diversity / redundancy rule

A Ramp should not contain three candidates that all teach the same surface from slightly different wording.

For the first implementation, candidates sharing the same primary workflow/implementation surface should receive a bounded redundancy penalty after one representative outcome has been selected.

Do not use semantic embeddings for this initially. Stable references and explicit workflow IDs are sufficient.

## 7. Recommended first-Ramp composition

The generator should try to cover the following progression rather than an arbitrary count:

```text
1. One orientation / mental-model outcome
2. One role-relevant system outcome
3. One real workflow trace
4. One change/verification outcome when evidence exists
5. One contribution candidate when qualified
```

Additional outcomes are justified only when they unlock something meaningful.

This means a high-quality Ramp may contain 4 steps rather than 7. The "First 7 Days" name describes the onboarding horizon, not a quota.

## 8. Contribution transition rule

The preferred path is:

```text
understand → trace → learn change pattern → contribute
```

But the transition is evidence-gated.

For example, the KMS GitHub ingestion proof currently supports:

```text
workflow understanding = qualified
first contribution       = not qualified
```

That is the correct result because the repository source establishes behavior but the current integrated candidate evidence does not yet establish a safe bounded change.

## 9. Explainability contract

Every selected candidate must retain a machine-readable reason containing:

```text
candidate_id
score
score_breakdown
stage
prerequisites
satisfied_prerequisites
evidence_refs
eligibility_status
selection_reason
```

The user-facing explanation may be generated/polished later, but the underlying selection reason must be deterministic.

Example:

```text
Selected workflow candidate W1 because:
- role relevance: 0.90
- evidence: 1.00
- prerequisite value: 0.95
- workflow value: 1.00
- no prerequisite blockers
- unlocks change-model candidate C1
```

## 10. What the LLM may and may not do

### Allowed

- turn deterministic candidate facts into readable objectives;
- explain why the candidate matters;
- compare two evidence-backed candidates when deterministic scores are close;
- improve wording without changing facts or references.

### Not allowed

- invent candidates from absent evidence;
- assign ownership unsupported by evidence;
- create workflows from prose alone when implementation evidence contradicts it;
- override contribution eligibility;
- change score inputs or prerequisite facts;
- select a high-risk contribution because it sounds useful.

The deterministic model remains authoritative.

## 11. KMS proof under RID-04

For the existing GitHub ingestion example:

### Candidate A — Trace GitHub ingestion

Expected result: **eligible learning candidate**.

Approximate reasoning:

- role relevance: high for backend;
- prerequisite value: high;
- evidence: direct/derived and multi-file;
- workflow value: high because it crosses HTTP → persistence → queue boundaries;
- actionability: high;
- verification: explain the observed chain and failure/duplicate boundaries;
- help: available when ownership is present.

This candidate should rank highly.

### Candidate B — "Improve GitHub validation"

Expected result: **not qualified as a contribution**.

Reason:

- no concrete bounded defect/improvement established;
- no verified change target;
- no history/change precedent supplied to the candidate;
- no contribution-specific verification path established.

The system must not convert a high-level engineering idea into a contribution merely because it sounds plausible.

## 12. Implementation boundary for RID-05

RID-04 intentionally does **not** require replacing the whole generator.

The smallest implementation target should be:

```text
existing KMS evidence
      ↓
small internal candidate objects
      ↓
eligibility gates
      ↓
score + prerequisite sequence
      ↓
one real workflow candidate
      ↓
existing Ramp step serializer
```

The existing persistence/API/frontend contracts should be preserved where possible.

The first implementation should prove that the new candidate model can produce a workflow-oriented step for the GitHub ingestion example without requiring a universal code intelligence system.

## 13. Acceptance criteria

RID-04 is accepted when:

1. Learning and contribution candidates have explicit hard eligibility gates.
2. Candidate ranking is deterministic and explainable.
3. Role relevance does not depend primarily on path keywords.
4. Prerequisites influence ordering.
5. Workflow outcomes outrank disconnected module tours when evidence is comparable.
6. Redundant candidates are penalized.
7. Contribution eligibility is a gate, not a high score.
8. Risk can prevent a first contribution regardless of relevance score.
9. The sequence can stop early when no meaningful candidate remains.
10. Every selected candidate retains evidence and selection metadata.
11. The KMS GitHub ingestion proof ranks as a strong learning candidate but does not falsely qualify an unsupported contribution.

## 14. Decisions and open calibration questions

### Accepted decisions

- 0–100 deterministic scoring is sufficient for the first implementation.
- Hard gates precede scoring.
- Contribution readiness is separate from learning relevance.
- Prerequisite-aware sequence beats global top-N ranking.
- Shorter meaningful Ramps beat seven-step filler.
- LLM is presentation/reasoning assistance, not the source of company facts.

### To calibrate with evaluation

- exact score weights;
- 70 contribution threshold;
- redundancy penalty magnitude;
- number of candidates evaluated before sequence construction;
- whether explicit stage quotas improve or distort quality.

These are implementation parameters, not permanent product truths.

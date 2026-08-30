# Ramp — Customer Workflow PRD

**Status:** Active product specification  
**Branch baseline:** `feat/ramp`  
**Scope:** First customer-facing KMS workflow to validate the product  
**Last updated:** 2026-08-31

## 1. Purpose

Ramp is the first customer-facing wedge of KMS. Its job is to reduce the time and senior-engineer effort required for a new engineer to understand an unfamiliar codebase and begin doing meaningful work.

The product must use the customer's own engineering context—code, ownership, architecture, and accumulated knowledge—to produce guidance that a generic AI assistant or static onboarding checklist could not reliably produce.

This document is the durable product contract for the Ramp feature. Future implementation work should be checked against it. If implementation, architecture, or another conversation contradicts this document, the contradiction must be made explicit and resolved rather than silently changing the product direction.

## 2. Problem

When an engineer joins an existing engineering team, the difficult part is not receiving a generic list of onboarding tasks. The difficult part is discovering how the real system works:

- Which services and areas matter to their role?
- Where should they start in a large unfamiliar repository?
- Why are particular components important?
- Who actually owns or understands them?
- Which documentation and code paths are trustworthy?
- What should they investigate or do first?
- When are they sufficiently oriented to begin meaningful work?

Existing onboarding commonly depends on scattered documentation, tribal knowledge, and repeated interruptions of senior engineers. KMS should turn the organization's existing engineering context into a practical path through that complexity.

## 3. Product hypothesis

> If KMS understands a company's engineering context and turns it into an evidence-backed, role-specific first-week path, a new engineer can reach useful context and meaningful contribution faster while requiring less repeated assistance from senior engineers.

This is a hypothesis, not a proven claim. The first version exists to test it with real engineers and real repositories.

## 4. Primary users

### Primary beneficiary — New engineer

A software engineer joining an existing team who needs to understand an unfamiliar system quickly enough to contribute.

Their desired outcome is not "finish onboarding." It is:

> "I understand enough of this system to start doing useful work without constantly asking someone where everything is."

### Primary operator / buyer candidate — Engineering manager or team lead

The person responsible for getting new engineers productive and absorbing the cost of onboarding.

Their desired outcome is:

> "My new engineer becomes productive faster without consuming disproportionate senior-engineer time."

The exact economic buyer remains a validation question.

## 5. Core customer workflow

```text
Company connects engineering knowledge sources
                    ↓
             KMS builds context
                    ↓
       Manager starts a new engineer Ramp
                    ↓
          Select role / context
                    ↓
       KMS generates First 7 Days path
                    ↓
         Engineer opens the Ramp
                    ↓
       Engineer works through steps
                    ↓
 Each step provides context + evidence + action
                    ↓
      Engineer completes / skips / asks
                    ↓
        KMS captures useful feedback
                    ↓
     Measure whether onboarding improved
```

The workflow is successful only if it produces a meaningful improvement for the engineer or the team. Generating attractive plans is not the product outcome.

## 6. What a Ramp must provide

A generated Ramp should be role-specific and grounded in the customer's actual engineering context.

Each important step should help answer:

1. **Where am I?** — What part of the system is this?
2. **What is it?** — What does the component/service/domain do?
3. **Why does it matter?** — Why should this engineer understand it now?
4. **Where should I look?** — Which repository files, modules, documents, or other evidence support the recommendation?
5. **What should I do?** — What concrete investigation or action should the engineer take?
6. **Who can help?** — Who or what is associated with this area when reliable ownership information exists?
7. **How do I know I'm done?** — What observable outcome indicates that the step has been completed successfully?

The exact UI can evolve, but the underlying user value must remain.

## 7. Evidence and trust requirements

Ramp recommendations must be grounded in customer-specific evidence wherever possible.

Useful evidence may include:

- Repository structure and source files
- Module/service relationships
- Ownership signals
- Git history and contributors
- Existing knowledge-graph relationships
- Relevant internal documentation when available
- Other connected engineering context supported by KMS

LLMs may improve explanations and presentation, but generated claims must not be presented as company facts when KMS has no supporting evidence.

A user should be able to understand **why KMS recommended a step** and inspect the supporting evidence where appropriate.

## 8. MVP scope

### Must have

- Company-scoped Ramp
- Role-specific Ramp generation
- Evidence-backed recommendations from available KMS context
- A coherent First 7 Days sequence
- Step-level workspace/detail experience
- Stable step identity suitable for deep links
- Clear resources/evidence associated with recommendations
- Concrete checklist/action for each meaningful step
- Completion state for steps
- Basic user feedback sufficient to learn whether recommendations are useful
- A usable end-to-end flow from generation to engineer consumption

### Should have if inexpensive

- Ability to regenerate when company context changes
- Lightweight step skip/reset behavior
- Clear distinction between verified evidence and generated explanation
- Basic progress visibility for the manager

### Explicitly out of MVP

- Generic company-wide knowledge assistant
- Full autonomous onboarding agent
- Complex workflow/orchestration platform
- Comprehensive HR onboarding
- Deep project-management functionality
- Broad RAG/chat product unrelated to the Ramp workflow
- Large-scale analytics platform
- Premature optimization for every possible GitHub event or repository edge case

Reliability work should support the customer workflow but must not become an independent product phase unless a reliability defect directly blocks real customer use.

## 9. Non-goals

Ramp is **not**:

- A prettier checklist generator
- A generic ChatGPT wrapper
- A replacement for an engineer's manager or teammates
- A guarantee that an engineer becomes productive in seven days
- A complete documentation replacement
- A static course about software engineering

The differentiation must come from understanding the customer's actual engineering environment.

## 10. User experience principles

### Evidence over eloquence

A shorter recommendation backed by strong evidence is better than a sophisticated paragraph containing unsupported claims.

### Action over information overload

Every step should move the engineer toward understanding or contribution. Avoid dumping repository information merely because it is available.

### Progressive context

Give the engineer enough context to understand the current step, then provide paths to deeper evidence rather than presenting the entire knowledge graph at once.

### Honest uncertainty

If KMS is uncertain, say so. Do not manufacture owners, architectural relationships, rationale, or confidence.

### Role relevance

The same repository should produce different priorities for different roles. A backend engineer and a frontend engineer should not receive the same Ramp with superficial wording changes.

### Fast path to meaningful work

The goal is not maximum onboarding coverage. The goal is useful context with the minimum unnecessary cognitive load.

## 11. Success criteria

The first validation should answer whether Ramp creates customer value, not whether the implementation is technically sophisticated.

### Primary validation question

> Does Ramp help a real engineer understand an unfamiliar codebase and begin meaningful work faster than the team's normal onboarding process?

### Product signals

Track at minimum:

- Ramp generation completion rate
- Ramp open/start rate
- Step view rate
- Step completion rate
- Step skip rate
- Evidence/resource interaction rate
- User-reported usefulness
- User-reported trust/confidence
- Time from Ramp start to meaningful first task
- Amount of help required from teammates, where measurable

These are instrumentation signals, not proof of product-market fit.

### Stronger eventual business metric

The long-term metric to pursue is reduction in **time and senior-engineer effort required to get a new engineer productive**.

## 12. Acceptance criteria for the first customer-ready slice

A real customer test should be possible without manual intervention from the development team after initial setup:

1. A company has usable engineering context connected to KMS.
2. A manager can start a Ramp for a real role.
3. KMS generates a role-specific First 7 Days path.
4. The engineer can open the path and navigate individual steps.
5. Steps contain concrete actions and customer-specific supporting evidence.
6. The engineer can record meaningful progress/feedback.
7. The system does not knowingly present unsupported generated claims as facts.
8. The team can observe enough usage data to compare the workflow against existing onboarding.

## 13. Current implementation baseline

The current `feat/ramp` implementation already provides the foundation for this workflow:

- Company/role-scoped Ramp plans
- `RampPlanGenerator`
- Structured steps with fields including title, rationale, risk tier, owners, target, summary, resources, checklist, evidence, machine data, and overrides
- Stable step identity intended for workspace/deep-link use
- Frontend Ramp workspace and role-scoped routes
- Existing codebase/ownership signals used during generation

These existing capabilities are implementation facts, not reasons to preserve weak behavior. The implementation should be changed when required to satisfy this PRD.

## 14. Product-quality bar

Before calling the first Ramp slice customer-ready, we should be able to put it in front of an engineer who did not build KMS and observe them using it on a real unfamiliar repository.

The test should expose weaknesses such as:

- Generic recommendations
- Incorrect or stale evidence
- Missing context
- Poor prioritization
- Unclear actions
- Lack of trust
- Excessive cognitive load
- Steps that do not help the engineer perform real work

We should prefer discovering these failures through real usage over adding speculative features.

## 15. Decision rules for future work

When deciding whether to implement a proposed feature, ask:

1. Does it directly improve the engineer's path from unfamiliarity to meaningful contribution?
2. Does it improve evidence quality, relevance, trust, actionability, or measurement?
3. Is the problem observed or strongly implied by actual customer testing?
4. Can we solve it without introducing disproportionate complexity?
5. Does it preserve the central differentiation: company-specific engineering context?

If the answer is mostly no, defer it.

## 16. Open questions to validate

These must remain hypotheses until tested:

- Who pays: engineering manager, CTO, engineering organization, or another buyer?
- How painful is onboarding relative to other engineering problems?
- Which company size/team structure feels the pain most strongly?
- Which evidence sources produce the largest improvement in recommendation quality?
- How much trust do engineers place in AI-generated onboarding guidance?
- What makes a step genuinely useful rather than merely informative?
- Is seven days the right framing, or simply a useful initial product boundary?
- What measurable amount of time/senior-engineer effort can KMS save?

## 17. Relationship to other documentation

- `docs/product/vision.md` — broader KMS product direction
- `docs/product/personas.md` — broader user/persona context
- `docs/product/metrics.md` — product measurement context
- `docs/architecture/ramp.md` — technical architecture of the current Ramp implementation

This PRD defines the **customer outcome and product scope**. `docs/architecture/ramp.md` defines how the current system implements it. Neither should silently replace the other.

## 18. Change control

This document is intentionally version-controlled.

If a future conversation, agent, or implementation proposes changing the core Ramp workflow, update this PRD in the same development cycle and explain the reason. Do not allow product direction to drift through incremental coding decisions.

**Current product wedge:** Make Ramp genuinely useful to a new engineer entering an unfamiliar engineering codebase, prove that it reduces time-to-context and onboarding effort, then expand from evidence gained in real customer use.
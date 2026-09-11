# ADR-003: Deterministic Ramp Generation

## Status
Accepted, with scope clarified 2026-09-12

## Context

An onboarding plan must be useful because it reflects the customer's actual engineering environment, not because an LLM invents a plausible checklist.

The first implementation correctly protected structural facts, but deterministic selection was too closely tied to repository modules/directories. That produced predictable plans without producing sufficiently intelligent onboarding.

## Decision

Ramp remains **evidence-first and deterministic at the fact/evidence layer**, but the onboarding unit is not a module.

Deterministic logic should establish:

- company-scoped evidence;
- implementation entities and mechanically derivable relationships;
- feature/workflow evidence where supported;
- ownership/history/risk/verification signals;
- candidate learning/contribution outcomes;
- stable identity and traceability.

LLM reasoning may synthesize and compare evidence-backed candidates and explain the resulting path, but it must not invent people, files, ownership, workflows, or contribution tasks.

Ramp steps represent bounded learning/work outcomes. A step may reference modules, files, features, workflows, technologies, documents, or historical changes as evidence.

Stable step IDs remain required for UI/deep-link continuity.

## Consequences

The generator can remain predictable and auditable while becoming substantially more useful than a directory tour. The system can evolve from module-first selection toward feature/workflow/contribution reasoning without turning the LLM into the source of truth.

This requires richer implementation evidence and candidate modeling. It does **not** require immediately building a universal autonomous codebase agent or a complete multi-language semantic compiler.

## Product constraint

Determinism is a means to trustworthiness, not the product itself. The redesigned Ramp must be evaluated by whether it improves an engineer's path from unfamiliarity to meaningful contribution.

## Related documentation

- `docs/product/ramp-prd.md` — customer outcome and product contract
- `docs/product/ramp-redesign.md` — target intelligence model and execution plan
- `docs/architecture/ramp.md` — technical architecture and migration strategy

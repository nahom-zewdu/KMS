# ADR-004: Import Edges Are Structural, Not Workflow Proof

## Status
Accepted, 2026-09-21

## Context

On `feat/implementation-relations`, KMS extracts Python and Go import statements, resolves them against the indexed file inventory, and persists `IMPORTS` edges. `WorkflowDiscoverer` then enumerates bounded directed paths over those edges and emits Ramp workflow *candidates*.

ADR-003 remains in force: facts and selection stay deterministic; the LLM is not the source of company truth. This record clarifies what an import fact is allowed to mean.

A live read-only evaluation (`docs/product/ramp-candidate-evaluation-2026-09-20.md`) found that every supporting signal for the sampled candidates was a direct `IMPORTS` edge. No candidate met the bar for a confirmed recognizable responsibility. Shared leaves (`api/domain/domain.go`, NLP utilities) produced many short paths that explain dependency, not behavior.

## Decision

Treat a resolved `IMPORTS` edge as a **direct structural fact**: file A names file/package B as a dependency.

Do **not** treat that edge, or a path of such edges, as proof of:

- runtime execution order;
- a business or user-facing workflow;
- ownership or role responsibility;
- a safe change surface;
- onboarding usefulness.

Ramp may use import paths as **candidate exploration material**. User-facing copy and evidence strength must describe the import relationship honestly. Workflow confidence derived from import confidence describes the imports, not a verified control/data flow.

Do not add further import-path ranking heuristics until at least one independent behavioral signal (route, call, queue, persistence, or test) can corroborate or reject a candidate. Prefer abstention over a confident fabricated workflow.

## Consequences

Indexer precision stays high: unresolved and external imports are dropped rather than stored as inferred architecture.

Candidate volume and redundancy (shared-leaf fan-in) are expected until corroborating evidence exists. That is an evidence gap, not a presentation bug.

RID-03's GitHub ingestion chain remains a **manual** workflow proof. It is not automatically the output of `WorkflowDiscoverer`.

## Related documentation

- `docs/decisions/ADR-003-deterministic-ramp.md` — deterministic fact/selection layer
- `docs/product/ramp-intelligence-model.md` — evidence strength and candidate objects
- `docs/product/ramp-candidate-evaluation-2026-09-20.md` — live import-path snapshot
- `docs/development/roadmap.md` — RID-05 status and RID-07 next task

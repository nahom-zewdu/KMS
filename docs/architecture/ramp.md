# Ramp Architecture

**Status:** Clean intelligence rewrite in progress (RID-05)
**Branch:** `feat/implementation-relations`
**Last updated:** 2026-09-21

Product contract: `docs/product/ramp-prd.md`.
Evidence/candidate semantics: `docs/product/ramp-intelligence-model.md`.
Execution status: `docs/development/roadmap.md`.

## 1. Boundary

Ramp has two separate concerns:

1. **Intelligence** — determine what a new engineer should understand/do next from company evidence.
2. **Persistence/API** — save plans, hydrate progress, and expose the existing frontend contract.

The deleted module-first generator is not part of the intelligence architecture. There is no `nlp/ramp/generator.py` on this branch.

## 2. Target architecture

```text
                    KMS KNOWLEDGE
                         │
          ┌──────────────┴──────────────┐
          │                             │
   codebase/files/modules        graph/history/docs
          │                             │
          └──────────────┬──────────────┘
                         ▼
                RampEvidenceStore
                         │
                         ▼
              normalized evidence
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
      WorkflowDiscoverer       role reasoning
              │                     │
              └──────────┬──────────┘
                         ▼
                  RampCandidate
                         │
                         ▼
               RampCandidateEngine
                 gates → score
                 prerequisites
                 sequencing
                         │
                         ▼
                    RampPlanner
                         │
                         ▼
                    RampStore
                         │
                         ▼
                  existing API/UI
```

## 3. Design rules

### Evidence owns facts

`RampEvidenceStore` reads company-scoped KMS records. It does not invent relationships or convert path names into confirmed architecture.

### Candidates own reasoning

Candidates represent bounded outcomes. A candidate may reference files/modules/import paths, but those entities are not themselves onboarding steps.

### Deterministic selection owns trust

Eligibility, risk, evidence strength, score, prerequisites, ordering, and contribution readiness are deterministic. LLM output cannot override them. `polish_why` is accepted by `POST /ramp-plans/generate` and is unused by `RampPlanner`.

### Persistence is an adapter

`RampStore` knows how to persist plans and progress. It does not know why a candidate was selected.

## 4. Current implementation

`nlp/ramp/` contains:

- `models.py` — normalized reasoning objects;
- `evidence.py` — company-scoped evidence extraction, including FILE-to-FILE graph edges;
- `workflows.py` — bounded directed-path candidate discovery;
- `candidates.py` — candidate gates/scoring/sequence;
- `store.py` — persistence/progress;
- `generator_v2.py` — `RampPlanner` orchestration.

`WorkflowDiscoverer` decomposes implementation evidence into deterministic directed
paths rather than treating each weakly connected component as one workflow. Paths
are limited to eight files and eight candidates per component; each candidate keeps
only the relationship evidence on its path. Cycles use deterministic fallback
starts, isolated surfaces are ignored, and weak-only relationships do not produce
workflow candidates.

`nlp/api.py` uses `RampPlanner` directly.

`WorkflowDiscoverer` decomposes FILE-to-FILE relations into deterministic directed paths rather than treating each weakly connected component as one workflow. Paths are limited to eight files and eight candidates per component; each candidate keeps only the relationship evidence on its path. Cycles use deterministic fallback starts, isolated surfaces are ignored, and inferred-only relationships do not produce candidates.

## 5. Current evidence boundary

Indexed `IMPORTS` edges are **direct structural facts** when extraction resolved both endpoints. They are not runtime traces.

`RampEvidenceStore.implementation_relationships()` maps FILE entity IDs to paths, skips `PART_OF` and `OWNS`, and classifies remaining edges by stored confidence (`≥ 0.8` direct, `≥ 0.6` derived, else inferred). The extractor writes `IMPORTS` at confidence `1.0`, so live import evidence is classified **direct**.

That does **not** upgrade a path into a verified workflow. See `docs/decisions/ADR-004-imports-are-not-workflows.md`.

Go imports resolve to the first sorted non-test `.go` file in the imported package. Python unresolved/external imports are omitted.

The user-facing workflow action asks the engineer to follow only observed implementation relationships, verify each boundary in source, and mark missing control/data-flow links as unknown.

This is intentional epistemic behavior, not a hidden fallback.

## 6. Contribution boundary

Ramp must not generate a first coding task merely because a file looks relevant. Contribution candidates require bounded change evidence, verification, controlled risk, credible help, and sufficient history/change precedent.

Until those signals exist, Ramp should stop at investigation/readiness.

## 7. Migration rule

Do not add new features to the former module-first generator. If a useful behavior is discovered there, reimplement the behavior against the new evidence/candidate model or deliberately discard it.

Working infrastructure—Supabase, ingestion, progress persistence, API routes, and the existing frontend workspace—is preserved because it is infrastructure, not the old Ramp reasoning model.

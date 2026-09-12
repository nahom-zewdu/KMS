# Ramp Architecture

**Status:** Clean intelligence rewrite in progress
**Branch:** `feat/ramp`
**Last updated:** 2026-09-12

## 1. Boundary

Ramp has two separate concerns:

1. **Intelligence** — determine what a new engineer should understand/do next from company evidence.
2. **Persistence/API** — save plans, hydrate progress, and expose the existing frontend contract.

The old module-first generator is not part of the intelligence architecture.

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

Candidates represent bounded outcomes. A candidate may reference files/modules/workflows, but those entities are not themselves onboarding steps.

### Deterministic selection owns trust

Eligibility, risk, evidence strength, score, prerequisites, ordering, and contribution readiness are deterministic. LLM output cannot override them.

### Persistence is an adapter

`RampStore` knows how to persist plans and progress. It does not know why a candidate was selected.

## 4. Current implementation

`nlp/ramp/` contains:

- `models.py` — normalized reasoning objects;
- `evidence.py` — company-scoped evidence extraction;
- `workflows.py` — workflow candidate discovery;
- `candidates.py` — candidate gates/scoring/sequence;
- `store.py` — persistence/progress;
- `generator_v2.py` — `RampPlanner` orchestration.

`nlp/api.py` uses `RampPlanner` directly.

`nlp/ramp/generator.py` contains no legacy intelligence; it is only a compatibility import surface. The historical `evidence_generator.py` has been removed.

## 5. Current evidence boundary

The first workflow implementation uses indexed structural evidence. For example, multiple GitHub/webhook/ingestion/Redis implementation surfaces can form a **workflow candidate**. The workflow relationship is still an inferred signal until source-level implementation relationship extraction exists.

The user-facing action therefore asks the engineer to verify the actual control/data flow in source and explicitly mark unsupported links as unknown.

This is intentional epistemic behavior, not a hidden fallback.

## 6. Contribution boundary

Ramp must not generate a first coding task merely because a file looks relevant. Contribution candidates require bounded change evidence, verification, controlled risk, credible help, and sufficient history/change precedent.

Until those signals exist, Ramp should stop at investigation/readiness.

## 7. Migration rule

Do not add new features to the former module-first generator. If a useful behavior is discovered there, reimplement the behavior against the new evidence/candidate model or deliberately discard it.

Working infrastructure—Supabase, ingestion, progress persistence, API routes, and the existing frontend workspace—is preserved because it is infrastructure, not the old Ramp reasoning model.

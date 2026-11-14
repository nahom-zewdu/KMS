# Ramp Quality Evaluation — Structural vs Behavioral Evidence

**Date:** 2026-09-22  
**Status:** VERIFIED — read-only evaluation; no production code, graph, plan, or database mutations  
**Scope:** `nahom-zewdu/KMS`, branch `feat/implementation-relations`, company `comp_1785181837594`, role `software-engineer`

## 1. Current-state diagnosis

The live `ramp_v2` plan contains **18 steps**: 1 orientation, 1 role-surface, and 16 workflow-learning steps.

The live plan metadata reports:

- 72 implementation surfaces
- 68 implementation relationships
- 68/68 current implementation relationships are `IMPORTS`
- 59 ownership signals
- 21 GitHub history records
- 18 selected candidates

The selected workflow steps are not being distinguished by human responsibility. The implementation currently turns bounded import paths into workflow candidates. The resulting paths repeatedly share prefixes and terminate at shared leaves such as `api/domain/domain.go`, `nlp/utils/supabase.py`, and `nlp/utils/logger.py`.

This is visible in the live plan itself. For example, the first several workflow steps all begin with:

```
nlp/main.py
  -> nlp/worker/processor.py
  -> nlp/worker/query.py
```

and then diverge into retrieval, synthesis, vector retrieval, or utility paths.

The current candidate model also gives these structurally different paths nearly the same high score. The workflow constructor assigns direct IMPORTS evidence a confidence of 1.0, actionability 0.9, verification strength 0.9, and a high baseline for workflow/prerequisite value. Selection then repeatedly takes the highest-scoring eligible candidate; there is no implemented semantic distinctness gate that asks whether the candidate represents a different thing worth learning.

The result is therefore not primarily a labeling problem. The system is selecting **different graph paths**, not demonstrably different onboarding outcomes.

## 2. Candidate evaluation

Scores below are the deterministic scores produced by the current workflow candidate model for the live IMPORTS candidates. Behavioral units are marked N/A because RID-07/RID-08/RID-09 evidence is still read-only and is not yet represented as production Ramp candidates.

| candidate | evidence | type | classification | human usefulness | reason |
|---|---|---|---|---|---|
| `workflow:0cbf8d57541d572e` | `nlp/main.py → processor.py → query.py → core.py → retrieval.py → analyzer.py → llm.py` | IMPORTS, 7 files, score 97.0 | **C** | Low | Long and structurally coherent, but imports do not show that one runtime query traverses this exact sequence. It ends at a generic engine boundary rather than a verified onboarding responsibility. |
| `workflow:6705a8735cb61e40` | `nlp/main.py → processor.py → query.py → core.py → retrieval.py → vector/retriever.py → llm.py` | IMPORTS, 7 files, score 97.0 | **C** | Low | Different graph path from the previous candidate, but much of the same prefix and no evidence that this is a distinct user-facing behavior. |
| `workflow:4e129c73c84eb7c4` | `nlp/main.py → processor.py → query.py → core.py → synthesizer.py → llm.py` | IMPORTS, 6 files, score 96.25 | **C** | Low | Looks like a plausible architecture trace, but static dependency does not establish execution order or a learning boundary. |
| `workflow:018e2ddf5db3da04` | `nlp/main.py → processor.py → consumer.py → utils/__init__.py → utils/common.py` | IMPORTS, 5 files, score 95.5 | **C** | Low | Terminates in shared utility code. This explains dependency structure, not an onboarding responsibility. |
| `workflow:81a4a8f864e4bd36` | `api/main.go → services/codebase.go → domain/domain.go` | IMPORTS, 3 files, score 90.2 | **C** | Low | The path resembles a service boundary but imports do not prove that `main.go` invokes the service for a particular behavior; `domain.go` is a shared leaf. |
| `workflow:6fb8c6a546bb96f3` | `api/handlers/github.go → api/domain/domain.go` | IMPORTS, 2 files, score 89.05 | **C** | Very low | This is exactly the previous failure mode: a meaningful-looking handler file collapses into a shared domain file without revealing what the handler actually does. |
| `RID09-GITHUB-ROUTE` | `POST /github → GitHubHandler.HandleGitHubWebhook` | route → handler | **A** | Medium | Establishes a real HTTP entry boundary. A new engineer can identify where GitHub webhooks enter, but downstream responsibility is still unknown. |
| `RID09-GITHUB-OP` | `POST /github → GitHubHandler.HandleGitHubWebhook → githubIngest.IngestGitHubEvent` | route → handler → direct operation | **A** | High | Names the concrete entrypoint and the next operation to inspect. The evidence is source-level and does not require interpreting filenames as behavior. |
| `RID09-BASELINE-OP` | `GET /github/sync-baseline → CodebaseHandler.SyncBaseline → codebaseService.SyncRepository` | route → handler → direct operation | **A** | High | Identifies a recognizable baseline-sync responsibility and gives a concrete next inspection target. It still stops before claiming the downstream queue behavior. |
| `RID09-SLACK-BRANCH` | `POST /slack/events → SlackHandler.HandleSlackWebhook → slackBot.HandleEvent` (mention) / `slackIngest.IngestSlackEvent` (message) | route → handler → branch-specific operations | **B** | High | This provides a meaningful exploration sequence and preserves the fact that one route branches into different behaviors. It is materially richer than a single file path. |

### Classification interpretation

The distinction is important:

- **A — Recognizable responsibility:** the evidence identifies a concrete system boundary/responsibility.
- **B — Useful onboarding path:** the evidence gives a meaningful sequence or branching path that a new engineer can use to explore behavior.
- **C — Ordinary dependency chain:** the evidence is real but does not justify treating it as a distinct onboarding unit.
- **D — Fragment / uncertain:** there is not enough evidence to determine what the candidate represents.

The current live IMPORTS candidates overwhelmingly fall into **C**. The behavioral examples move into **A/B** because they expose actual source-level entry and delegation facts.

## 3. Structural vs behavioral comparison

### IMPORTS-only

```
api/handlers/github.go
        ↓
api/domain/domain.go
```

Supports:

> github.go depends on domain.go.

Does not establish:

- an HTTP entrypoint;
- which handler method matters;
- what operation is invoked;
- runtime ordering;
- a distinct engineering responsibility.

### Route → handler

```
POST /github
        ↓
GitHubHandler.HandleGitHubWebhook
```

Supports:

> GitHub webhook requests enter through this concrete handler.

This is already a meaningful orientation boundary.

### Route → handler → direct operation

```
POST /github
        ↓
GitHubHandler.HandleGitHubWebhook
        ↓
githubIngest.IngestGitHubEvent
```

Supports:

> the concrete GitHub webhook handler directly delegates to a named ingestion operation.

It also provides a truthful next inspection target.

This is materially more actionable than the IMPORTS path because the engineer can move from an external behavior to a concrete method and then to a concrete operation.

### Richer source evidence

The source itself contains still stronger facts that the current Ramp evidence layer does not yet extract.

For example:

```
GitHub webhook
  → GitHubHandler.HandleGitHubWebhook
  → GitHubIngest.IngestGitHubEvent
  → CoreIngestService.Ingest
```

and:

```
baseline sync
  → CodebaseHandler.SyncBaseline
  → CodebaseService.SyncRepository
  → RedisStream.Publish("codebase_baseline_jobs", ...)
```

These are source observations, not current Ramp candidate evidence. The current RID-09 composer stops at the handler's direct dependency call. Therefore they should **not** be presented as already-supported production evidence.

The important finding is that there is a credible path from structural evidence toward richer behavioral evidence without requiring a general-purpose call graph.

## 4. Usefulness criteria

Use only these five criteria for the next evaluation:

1. **Recognition** — Can a new engineer state what responsibility/boundary the evidence represents?
2. **Behavioral grounding** — Does the evidence demonstrate an actual route, call, queue, persistence operation, test, or other observable behavior rather than only dependency?
3. **Distinctness** — Does this represent something materially different to learn, rather than another path through the same surfaces?
4. **Actionability** — Does it give the engineer a concrete next inspection target?
5. **Evidence sufficiency** — Is the evidence strong enough to present this as an onboarding unit without relying on filename/path interpretation?

These are evaluation criteria, not another production scoring formula.

## 5. Architecture implication

**Decision: STEER.**

The evidence does **not** support continuing to improve IMPORTS-path workflow generation as the primary source of Ramp learning units.

The current implementation has already demonstrated that:

```
different dependency paths
≠
different things worth learning
```

The behavioral evidence shows a more useful distinction:

```
route
  → handler
  → direct operation
```

can establish a recognizable implementation boundary and a concrete next inspection target.

The appropriate architecture is therefore:

```
IMPORTS
    ↓
structural evidence
    ↓
candidate context / navigation support

behavioral evidence
    ↓
route / handler / operation / queue / persistence boundaries
    ↓
candidate onboarding units
```

IMPORTS should not be deleted. It remains useful for structural context and for finding surfaces to inspect. It should simply stop being treated as sufficient evidence for a workflow-learning unit.

The current result also gives us a stronger product principle:

> **A candidate should exist because there is a defensible thing to learn, not because a graph path exists.**

## 6. Exact next implementation task

**RID-10A — Read-only behavioral candidate projection**

Do **one** narrowly bounded implementation task:

> Build a read-only projection that takes the existing RID-09 composed route → handler → direct-operation evidence and evaluates it as a candidate evidence unit, without changing the production Ramp planner, graph, database, or API contract.

### Likely files

- `nlp/ramp/evidence_composition.py`
- a new focused evaluation module under `nlp/ramp/`, if needed
- `nlp/tests/` for focused tests
- `docs/product/` for the evaluation artifact

Do **not** modify `workflows.py` or `candidates.py` in this task.

### Required behavior

For each composed behavioral boundary, expose enough information to answer:

```
What enters?
Who handles it?
What operation is directly invoked?
What should I inspect next?
What evidence supports each boundary?
```

It should support branch-specific observations such as Slack without flattening branches into one fake workflow.

### Invariants

- no graph writes;
- no Ramp-plan writes;
- no Supabase mutations;
- no interface implementation inference;
- no runtime-order claims;
- no ownership inference;
- no contribution claims;
- no new keyword heuristics;
- IMPORTS remains unchanged;
- deterministic output;
- unsupported/ambiguous relationships abstain.

### Tests required

At minimum:

- GitHub route → handler → direct operation;
- baseline route → handler → direct operation;
- Slack branch preservation;
- Query transport boundary;
- unmatched/ambiguous evidence abstention;
- deterministic ordering;
- no cross-file handler-symbol joins.

### Must NOT change

- `WorkflowDiscoverer`;
- candidate scoring;
- candidate selection;
- Ramp API contract;
- Supabase schema;
- live Ramp data;
- generated production plan;
- path length limits;
- role keyword lists.

**Decision gate after RID-10A:** stop again and compare behavioral candidate quality against the IMPORTS baseline before integrating behavioral candidates into production Ramp selection.


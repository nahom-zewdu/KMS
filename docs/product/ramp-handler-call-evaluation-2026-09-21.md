# RID-08 — Go Handler → Direct Service-Call Corroboration Evaluation

**Date:** 2026-09-21  
**Status:** IMPLEMENTED — read-only structural evaluation; repository execution pending  
**Scope:** branch `feat/implementation-relations`, repository `nahom-zewdu/KMS`  
**Mode:** source inspection only; no Supabase, graph, or Ramp-plan writes

## Objective

Determine whether explicit calls from an already-resolved HTTP handler through its declared dependency fields provide materially stronger onboarding evidence than:

1. `IMPORTS` only; and
2. route → handler evidence from RID-07.

The target evidence is deliberately narrow:

```text
POST /github
  → GitHubHandler.HandleGitHubWebhook
  → h.githubIngest.IngestGitHubEvent
```

and:

```text
GET /github/sync-baseline
  → CodebaseHandler.SyncBaseline
  → h.codebaseService.SyncRepository
```

## Method

Added a standalone `GoHandlerCallEvidenceExtractor`.

It:

- resolves a requested `HandlerType.Method` inside one Go source file;
- reads fields declared directly on that handler struct;
- records explicit `h.<field>.<method>(...)` calls inside the target method;
- preserves source order;
- reports source file and line;
- abstains if the handler struct or method cannot be resolved;
- does not resolve the concrete implementation behind an interface;
- ignores arbitrary package/function calls such as `json.Unmarshal`, `time.Now`, or `fmt.Sprintf`;
- does not build a general call graph or persist evidence.

No Ramp planner, graph indexer, Supabase data, or production behavior was changed.

## Findings

### 1. GitHub webhook

**Observed source:** `api/handlers/github.go:319`

```text
POST /github
  → GitHubHandler.HandleGitHubWebhook
  → h.githubIngest.IngestGitHubEvent(...)
```

The handler struct declares `githubIngest domain.GitHubIngestService`, and the handler directly invokes `IngestGitHubEvent`.

This is materially stronger than route evidence alone: the source now establishes a concrete operation boundary—GitHub webhook handling hands an `IngestRequest` to the GitHub ingestion service.

Still unsupported:

- the internal implementation of `GitHubIngestService`;
- persistence/queue behavior behind that interface;
- complete runtime ordering beyond the observed handler method;
- ownership;
- whether this is a safe first contribution.

### 2. Codebase baseline sync

**Observed source:** `api/handlers/codebase.go:27`

```text
GET /github/sync-baseline
  → CodebaseHandler.SyncBaseline
  → h.codebaseService.SyncRepository(...)
```

The handler declares `codebaseService domain.CodebaseService` and directly invokes `SyncRepository`.

This gives the route a recognizable operation: baseline synchronization is handed to the codebase service. That is substantially more meaningful to an engineer than an import path ending at `domain.go`.

Still unsupported:

- the implementation behind `CodebaseService`;
- what gets indexed or persisted;
- downstream queue/workflow details;
- ownership or contribution safety.

### 3. Frontend query

**Observed source:** `api/handlers/query.go:61-68`

```text
POST /query
  → QueryHandler.HandleQuery
  → h.redis.Subscribe(...)
  → h.redis.Publish(...)
```

This is useful but different from the service examples. The direct dependency is shared infrastructure, not a domain-specific operation.

The evidence establishes a request/response transport boundary:

- subscribe to `query_results:<queryID>`;
- publish a query job to `query_jobs`.

It does not by itself establish what the query engine does with that job.

### 4. Slack webhook

Two direct dependency boundaries are observed:

- `api/handlers/slack.go:158`: `h.slackBot.HandleEvent(...)` for app mentions.
- `api/handlers/slack.go:210`: `h.slackIngest.IngestSlackEvent(...)` for message ingestion.

This is stronger than route→handler alone because the handler's branch-specific operations are explicit. It also demonstrates why a route-only signal is insufficient: one route can contain multiple behavioral branches.

Still unsupported:

- the implementations behind `SlackBotService` and `SlackIngestService`;
- full event processing behavior;
- ownership;
- safe contribution scope.

## Before vs after

| Evidence level | Example | What a new engineer can actually learn |
|---|---|---|
| IMPORTS only | `github.go → domain.go` | The handler depends on shared domain definitions |
| Route → handler | `POST /github → GitHubHandler.HandleGitHubWebhook` | A concrete HTTP boundary and entrypoint |
| Route → handler → direct dependency call | `POST /github → GitHubHandler.HandleGitHubWebhook → h.githubIngest.IngestGitHubEvent` | The entrypoint hands the request to a named ingestion operation |

The third level crosses an important threshold: it begins to describe **what the component does**, rather than only **where the component is**.

The signal is not sufficient for a full workflow. But it is sufficiently specific to support a meaningful next inspection target: the service interface/implementation named by the handler field.

## False positives and ambiguity

### Interface implementation ambiguity

`h.githubIngest.IngestGitHubEvent` proves the handler calls the interface method. It does not prove which concrete implementation executes. The extractor intentionally stops at the interface boundary.

### Shared infrastructure

`h.redis.Publish` and `h.redis.Subscribe` are direct facts, but they are not themselves business responsibilities. They should not be promoted into workflow names such as "query processing" without downstream evidence.

### Multiple branches

Slack demonstrates that one route/handler can have several direct operations. A single route→handler relationship therefore remains too coarse for workflow generation.

### Helper methods

Calls such as `h.verifyGitHubSignature(...)` are receiver method calls, not dependency operations. The extractor intentionally excludes them because RID-08 is testing the narrower question of handler → injected dependency corroboration.

### Conditional execution

The observed calls may occur only on particular branches. The extractor records source-level direct calls; it does not claim unconditional runtime execution.

## Product usefulness

The evidence now supports a more recognizable onboarding progression:

```text
HTTP entrypoint
  → concrete handler
  → named operation/dependency
  → inspect that operation next
```

That is a better learning boundary than an import path and a better next-inspection instruction than route evidence alone.

However, this remains **structural source evidence**, not customer validation. We have not yet demonstrated that a real new engineer receives and uses a generated step based on this evidence successfully.

## Decision

**RID-08 outcome: PROMOTE NARROWLY.**

The direct handler-call signal is strong enough to keep as a small evidence-layer primitive. It should not yet be wired into autonomous workflow generation or graph persistence.

The narrow promotion target should be evidence composition:

```text
route → handler → direct dependency operation
```

with explicit evidence strength and uncertainty preserved.

Do not promote interface implementation, downstream workflow, ownership, or contribution safety without another independent signal.

## Verification status

Repository tests have not been executed by this environment. The extractor and focused tests are committed, but technical verification remains pending local execution.

Required verification:

```bash
cd nlp
PYTHONPATH=. uv run pytest tests/test_handler_call_evidence.py -q
PYTHONPATH=. uv run pytest tests/test_route_evidence.py -q
PYTHONPATH=. uv run pytest tests/test_ramp_v2.py -q
```

Then review:

```bash
git diff
git status
```

## Smallest next step

**Do not build a generic Go call graph.**

First verify the focused tests. If they pass, the next product experiment should be a read-only composition of route + handler + direct dependency evidence for the four named HTTP boundaries above, followed by a small human usefulness evaluation of the resulting onboarding descriptions.

The goal is to determine whether the composed evidence produces a genuinely useful **what this component does / what to inspect next** step before touching Ramp persistence or scoring.

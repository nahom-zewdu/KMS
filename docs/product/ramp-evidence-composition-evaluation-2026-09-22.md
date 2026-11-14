# RID-09 — Route → Handler → Direct Operation Evidence Composition

**Date:** 2026-09-22
**Status:** IMPLEMENTED — read-only structural evaluation; local repository execution pending
**Scope:** branch `feat/implementation-relations`, repository `nahom-zewdu/KMS`
**Mode:** source inspection only; no Supabase, graph, Ramp-plan, planner, scoring, or persistence writes

## Objective

Determine whether composing the already-verified RID-07 route/handler signal with the already-verified RID-08 direct handler dependency-call signal produces a useful onboarding boundary:

```text
HTTP route
  → concrete handler
  → explicitly called dependency operation
```

The product question is deliberately narrow:

> Does this composed evidence tell a new engineer what this entrypoint does at a useful level and what to inspect next, without claiming a workflow that the source does not prove?

This is still structural evaluation, not customer validation.

## Method

The new `GoEvidenceComposer` accepts only the outputs of the two existing read-only extractors:

- `RouteEvidence`
- `HandlerCallEvidence`

It joins records only when both the handler symbol and handler source file match.

The composed object preserves:

- HTTP method and path;
- handler symbol and source file;
- route source and line;
- dependency field;
- directly called operation;
- call source and line;
- a next-inspection target equal to the observed dependency field and method.

It does **not**:

- resolve an interface to a concrete implementation;
- infer runtime ordering;
- infer ownership;
- infer safe contribution scope;
- infer a complete downstream workflow;
- write graph edges or Ramp plans;
- alter planner/scoring behavior.

## Source-level findings

### GitHub webhook

Observed:

```text
POST /github
  → GitHubHandler.HandleGitHubWebhook
  → githubIngest.IngestGitHubEvent
```

The handler source directly declares `githubIngest domain.GitHubIngestService` and calls `h.githubIngest.IngestGitHubEvent(...)`.

**Onboarding value:** high enough to identify a concrete entry boundary and a named operation to inspect next.

A truthful next inspection is the `GitHubIngestService` interface and its implementation. The composition itself stops at the interface call and does not claim which implementation executes.

### Baseline synchronization

Observed:

```text
GET /github/sync-baseline
  → CodebaseHandler.SyncBaseline
  → codebaseService.SyncRepository
```

The handler directly calls `h.codebaseService.SyncRepository(...)`.

**Onboarding value:** high enough to identify that this HTTP boundary delegates baseline synchronization to a named codebase operation.

The next inspection target is `codebaseService.SyncRepository`; the actual service implementation must be inspected separately before describing downstream behavior.

### Frontend query

Observed:

```text
POST /query
  → QueryHandler.HandleQuery
  → redis.Subscribe
  → redis.Publish
```

**Onboarding value:** moderate and different from the domain-service examples.

The evidence establishes a transport boundary: subscribe to a query-result channel and publish a query job. It does not establish the semantics of query processing.

Therefore the safe onboarding description should not call this a complete "query workflow." The useful next inspection is the consumer of `query_jobs` / producer of `query_results:<queryID>`, not Redis itself as a business responsibility.

### Slack webhook

Observed branch-specific operations:

```text
POST /slack/events
  → SlackHandler.HandleSlackWebhook
  → slackBot.HandleEvent          (app mention branch)

POST /slack/events
  → SlackHandler.HandleSlackWebhook
  → slackIngest.IngestSlackEvent  (message branch)
```

**Onboarding value:** high for demonstrating that a single HTTP entrypoint can branch into different named operations.

This is important because a route-only model would flatten these branches into one vague "Slack implementation flow."

The composed evidence still does not claim that both operations execute for every request.

## Before / after

| Evidence | What it supports | What it does not support |
|---|---|---|
| `A imports B` | structural dependency | runtime behavior |
| route → handler | concrete HTTP entrypoint | downstream responsibility |
| route → handler → direct operation | entrypoint delegates to a named operation | implementation, complete workflow, ownership |
| route → handler → direct operation + next inspection | bounded starting point for source exploration | customer usefulness / contribution safety |

The third level is materially more actionable than the first two because it names an operation rather than ending at a shared domain file.

The fourth item is intentionally not a new inference layer: "next inspection" is simply the directly observed field/method pair, so it remains evidence-backed.

## Human usefulness assessment

### Structural judgment

For the four boundaries inspected, the composed evidence is sufficient to form a small, bounded onboarding instruction such as:

> Start at `POST /github`, inspect `GitHubHandler.HandleGitHubWebhook`, then follow its direct call to `githubIngest.IngestGitHubEvent`.

That instruction is more actionable than an import path because it gives the engineer a concrete entrypoint and a concrete operation to open next.

The signal is weaker for shared infrastructure (`redis.Publish` / `Subscribe`) because the operation describes transport mechanics rather than domain responsibility.

### What remains unproven

We have **not** shown that a real new engineer:

- understands the system faster from this evidence;
- can complete an onboarding task using it;
- avoids unnecessary files;
- reaches a safe contribution boundary faster;
- prefers this guidance over existing Ramp output.

Therefore RID-09 does **not** establish customer/product acceptance.

## Decision

**RID-09 outcome: PROMOTE TO HUMAN USEFULNESS TEST, not production integration.**

The composed evidence is strong enough to stop adding static-analysis sophistication for now. The next experiment should expose a small set of these evidence-backed onboarding boundaries to a human who did not build KMS and measure whether they can use them to locate and explain the relevant implementation.

Do not yet:

- add route/call evidence to graph persistence;
- change WorkflowDiscoverer;
- change candidate scoring;
- generate autonomous workflow candidates from this signal;
- claim contribution readiness.

## Verification

Required repository verification:

```bash
cd nlp
PYTHONPATH=. uv run pytest tests/test_evidence_composition.py -q
PYTHONPATH=. uv run pytest tests/test_handler_call_evidence.py -q
PYTHONPATH=. uv run pytest tests/test_route_evidence.py -q
PYTHONPATH=. uv run pytest tests/test_ramp_v2.py -q
git diff
git status
```

Expected focused test count is 22 total if the previously verified 17 tests remain unchanged: 5 composition + 5 handler-call + 3 route + 9 Ramp-v2.

## Acceptance gate

RID-09 can move from VERIFIED to ACCEPTED only after a dated human usefulness evaluation demonstrates that an engineer who did not build KMS can use the composed evidence to orient themselves and identify the next implementation boundary with materially less ambiguity than the current import-path output.

Until then, keep the composition layer read-only and unintegrated.

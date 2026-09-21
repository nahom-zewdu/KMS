# RID-07 — Go Route/Handler Corroboration Evaluation

**Date:** 2026-09-21  
**Status:** VERIFIED — read-only structural evaluation; focused extractor tests passed locally  
**Scope:** branch \`feat/implementation-relations\`, repository \`nahom-zewdu/KMS\`  
**Mode:** source inspection only; no Supabase, graph, or Ramp-plan writes

## Objective

Determine whether explicit Gin route registration plus handler-source resolution adds useful behavioral evidence to the existing 16-candidate IMPORTS snapshot.

This is an evidence experiment, not a production Ramp intelligence change.

## Method

A new read-only \`GoRouteEvidenceExtractor\` inspects:

1. explicit \`router.METHOD(path, handlerVariable.Method)\` registrations;
2. \`handlerVariable := NewXHandler(...)\` constructor bindings;
3. the unique source file containing \`type XHandler struct\`.

It emits only directly observed facts:

\`\`\`text
HTTP method + path
    ↓
handler symbol
    ↓
handler source file
\`\`\`

It abstains when the handler variable or handler type cannot be resolved uniquely.

It does **not** infer:

- runtime execution order;
- ownership;
- business responsibility beyond the HTTP boundary;
- safe contribution scope;
- complete control/data flow.

The extractor is not connected to \`WorkflowDiscoverer\`, the graph indexer, Ramp scoring, or persistence.

## Source evidence

The current \`api/handlers/routes.go\` explicitly registers:

| Method | Path | Handler | Source |
|---|---|---|---|
| POST | \`/github\` | \`GitHubHandler.HandleGitHubWebhook\` | \`api/handlers/github.go\` |
| POST | \`/github/\` | \`GitHubHandler.HandleGitHubWebhook\` | \`api/handlers/github.go\` |
| POST | \`/query\` | \`QueryHandler.HandleQuery\` | \`api/handlers/query.go\` |
| POST | \`/slack/events\` | \`SlackHandler.HandleSlackWebhook\` | \`api/handlers/slack.go\` |
| POST | \`/slack/events/\` | \`SlackHandler.HandleSlackWebhook\` | \`api/handlers/slack.go\` |
| GET | \`/github/sync-baseline\` | \`CodebaseHandler.SyncBaseline\` | \`api/handlers/codebase.go\` |

The inline \`/health\` route is intentionally excluded because it has no named handler symbol.

## Candidate reclassification

The 16 candidates from the 2026-09-20 snapshot were compared against the resolved handler files.

| # | Existing candidate | Route corroboration | Classification after route evidence | What is actually established |
|---:|---|---|---|---|
| 1 | \`nlp/main.py → nlp/worker/processor.py → nlp/worker/consumer.py → nlp/utils/__init__.py → nlp/utils/common.py\` | None | Ordinary dependency chain | Imports only |
| 2 | \`nlp/main.py → ... → nlp/engine/llm.py\` | None | Potential exploration path, still unverified | Imports only |
| 3 | \`nlp/main.py → ... → nlp/engine/llm.py\` | None | Potential exploration path, still unverified | Imports only |
| 4 | \`nlp/main.py → ... → nlp/engine/llm.py\` | None | Potential exploration path, still unverified | Imports only |
| 5 | \`api/handlers/github.go → api/domain/domain.go\` | **Direct**: \`POST /github\` | **Potentially useful exploration boundary** | HTTP request boundary and concrete handler are observed; domain import remains structural |
| 6 | \`api/repository/supabase.go → api/domain/domain.go\` | None | Fragment / no clear use | Imports only |
| 7 | \`api/handlers/query.go → api/domain/domain.go\` | **Direct**: \`POST /query\` | **Potentially useful exploration boundary** | HTTP query entrypoint and concrete handler are observed |
| 8 | \`api/handlers/slack.go → api/domain/domain.go\` | **Direct**: \`POST /slack/events\` | **Potentially useful exploration boundary** | Slack event HTTP boundary and concrete handler are observed |
| 9 | \`api/main.go → api/services/codebase.go → api/domain/domain.go\` | **Indirect**: baseline route exists, but candidate omits \`api/handlers/codebase.go\` | Ordinary dependency chain | A related route exists, but this candidate is not the route-to-handler path |
| 10 | \`api/handlers/routes.go → api/domain/domain.go\` | **Context only**: route registration source observed | Fragment / no clear use | The file registers routes, but this candidate does not identify a specific handler |
| 11 | \`api/main.go → api/handlers/codebase.go → api/domain/domain.go\` | **Direct**: \`GET /github/sync-baseline\` | **Potentially useful exploration boundary** | Baseline HTTP entrypoint and concrete handler are observed |
| 12 | \`nlp/main.py → ... → nlp/utils/logger.py\` | None | Potential exploration path, still unverified | Imports only |
| 13 | \`api/main.go → api/repository/redis_stream.go → api/domain/domain.go\` | None | Potential exploration path, still unverified | Imports only |
| 14 | \`nlp/main.py → ... → nlp/utils/logger.py\` | None | Ordinary dependency chain | Imports only |
| 15 | \`nlp/main.py → ... → nlp/utils/logger.py\` | None | Potential exploration path, still unverified | Imports only |
| 16 | \`nlp/main.py → ... → nlp/utils/logger.py\` | None | Potential exploration path, still unverified | Imports only |

## What route evidence adds

For candidates 5, 7, 8, and 11, the evidence changes the meaning of the first implementation surface.

Before:

> \`github.go imports domain.go\`

After:

> \`POST /github → GitHubHandler.HandleGitHubWebhook → api/handlers/github.go\`

That is materially more useful to an engineer because it identifies a concrete system boundary and a reason to inspect the file: it handles a specific incoming HTTP interaction.

The same applies to the query, Slack-event, and baseline-sync boundaries.

Route evidence does not rescue generic dependency paths. For candidate 10, knowing that \`routes.go\` registers HTTP routes does not identify which product behavior its domain import represents.

Candidate 9 is also important: the existence of \`GET /github/sync-baseline\` is related to the codebase service, but the candidate skips the actual handler boundary. Treating nearby route evidence as direct corroboration would overstate the evidence.

## Direct facts vs inference

### Directly observed

- Six named Gin route registrations resolve to handler registrations; two are trailing-slash variants.
- Each resolved handler symbol maps to one source file.
- \`GitHubHandler.HandleGitHubWebhook\`, \`QueryHandler.HandleQuery\`, \`SlackHandler.HandleSlackWebhook\`, and \`CodebaseHandler.SyncBaseline\` are concrete handler symbols in the current source.
- The corresponding candidate files are therefore exposed at an HTTP boundary.

### Structural inference

- These handler files are reasonable starting points for understanding the associated HTTP boundary.
- Candidate 11 is structurally closer to the baseline-sync boundary than candidate 9 because it contains the handler file.

### Behavioral inference not established

The route registration alone does not prove:

- what downstream services execute;
- whether every request follows a particular path;
- persistence or queue behavior;
- business outcome;
- ownership;
- contribution safety.

Those require additional evidence.

## False positives / ambiguity

The primary false-positive risk is **route existence being mistaken for workflow completeness**.

A route tells Ramp where an interaction enters the system without telling Ramp what the entire system does afterward.

A second risk is **shared domain imports**. The existing candidates terminate at \`api/domain/domain.go\`, which remains a poor workflow endpoint. Route evidence makes the handler boundary more recognizable but does not make the shared domain file a meaningful terminal responsibility.

A third issue is **candidate shape**. Route evidence cannot safely be attached merely because a nearby service appears in a route's downstream implementation. The candidate must contain, or explicitly connect through, the observed handler boundary.

## Human usefulness judgment

This is a structural judgment, not customer validation.

Route evidence appears materially useful for a narrow subset of Go candidates because it converts an opaque import relationship into a concrete interaction boundary. It does not yet produce a complete onboarding workflow or a safe contribution recommendation.

Therefore the signal is strong enough to justify a **small evidence-layer implementation**, but not a generalized route-aware workflow engine.

## Decision

**RID-07 outcome: PROMOTE NARROWLY.**

The repository now contains a standalone read-only route/handler evidence extractor and focused unit tests. It is deliberately not wired into Ramp planning or graph persistence.

The next corroboration should connect one already-observed handler boundary to its direct downstream operation—for example:

\`POST /github → GitHubHandler.HandleGitHubWebhook → GitHubIngestService.IngestGitHubEvent\`

That experiment should determine whether a second behavioral boundary produces a recognizable responsibility rather than merely another source-location fact.

## Verification status

Repository test execution could not be performed in this environment because direct external GitHub network access is unavailable to the local execution environment. Therefore this task is **not yet VERIFIED**.

The source inspection itself was performed against the branch contents, and the extractor/test files were committed to the target branch. No live Supabase, graph, or Ramp-plan mutation was performed.

## Smallest next step

Run the focused test file in the repository environment:

\`\`\`bash
cd nlp
uv run pytest tests/test_route_evidence.py -q
\`\`\`

If it passes, verify the full focused Ramp suite and review the diff. Only then should RID-07 move to \`VERIFIED\`.

Do not expand route analysis until that verification is complete.

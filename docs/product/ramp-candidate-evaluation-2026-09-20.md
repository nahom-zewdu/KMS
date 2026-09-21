# Ramp Candidate Usefulness Evaluation

**Date:** 2026-09-20  
**Scope:** live company `comp_1785181837594`, repository `nahom-zewdu/KMS`  
**Mode:** read-only Supabase query; no graph or plan writes

This file is the source of truth for that snapshot. Do not copy the candidate table elsewhere. Decision that follows from it: `docs/decisions/ADR-004-imports-are-not-workflows.md`. Selected next task: RID-07 in `docs/development/roadmap.md`.

## Evaluation method

`RampEvidenceStore.implementation_relationships()` maps company-scoped FILE
entity IDs to paths and turns graph edges into `Evidence`. It excludes `PART_OF`
and `OWNS`, then `WorkflowDiscoverer` keeps evidence whose endpoints are indexed
surfaces. The discoverer builds weak undirected components for grouping, but
expands directed simple paths, caps each path at eight files and each component at
eight candidates, and preserves the path's exact edge evidence.

Candidate labels are not semantic classifications. `_label()` takes the first
module-path segment from the path and emits `<segment> implementation flow`, or
`connected implementation flow`. In this snapshot, labels are therefore only
`api implementation flow` and `nlp implementation flow`.

## Classification criteria

- **Recognizable responsibility:** evidence identifies a responsibility boundary,
  not merely an import relation. This requires corroboration beyond `IMPORTS`.
- **Potentially useful exploration path:** a bounded multi-hop path with a clear
  structural start and distinct layers, but still uncertain without behavioral
  evidence.
- **Ordinary dependency chain:** a short or shared-leaf import path that explains
  code dependency but does not establish a workflow.
- **Fragment / no clear use:** a path too small or generic to support a useful
  exploration objective.

No candidate qualifies as a confirmed recognizable responsibility: all 68 signals
are direct `IMPORTS` edges, with no route, queue/event, symbol, test, history, or
runtime evidence attached.

## Live candidates

`edge:<uuid>` values below are the exact supporting IMPORTS evidence returned by
Supabase. Paths are listed in directed order.

| # | Candidate refs | Exact supporting evidence | Structural description | Classification |
|---:|---|---|---|---|
| 1 | `nlp/main.py -> nlp/worker/processor.py -> nlp/worker/consumer.py -> nlp/utils/__init__.py -> nlp/utils/common.py` | `3d7f4d99-f3f6-51ab-b088-25a0685bc9ad`, `3a8711df-b80e-5965-bf77-b08ccc0110a0`, `0e61ac4a-afbd-5730-a9e5-84f95a90fcc0`, `5c7894e6-658e-578c-9df1-e23c330e89fd` | Entrypoint to worker files, then shared utility package/common helper. | Ordinary dependency chain |
| 2 | `nlp/main.py -> nlp/worker/processor.py -> nlp/worker/query.py -> nlp/query_engine/core.py -> nlp/query_engine/retrieval.py -> nlp/query_engine/analyzer.py -> nlp/engine/llm.py` | `3d7f4d99-f3f6-51ab-b088-25a0685bc9ad`, `d2968146-e082-5f7d-a2ad-f6bec18ac5a8`, `226ff445-ff2b-5ec6-b104-863dd89077f7`, `92dd54a0-6447-5aee-90ea-375518466886`, `571c3466-04b2-50fe-b350-8a073e246fcf`, `e8e05e49-f8d4-5138-bc85-8543ca149ed3` | Entrypoint through worker/query and query-engine files to an LLM module. | Uncertain; potentially useful exploration path |
| 3 | `nlp/main.py -> nlp/worker/processor.py -> nlp/worker/query.py -> nlp/query_engine/core.py -> nlp/query_engine/synthesizer.py -> nlp/engine/llm.py` | `3d7f4d99-f3f6-51ab-b088-25a0685bc9ad`, `d2968146-e082-5f7d-a2ad-f6bec18ac5a8`, `226ff445-ff2b-5ec6-b104-863dd89077f7`, `0e7533f7-6b78-5b83-8abe-383becb86338`, `7a0eadea-5225-52ea-a44d-412f22c36759` | Entrypoint through query processing and synthesis to an LLM module. | Uncertain; potentially useful exploration path |
| 4 | `nlp/main.py -> nlp/worker/processor.py -> nlp/worker/query.py -> nlp/query_engine/core.py -> nlp/query_engine/retrieval.py -> nlp/query_engine/vector/retriever.py -> nlp/engine/llm.py` | `3d7f4d99-f3f6-51ab-b088-25a0685bc9ad`, `d2968146-e082-5f7d-a2ad-f6bec18ac5a8`, `226ff445-ff2b-5ec6-b104-863dd89077f7`, `92dd54a0-6447-5aee-90ea-375518466886`, `0d83116d-b205-57de-99c5-dbbd62c3367b`, `6468cb52-f352-5fec-a9b7-6ee1bc5a1cf0` | Entrypoint through query/retrieval and vector retrieval to an LLM module. | Uncertain; potentially useful exploration path |
| 5 | `api/handlers/github.go -> api/domain/domain.go` | `7c98bd55-efad-5530-b2cb-5c8ed7e9bfc6` | Handler imports shared domain file. | Fragment / no clear use |
| 6 | `api/repository/supabase.go -> api/domain/domain.go` | `a153d649-c4f4-5535-a68f-967147f3e120` | Repository implementation imports shared domain file. | Fragment / no clear use |
| 7 | `api/handlers/query.go -> api/domain/domain.go` | `6527fb82-a092-5e43-aedc-61e533bf01a0` | Handler imports shared domain file. | Fragment / no clear use |
| 8 | `api/handlers/slack.go -> api/domain/domain.go` | `e41af40c-b43a-529c-a6b4-e742a483c6c3` | Handler imports shared domain file. | Fragment / no clear use |
| 9 | `api/main.go -> api/services/codebase.go -> api/domain/domain.go` | `1630b091-9f7c-5e6e-90e5-b2704360714e`, `aaa67ca2-af00-5687-904e-21b9243e64ab` | Entrypoint imports service, which imports shared domain. | Ordinary dependency chain |
| 10 | `api/handlers/routes.go -> api/domain/domain.go` | `dd5a964c-33e4-5b96-804a-aa68609961a0` | Routes file imports shared domain file. | Fragment / no clear use |
| 11 | `api/main.go -> api/handlers/codebase.go -> api/domain/domain.go` | `ebe27d58-a59e-5c2c-b547-09f206f33ad7`, `c783942f-b01b-58eb-a5fb-e3a1eb78e216` | Entrypoint imports handler, which imports shared domain. | Ordinary dependency chain |
| 12 | `nlp/main.py -> nlp/worker/processor.py -> nlp/worker/baseline.py -> nlp/utils/supabase.py -> nlp/utils/logger.py` | `3d7f4d99-f3f6-51ab-b088-25a0685bc9ad`, `f874038d-c587-54de-bbd6-f2fb750b96d1`, `f6ea6a19-d2aa-5f94-8344-b1e5ae1b70b5`, `37287c5e-0553-5ca1-8467-90f4998f698f` | Entrypoint to worker baseline and shared persistence/logging utilities. | Uncertain; potentially useful exploration path |
| 13 | `api/main.go -> api/repository/redis_stream.go -> api/domain/domain.go` | `6d75b3c8-965e-571c-a934-c4c56c6822a0`, `c7352828-184f-516e-808c-b8901764539e` | Entrypoint to Redis repository and shared domain file. | Uncertain; potentially useful exploration path |
| 14 | `nlp/main.py -> nlp/worker/processor.py -> nlp/utils/__init__.py -> nlp/utils/supabase.py -> nlp/utils/logger.py` | `3d7f4d99-f3f6-51ab-b088-25a0685bc9ad`, `94af4f16-2e4d-52d8-9679-1cdc3bb931dc`, `0b4a9034-d98b-501d-937d-1f30d6c75105`, `37287c5e-0553-5ca1-8467-90f4998f698f` | Entrypoint to processor and shared persistence/logging utilities. | Ordinary dependency chain |
| 15 | `nlp/main.py -> nlp/worker/processor.py -> nlp/worker/ingestion.py -> nlp/utils/__init__.py -> nlp/utils/supabase.py -> nlp/utils/logger.py` | `3d7f4d99-f3f6-51ab-b088-25a0685bc9ad`, `d3877d50-44db-5cbc-85bf-441a9f34edc4`, `92b3b27b-375f-586e-b4dc-476106d583f8`, `0b4a9034-d98b-501d-937d-1f30d6c75105`, `37287c5e-0553-5ca1-8467-90f4998f698f` | Entrypoint to ingestion and shared persistence/logging utilities. | Uncertain; potentially useful exploration path |
| 16 | `nlp/main.py -> nlp/worker/processor.py -> nlp/worker/consumer.py -> nlp/utils/__init__.py -> nlp/utils/supabase.py -> nlp/utils/logger.py` | `3d7f4d99-f3f6-51ab-b088-25a0685bc9ad`, `3a8711df-b80e-5965-bf77-b08ccc0110a0`, `0e61ac4a-afbd-5730-a9e5-84f95a90fcc0`, `0b4a9034-d98b-501d-937d-1f30d6c75105`, `37287c5e-0553-5ca1-8467-90f4998f698f` | Entrypoint to worker consumer and shared persistence/logging utilities. | Uncertain; potentially useful exploration path |

## Findings

The weak-candidate repetition is structural:

1. `api/domain/domain.go` is a shared leaf, so unrelated handlers and services
   become short candidates with no evidence of request handling, persistence, or
   control flow.
2. `nlp/utils/__init__.py`, `nlp/utils/supabase.py`, and
   `nlp/utils/logger.py` are shared leaves, so worker branches converge into
   utility-heavy candidates.
3. `nlp/main.py -> nlp/worker/processor.py` is repeated across several paths,
   making the entrypoint and processor look like workflow evidence even though
   IMPORTS does not show which runtime branch is executed.
4. The longer query paths are plausible exploration material, but imports do not
   establish that a query actually traverses every imported module, nor do they
   establish user-visible behavior.

The missing evidence is source-level behavior that can distinguish dependency
structure from execution flow: route-to-handler registration, function or symbol
calls, queue publication/consumption, persistence operations, tests covering the
path, and history showing a coherent change boundary. Ownership and role evidence
could rank a verified path, but cannot turn imports into behavior by itself.

## Proposed acceptance criteria

Before calling a candidate a useful workflow, require all of the following:

1. **Evidence:** at least two implementation relation types or one IMPORTS path
   corroborated by a route, call, queue, persistence, or test signal.
2. **Boundedness:** 2–8 implementation surfaces, with no shared utility/domain
   leaf as the only target and no repeated path prefix accounting for the entire
   candidate without a second boundary signal.
3. **Structural coherence:** a reviewer can identify a source boundary, one or
   more intermediate responsibility boundaries, and a terminal boundary from
   evidence rather than filename interpretation.
4. **Provenance:** every displayed edge and file resolves to a company-scoped KMS
   record; no inferred file or business label is added.
5. **Discrimination:** adding an unrelated shared dependency must not create a
   new workflow candidate or materially change the candidate's core refs.
6. **Human evaluation:** two engineers unfamiliar with the implementation should
   independently rate the candidate as a useful exploration path at least 4/5,
   with agreement recorded separately from automated tests.

## Minimal next implementation step

Selected as **RID-07** in `docs/development/roadmap.md`. Do not add another path
heuristic. Add a read-only source evidence extractor for one existing boundary,
preferably route registration and handler/service calls in the Go API, and attach
those facts to candidate evaluation without changing the existing `IMPORTS` graph
or workflow output yet. Use the artifact above as the before fixture, then compare
whether the same 16 candidates gain corroboration or are rejected as ordinary
dependency chains.

Human usefulness has not been validated by this artifact; it is a structural
evaluation of live evidence only.
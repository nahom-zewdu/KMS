# KRT-04.6 — Planned Query Orchestration Boundary

**Status:** VERIFIED — USER-REPORTED LOCAL TESTS  
**Date:** 2026-11-26  
**Branch:** `feat/krt-04-evidence-gathering`

## Goal

Compose the KRT-04 stages behind one explicit, testable boundary without switching production QueryEngine traffic before repository-scope resolution and legacy-route compatibility are proven.

## Changes

Added `nlp/query_engine/planned_query.py`:

- Classifies a query using trusted `QueryScope`.
- Resolves exact SCIP symbols before call-site evidence gathering.
- Invokes the bounded evidence gatherer for supported code queries.
- Calls grounded synthesis only when validated evidence exists.
- Validates model output and exact citation membership before returning an answer.
- Returns explicit abstentions for unsupported queries, unresolved symbols, missing evidence, and invalid citations.
- Defers structured facts to the existing authoritative structured handler.
- Defers follow-ups/clarifications to the existing conversation handling path.
- Leaves the existing `QueryEngine.handle_query` behavior unchanged.

Added `nlp/tests/test_planned_query.py` covering passage flow, call-site resolution, structured/follow-up deferral, unsupported queries, ambiguous symbols, missing evidence, and invalid citations.

## Why QueryEngine is not switched yet

The current public job contract reliably supplies a company ID but does not establish a trusted repository ID. KRT-04 retrievers require both. Taking a repository ID directly from arbitrary question payload data would be unsafe; selecting one of several company repositories implicitly would be ambiguous. A separate trusted repository-selection boundary is required before production routing can use this executor.

The existing QueryEngine also has distinct structured-fact and conversation paths. This executor deliberately defers those paths rather than bypassing their authoritative behavior.

## Verification

User-reported local verification on 2026-11-26:

- `uv run pytest -q tests/test_planned_query.py` — **7 passed in 1.68s**.
- `uv run pytest -q` — **400 passed, 8 skipped, 6 warnings, 4 subtests passed in 15.63s**.
- The six warnings are existing python-json-logger and PyGithub deprecations.

## Boundaries

This is an orchestration seam, not a production traffic cutover. No QueryEngine behavior, cache semantics, Redis publication, analytics, structured fact handling, or legacy retrieval behavior is changed. QueryEngine integration remains the final KRT-04 stage after trusted repository selection and compatibility tests.

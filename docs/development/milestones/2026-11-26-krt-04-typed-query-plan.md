# KRT-04.1 — Typed Query-Plan Contract

**Status:** IMPLEMENTED — local runtime verification pending  
**Date:** 2026-11-26  
**Branch:** `feat/krt-04-query-planning`  
**Base:** KRT-03 merge commit `1872ef7c92fbf5cbbe6862801220abd65e25c1a4`

## Goal

Introduce a pure, immutable, dependency-light contract that represents a query plan before any classifier, symbol resolver, retriever, or synthesizer executes.

## Implementation

Added `nlp/query_engine/query_plan.py`:

- `QueryIntent` distinguishes courtesy, structured facts, declaration discovery, call-site navigation, passage retrieval, follow-ups, clarification, and unsupported requests.
- `QueryScope` requires a trusted non-placeholder company ID and accepts an optional validated repository ID.
- `QueryConstraints` carries optional source revision and time bounds, validating lengths, datetime types, timezone-awareness consistency, and ordering.
- `ResolvedScipSymbol` carries the exact symbol, resolution method, and source value that justified resolution.
- `QueryPlan` is frozen and validates typed intent/disposition, bounded extracted terms/paths/identifiers/qualified names/conversation references, and consistent ambiguity/abstention states.
- Limits are explicit module constants to keep downstream work bounded.

Added `nlp/tests/test_query_plan.py` covering supported intents, required/placeholder scope, invalid enum values, collection shape and bounds, time constraints, explicit ambiguity/abstention, symbol provenance, and follow-up references.

## Boundaries

This slice does not classify natural language, resolve symbols, execute retrieval, call an LLM or external service, change `QueryEngine.handle_query`, synthesize answers, or generate/validate citations. It adds no database migration and no vector/RRF work.

The contract deliberately keeps clarification and abstention as explicit dispositions. A follow-up can retain bounded conversation references without assuming that a reference or symbol has been resolved.

## Verification

Implementation and focused tests are committed. Runtime test results are pending execution in the developer's local checkout; do not mark this slice VERIFIED until the focused test and full NLP suite have been run and reported.

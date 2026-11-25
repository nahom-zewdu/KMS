# KRT-04.2 — Deterministic Query Classification

**Status:** VERIFIED — submitted for review  
**Date:** 2026-11-26  
**Branch:** `feat/krt-04-query-classification`  
**Base:** KRT-04.1 merge commit `54a0acaf7c69fecc6fc610dbc25effb750501ae3`

## Goal

Turn a current user query plus trusted caller context into the existing typed `QueryPlan` contract. Keep classification conservative and deterministic before connecting it to QueryEngine or retrieval.

## Implementation

Added `nlp/query_engine/query_planner.py`:

- Classifies courtesy, structured facts, declaration discovery, call-site navigation, passage retrieval, follow-ups, clarification, and unsupported requests.
- Uses ordered lexical rules; explicit call-site and declaration requests take precedence over broad passage matching.
- Extracts bounded file paths, qualified names, identifiers, and query terms.
- Requires a trusted `QueryScope` supplied by the caller. Scope is never inferred from user text.
- Treats acknowledgements and pronoun-led follow-ups as clarification unless both conversation history and caller-supplied conversation references are present.
- Never resolves a SCIP symbol. A call-site plan carries no `resolved_symbol` until a later, evidence-backed resolver proves an exact unambiguous match.
- Unsupported requests abstain rather than defaulting to broad retrieval.

Added `nlp/tests/test_query_planner.py` for supported intents, precedence, trusted scope, ambiguous follow-ups, explicit context references, extraction, bounds, abstention, and no speculative symbol resolution.

## Boundaries

This is a pure classifier/planner slice. It does not change `QueryEngine.handle_query`, call an LLM, Supabase, Redis, or a retriever, resolve repository/revision constraints, create conversation references, synthesize answers, or generate/validate citations. No migrations, embeddings, RRF, or UI changes.

The lexical rules are an intentionally small baseline, not a claim of broad natural-language understanding. They must be evaluated against representative query fixtures before wiring into production routing. False positives and false negatives should be corrected from those fixtures, not by expanding regexes speculatively.

## Verification

Developer-reported local verification on 2026-11-26:

- Focused contract + planner tests: `uv run pytest -q tests/test_query_plan.py tests/test_query_planner.py` — **49 passed in 1.23s**.
- Full NLP suite: `uv run pytest -q` — **359 passed, 8 skipped, 6 warnings, 4 subtests passed in 18.70s**.
- The six warnings are existing deprecations from python-json-logger and PyGithub's `login_or_token` argument.
- A duplicate parameterized fixture was removed after the full-suite run; this was a test-only cleanup and did not change implementation behavior.

The focused and full suites pass. These results verify the current deterministic classifier contract and regression suite; they do not establish broad natural-language classification quality. Representative real-world query evaluation is still required before connecting this planner to production QueryEngine routing.

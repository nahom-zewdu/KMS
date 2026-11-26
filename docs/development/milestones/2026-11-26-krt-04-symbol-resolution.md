# KRT-04.3 — Conservative SCIP Symbol Resolution

**Status:** VERIFIED — PENDING REVIEW  
**Date:** 2026-11-26  
**Branch:** `feat/krt-04-symbol-resolution`  
**Base:** KRT-04.2 merge commit `0334cff51a72d788137b1346827df60eaab7dc92`

## Goal

Resolve an explicitly named declaration in a call-site query to one exact SCIP symbol, using existing snapshot-scoped declaration and occurrence indexes. This is the narrow bridge between the KRT-04.2 planner and KRT-03 call-site retrieval.

## Inputs and output

Input is a validated `QueryPlan` plus injected `CodeSymbolRetriever` and `ScipOccurrenceRetriever` dependencies.

- Only `CALL_SITE_NAVIGATION` plans with `READY` disposition are eligible.
- `company_id` and `repository_id` come only from the plan's trusted `QueryScope`; a repository ID is mandatory.
- Candidate names come only from the plan's extracted `qualified_names` and `identifiers`.
- A successful result contains a copied plan with `ResolvedScipSymbol` populated, preserving the exact SCIP symbol and whether the input matched an exact qualified name or identifier.
- Non-success results explicitly report why resolution did not occur; callers must use the existing lexical fallback rather than guessing.

## Resolution algorithm

1. Prefer an explicit qualified name over a bare identifier.
2. Require one distinct candidate name. Multiple independent candidate names are ambiguous; do not choose by order or frequency.
3. For qualified names, use `CodeSymbolRetriever.find_qualified_name` (exact match). For identifiers, use `search_names` only as a bounded candidate lookup, then filter rows by exact `name` or exact `qualified_name`; substring matches are not accepted.
4. Require exactly one declaration row after exact filtering. Zero is unresolved; multiple declarations are ambiguous.
5. Read semantic occurrences for that declaration's file from the active snapshot. Match only a SCIP `definition` occurrence at the same source range as the declaration. Require exactly one distinct SCIP symbol.
6. Return the exact symbol string unchanged. Never synthesize a SCIP symbol from a source-language name.

The declaration and occurrence retrievers independently enforce company, repository, and active-snapshot scope. The resolver must also verify the returned declaration/occurrence rows agree on file path and source range before accepting a match.

## Failure states

At minimum: `not_call_site_query`, `repository_scope_required`, `no_explicit_symbol_candidate`, `multiple_symbol_candidates`, `declaration_not_found`, `ambiguous_declaration`, `definition_occurrence_not_found`, `ambiguous_scip_definition`, and `source_range_mismatch`.

No failure state should be silently converted into a guessed symbol.

## Tests

- Exact qualified-name resolution.
- Exact identifier resolution after rejecting substring-only matches.
- No declaration, duplicate declaration, multiple requested names.
- Declaration with no SCIP definition occurrence.
- Multiple SCIP definitions or mismatched source ranges.
- Non-call-site / non-ready plans are not resolved.
- Missing repository scope is rejected before retriever calls.
- Trusted company/repository arguments are passed unchanged.
- Active-snapshot behavior remains delegated to existing retrievers.

## Implementation checkpoint

Implemented as `nlp/query_engine/symbol_resolution.py` with focused tests in `nlp/tests/test_symbol_resolution.py`. The resolver uses injected retrievers, filters identifier substring results to exact names, checks declaration/SCIP definition file and byte/line ranges plus snapshot identity, and returns explicit failure reasons. It does not alter production routing.

**Verification (2026-11-26):** user-reported `uv run pytest -q tests/test_symbol_resolution.py` — **15 passed**; full `uv run pytest -q` — **373 passed, 8 skipped, 6 warnings, 4 subtests passed** in 19.55s. The six warnings are existing deprecations from `pythonjsonlogger` and PyGithub.

## Boundaries

This slice does not alter `QueryEngine`, classify queries, perform retrieval, change the retrieval router, synthesize answers, create citations, or write to Supabase. It adds no schema changes, migrations, embeddings, or RRF. Integration into production routing is a later, separately reviewed step.

The resolver is intentionally conservative: a lower resolution rate is preferable to navigating references for the wrong symbol.

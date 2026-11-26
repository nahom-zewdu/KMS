# KRT-04.4 — Bounded Evidence Gathering

**Status:** IMPLEMENTED — PENDING LOCAL VERIFICATION  
**Date:** 2026-11-26  
**Branch:** `feat/krt-04-evidence-gathering`

## Goal

Connect validated KRT-04 query plans to the existing KRT-03 deterministic retrievers through one bounded, provenance-preserving evidence-gathering boundary.

## Supported routing

| Intent | Retriever | Requirements |
|---|---|---|
| `PASSAGE_RETRIEVAL` | `SourceChunkRetriever` | At least one extracted term |
| `DECLARATION_DISCOVERY` | `CodeSymbolRetriever` | One explicit file path, qualified name, or identifier |
| `CALL_SITE_NAVIGATION` | `ScipOccurrenceRetriever` | Exact `ResolvedScipSymbol` already attached to plan |

Only one retrieval strategy runs for a plan. Multiple explicit declaration targets are rejected rather than fanned out or ranked speculatively.

## Scope and provenance

- Company and repository IDs are passed from the trusted `QueryScope`; repository scope is mandatory.
- Existing retrievers remain responsible for database-side company/repository/active-snapshot filtering.
- Returned code evidence must identify company, repository, snapshot, source revision, file, content hash, and exact line/byte range through `EvidenceCandidate`.
- Optional source-revision constraints are checked against returned evidence.
- The gatherer preserves the shared `EvidenceCandidate` type and stable evidence identity; it does not rewrite provenance.

## Bounds and abstention

- Maximum output: 20 evidence records; default: 8.
- Maximum content length: 12,000 characters; default: 12,000.
- Maximum passage terms forwarded: 20 (the query-plan contract already bounds them).
- Non-ready plans and courtesy/follow-up/clarification/unsupported intents do not retrieve.
- Structured facts are explicitly unsupported by this slice; the authoritative structured query path is not yet wired into the gatherer.
- Time constraints are explicitly unsupported until a compatible scoped retrieval contract exists.
- Missing repository scope, missing terms, unresolved SCIP symbols, multiple declaration targets, and empty results return stable reasons.

## Tests added

- Trusted company/repository scope forwarding for passage retrieval.
- Rejection of cross-scope and wrong-revision candidates.
- Exact declaration lookup and substring filtering.
- File-path declaration lookup.
- SCIP call-site retrieval requiring a resolved symbol and filtering definitions from references.
- No retrieval for non-ready and conversation-control plans.
- Missing repository and unsupported time constraints fail closed.
- Result-count and content-size bounds.
- Ambiguous declaration targets do not trigger fan-out.

## Verification

Pending local execution:

```bash
uv run pytest -q tests/test_evidence_gatherer.py
uv run pytest -q
```

## Boundaries

This slice does not integrate with `QueryEngine`, synthesize natural-language answers, generate or validate citations, invoke an LLM, write to Supabase, add migrations, or introduce embeddings/RRF. Those remain subsequent KRT-04 work, all on the same feature branch before the consolidated KRT-04 PR.

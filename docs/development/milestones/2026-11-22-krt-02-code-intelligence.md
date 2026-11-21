# KRT-02 — Code Intelligence Completion

**Status:** VERIFIED  
**Date:** 2026-11-22  
**Branch:** `feat/krt-02-code-intelligence`  
**Next milestone:** KRT-03 — Hybrid Retrieval

## Outcome

KMS now has revision-aware code declarations and semantic symbol occurrences for supported repositories. Both are persisted against immutable source snapshots and can be retrieved within the active company/repository scope.

## What changed

- Added Tree-sitter declaration extraction for Python, Go, JavaScript, TypeScript, and TSX.
- Added bounded indexing and snapshot-scoped persistence for declarations, including explicit coverage for unsupported, oversized, unavailable, and syntax-error files.
- Added exact-name, file-symbol, and name-search navigation against the active snapshot.
- Added a bounded SCIP adapter that normalizes definitions and occurrences with source paths, ranges, file hashes, source revision, and indexer metadata.
- Added separate persistence and retrieval for SCIP occurrences, including definition/reference navigation and database-derived coverage counts.
- Added database checks for tenant/repository/file ownership, source revision, snapshot publication, idempotency, and protection of published records.
- Integrated declaration indexing into baseline snapshot creation. SCIP occurrence indexing is available as a separate bounded indexing path; it is not represented as an automatically enabled production job.
- Added opt-in real SCIP integration tests and documented toolchain requirements.

## Verification

Developer-reported local checks on 2026-11-22:

- Full NLP suite: **245 passed, 3 skipped, 6 warnings, 4 subtests passed**.
- SCIP occurrence persistence tests: **8 passed**.
- Real SCIP integrations were run separately for Python, Go, and TypeScript; each language integration passed in its respective opt-in run.
- The SCIP occurrence migration applied successfully to the local PostgreSQL 16 test database.
- `schema/tests/code_symbol_occurrences.sql` passed against that database.
- Earlier local PostgreSQL checks for snapshot and declaration persistence also passed.

The three default-suite skips are opt-in language integrations, which were exercised separately. The six warnings are existing dependency deprecations, not test failures.

## Boundaries and remaining risks

- This verifies the implementation and local integration tests; it does not claim a live Supabase deployment or production-data validation.
- SCIP indexing requires language-specific tools and project context. It is not automatically enabled for every repository.
- The subprocess runner applies time and output limits but is **not** an OS-level security sandbox. Indexing untrusted repositories still requires an isolated worker with resource and network restrictions.
- Language coverage is explicit, not complete. Unsupported syntax and indexer/toolchain failures must remain visible rather than being treated as successful coverage.
- No general call graph, runtime workflow inference, or behavioral proof is introduced by symbol/reference indexing.

## Next

Proceed to KRT-03 Hybrid Retrieval. First inspect the current text/vector stores and retrieval interfaces, then specify candidate generation, tenant/revision filtering, fusion, and a small evaluation set before implementation. Do not assume that existing raw-event embeddings already provide source-code semantic retrieval.

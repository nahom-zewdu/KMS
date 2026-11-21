# KRT-03 — Hybrid Retrieval Design

**Status:** IN_PROGRESS — first evidence/lexical slice locally verified; lexical metric harness added, integration baseline pending  
**Date:** 2026-11-22  
**Working branch:** `feat/krt-03-hybrid-retrieval`  
**Base branch:** `feat/ramp`  
**Prerequisite:** KRT-00, KRT-01, and KRT-02 completed  
**Next:** Build and evaluate retrieval slices before integrating them into the query engine

## Goal

Return the right company evidence for a question, with its source and revision intact. Combine exact matching, semantic similarity, and code relationships without mixing evidence from different companies or source revisions.

This milestone improves candidate retrieval. It does not replace structured answers, query planning, or grounded synthesis (KRT-04).

## What exists today

| Area | Current implementation | Gap |
|---|---|---|
| Historical/event vectors | `VectorRetriever` embeds queries with `all-MiniLM-L6-v2` and calls `match_documents` on `raw_data` (384 dimensions) | This is event/context search, not source-code search |
| Event keyword fallback | Company-filtered `ilike` over `raw_data.content` | Limited token matching; no code/path/identifier index |
| Graph retrieval | `AdaptiveRetriever` resolves entities and searches company-scoped edges | Not a general ranked evidence retriever |
| Source files | `retrieve_source_chunks` selects a few indexed paths and fetches file text from GitHub | Heuristic selection; not reusable lexical retrieval; source fetch uses repository `baseline_revision`, which must be tied explicitly to the active snapshot |
| Code declarations | `CodeSymbolRetriever` searches declarations by qualified name, file, or name | Useful exact navigation, not broad text retrieval |
| Semantic references | `ScipOccurrenceRetriever` finds definitions and references by SCIP symbol | Useful structural navigation, not natural-language retrieval |
| Ranking | `AdaptiveRetriever` adds source bonuses and deduplicates by a content prefix | Scores are not calibrated or evaluated; no rank-fusion baseline |
| Structured facts | `structured.py` answers supported counts, inventory, Ramp state, and ownership questions directly | Keep this authoritative path separate from generic top-k retrieval |

## Design decisions

### 1. Keep retrieval sources distinct

KRT-03 should expose independently testable candidate sources:

- **Structured:** existing deterministic SQL answers remain outside generic top-k fusion.
- **Lexical:** exact file paths, names, qualified names, identifiers, and indexed source text.
- **Semantic:** vector similarity over source-code chunks and, where relevant, historical event records.
- **Structural:** declarations, SCIP definitions/references, and existing typed graph relationships.

Do not treat imports, symbol references, or inferred relations as proof of runtime behavior.

### 2. Introduce a shared evidence candidate

Every retriever should return a consistent record containing, where applicable:

- evidence type and stable evidence ID;
- company and repository IDs;
- active snapshot ID and source revision;
- file path and line/byte range;
- content or a bounded evidence excerpt;
- retriever name, rank, and raw score;
- content hash and extractor/indexer/chunker version.

The source identity and provenance must survive deduplication, fusion, and synthesis. A file path alone is not a citation.

### 3. Add a durable source-chunk index before code embeddings

The current `codebase_files` rows are inventory metadata; they do not store durable source text chunks. Create a snapshot-scoped source-chunk store only after settling the chunk contract.

Each chunk should be tied to the exact repository snapshot and file, with source revision, content hash, line/byte range, chunker version, and embedding model/version when embedded. Enforce tenant/repository/file ownership in the database, following the KRT-02 persistence pattern.

The GitHub fetch path must resolve the commit from the active snapshot itself, not assume the repository's mutable `baseline_revision` is always the same revision. Never embed text fetched from a different revision than the snapshot being indexed.

### 4. Treat code and event embeddings as separate evidence domains

Existing event embeddings use `all-MiniLM-L6-v2`, 384 dimensions. That proves the current event-vector path; it does not prove the same model retrieves code well.

Start with a reproducible baseline using the existing model only if it can be applied consistently to code chunks. Record the model ID, dimensions, normalization, and version. Compare it against lexical-only retrieval on a small code-query set before deciding whether a different embedding model is justified.

Do not silently mix event and code vectors or compare their raw similarity scores as if they were calibrated.

### 5. Use rank fusion, not hand-written score bonuses

Each retriever should return a ranked list. Start with Reciprocal Rank Fusion (RRF) for combining lexical, semantic, and structural candidates. Preserve each source rank for debugging.

Deduplicate by stable evidence identity (snapshot + file + range + content hash, or the corresponding event/graph identity), not by the first 120 characters of content. Keep multiple distinct ranges from the same file when they support different claims.

Do not add a reranker until evaluation shows that fusion leaves a meaningful ranking problem.

### 6. Enforce scope before candidates leave storage

Every code retrieval path must filter by company, repository, and active snapshot in its database query. The default is the active published snapshot. A future explicit historical-revision query must request a specific revision; it must not silently widen to old snapshots.

Event retrieval remains company-scoped. Graph retrieval remains company-scoped. Do not rely on filtering results after retrieval as the security boundary.

## Implementation sequence

1. **Evidence contract and fixtures**
   - Define the shared candidate shape and stable identity rules.
   - Create a small repository fixture with known paths, declarations, references, and source ranges.
   - Create a small query set with expected paths, symbols, and event IDs. Add exact evidence IDs/ranges when the indexer-backed benchmark runner is implemented.

2. **Lexical source retrieval**
   - Add exact path, qualified-name, and identifier lookup using existing snapshot metadata.
   - Add full-text retrieval over persisted source chunks once the chunk store is in place.
   - Measure exact-match recall before adding vectors.

3. **Durable chunk storage**
   - Specify chunk boundaries and provenance.
   - Add snapshot-scoped persistence, database constraints, and PostgreSQL integration tests.
   - Ensure source text is from the exact published snapshot.

4. **Semantic code retrieval**
   - Embed persisted chunks with a pinned model/version.
   - Add a tenant/repository/active-snapshot filtered vector search function.
   - Test vector behavior against real pgvector in the disposable PostgreSQL database.

5. **Fusion and query-engine integration**
   - Implement RRF over independently ranked candidate lists.
   - Preserve source identity and provenance in output.
   - Integrate code retrieval without regressing structured answers or event-history queries.

## Evaluation and acceptance

Build a small versioned benchmark before implementation; start with 20–30 questions and expand based on observed failures. Include:

- exact file-path and identifier questions;
- qualified-name and definition/reference navigation;
- natural-language questions about code behavior;
- questions requiring evidence across multiple files;
- historical Slack/GitHub event questions;
- queries with no relevant evidence;
- same-named files/symbols in different repositories or companies.

Track:

- Recall@5 and Recall@10 for expected evidence;
- MRR or nDCG@10 for ranking quality;
- exact snapshot/revision correctness;
- cross-company and cross-repository leakage (must be zero);
- latency and embedding/indexing cost.

KRT-03 is accepted only when lexical and semantic retrieval are independently tested, fusion improves or at least does not regress the benchmark, every returned code candidate has exact snapshot provenance, and database tests prove tenant/snapshot isolation. Keep unsupported cases visible; do not claim complete code understanding.

## Explicitly out of scope

- New vector database or graph database.
- RAG framework adoption.
- Automatic query planning and claim-level citation validation (KRT-04).
- LLM reranking before a benchmark justifies it.
- Generic call-graph or runtime-flow inference.
- Production rollout of a new embedding pipeline before local database and retrieval evaluation pass.

## Implementation progress — 2026-11-22

### First slice: evidence contract and benchmark fixture

Added:

- `nlp/query_engine/evidence.py`: immutable `EvidenceCandidate` contract for code chunks, symbols, SCIP occurrences, events, and graph evidence.
- Code candidate validation requires company, repository, active snapshot, source revision, path, content hash, and source ranges.
- Stable evidence IDs are based on tenant and source identity, not retriever rank or score. Code identity includes the exact snapshot, revision, path, range, and content hash; event/graph identity includes company, source, and record ID.
- `nlp/tests/test_query_engine_evidence.py`: validation, identity stability, tenant separation, and serialization tests.
- `nlp/tests/fixtures/retrieval/`: a small synthetic four-file repository, historical event records, and a 20-query benchmark covering paths, identifiers, definitions/references, natural-language code questions, multi-file questions, historical events, no-evidence queries, and scope boundaries.
- `nlp/tests/test_retrieval_benchmark_fixture.py`: checks that benchmark expectations resolve to fixture files, symbols, and tenant-owned event records.
- `nlp/query_engine/code_lexical.py`: adds a first lexical adapter over active-snapshot declarations. It prioritizes exact qualified-name matches, then exact file-path declarations, then identifier matches; deduplicates by stable evidence ID and retains the match modes.
- `nlp/tests/test_code_lexical_retriever.py`: covers scope forwarding, deduplication, ranking, provenance, and invalid tenant rejection.
- `nlp/query_engine/lexical_benchmark.py`: adds a reusable evaluator for Recall@1/5/10 and MRR, with hard company/repository/snapshot leakage checks.
- Eight fixture queries now declare explicit lexical inputs. The other twelve remain unsupported by this lexical slice and are not counted as misses.
- `nlp/tests/test_lexical_benchmark.py`: covers metric calculation, late/missing relevant evidence, invalid cutoffs, and company/repository/snapshot leakage.

**Local verification — developer-reported, 2026-11-22:**

- Focused evidence, lexical retriever, and benchmark-fixture tests: **29 passed**.
- Full NLP suite: **274 passed, 3 skipped, 6 warnings, 4 subtests passed**.
- No failures. The skipped tests are opt-in SCIP integrations; Python, Go, and TypeScript integrations were exercised separately in the KRT-02 close-out.
- The warnings are existing dependency deprecations (`pythonjsonlogger` and PyGithub), not failures.

This verifies the current slice's tests, not retrieval quality. The benchmark remains a deterministic synthetic fixture; it does not yet measure end-to-end retrieval quality or represent a production repository.

### Next bounded implementation

Run the evaluator against an indexed copy of the synthetic repository using the real `CodeLexicalRetriever`. The current tests validate the evaluator with controlled candidates; they do **not** establish a retrieval baseline. The integration run must prove that fixture declarations are indexed under the declared company/repository/snapshot IDs, then record Recall@1/5/10, MRR, and zero scope leakage. If fixture indexing cannot reproduce the declared snapshot identity cleanly, fix the fixture/indexing boundary rather than weakening provenance checks. Do not add source chunks or embeddings until this lexical baseline is measured.

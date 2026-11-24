# KRT-03 — Hybrid Retrieval Design

**Status:** IN_PROGRESS — lexical retrieval, source-chunk persistence, and small benchmark comparisons verified; a 33-query task-separated evaluation fixture is implemented and awaiting local validation  
**Date:** 2026-11-22  
**Working branch:** `feat/krt-03-hybrid-retrieval`  
**Base branch:** `feat/ramp`  
**Prerequisite:** KRT-00, KRT-01, and KRT-02 completed  
**Next:** run the new task-separated retrieval integration benchmark, inspect its per-query failures and rankings, then refine the labels/runners before considering semantic retrieval or rank fusion

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

- `nlp/query_engine/evidence.py`: immutable `EvidenceCandidate` contract for code chunks, symbols, SCIP occurrences, events, and graph evidence.- Code candidate validation requires company, repository, active snapshot, source revision, path, content hash, and source ranges.
- Stable evidence IDs are based on tenant and source identity, not retriever rank or score. Code identity includes the exact snapshot, revision, path, range, and content hash; event/graph identity includes company, source, and record ID.
- `nlp/tests/test_query_engine_evidence.py`: validation, identity stability, tenant separation, and serialization tests.
- `nlp/tests/fixtures/retrieval/`: a small synthetic four-file repository, historical event records, and a 20-query benchmark covering paths, identifiers, definitions/references, natural-language code questions, multi-file questions, historical events, no-evidence queries, and scope boundaries.
- `nlp/tests/test_retrieval_benchmark_fixture.py`: checks that benchmark expectations resolve to fixture files, symbols, and tenant-owned event records.
- `nlp/query_engine/code_lexical.py`: adds a first lexical adapter over active-snapshot declarations. It prioritizes exact qualified-name matches, then exact file-path declarations, then identifier matches; deduplicates by stable evidence ID and retains the match modes.
- `nlp/tests/test_code_lexical_retriever.py`: covers scope forwarding, deduplication, ranking, provenance, and invalid tenant rejection.
- `nlp/query_engine/lexical_benchmark.py`: adds a reusable evaluator for Recall@1/5/10 and MRR, with hard company/repository/snapshot leakage checks.
- Eight fixture queries now declare explicit lexical inputs. The other twelve remain unsupported by this lexical slice and are not counted as misses.
- `nlp/tests/test_lexical_benchmark.py`: covers metric calculation, late/missing relevant evidence, invalid cutoffs, and company/repository/snapshot/source-revision leakage.
- `nlp/tests/test_lexical_benchmark_integration.py`: indexes the four real fixture source files with `CodeSymbolIndexer`, retrieves them through `CodeLexicalRetriever`, and runs the evaluator end to end against an in-memory PostgREST double. It asserts the expected fixture baseline (Recall@1/5/10 and MRR), active-repository isolation, and persisted provenance. This is application-pipeline integration, not PostgreSQL/RLS integration.

**Local verification — developer-reported, 2026-11-22:**

- Initial evidence/lexical/fixture verification on `feat/ramp`: **29 focused passed**; full NLP suite **274 passed, 3 skipped, 6 warnings, 4 subtests passed**.
- After adding the lexical evaluator, developer-reported focused KRT-03 suite on `feat/krt-03-hybrid-retrieval`: **36 passed**.
- Latest developer-reported full NLP suite on the feature branch: **281 passed, 3 skipped, 6 warnings, 4 subtests passed**.
- No failures. The skipped tests are opt-in SCIP integrations; Python, Go, and TypeScript integrations were exercised separately in the KRT-02 close-out.
- The warnings are existing dependency deprecations (`pythonjsonlogger` and PyGithub), not failures.

This verifies the current slice's tests, not retrieval quality. The benchmark remains a deterministic synthetic fixture; it does not yet measure end-to-end retrieval quality or represent a production repository.

### Next bounded implementation

Run the evaluator against an indexed copy of the synthetic repository using the real `CodeLexicalRetriever`. The current tests validate the evaluator with controlled candidates; they do **not** establish a retrieval baseline. The integration run must prove that fixture declarations are indexed under the declared company/repository/snapshot IDs, then record Recall@1/5/10, MRR, and zero scope leakage. If fixture indexing cannot reproduce the declared snapshot identity cleanly, fix the fixture/indexing boundary rather than weakening provenance checks. Do not add source chunks or embeddings until this lexical baseline is measured.


### Lexical baseline verification — 2026-11-23

Developer-reported local verification on `feat/krt-03-hybrid-retrieval`:

- `tests/test_lexical_benchmark_integration.py`: **1 passed**.
- Full NLP suite: **283 passed, 3 skipped, 6 warnings, 4 subtests passed**.
- The end-to-end fixture indexes four Python files through the real Tree-sitter symbol indexer, retrieves through `CodeLexicalRetriever`, and evaluates eight supported lexical queries. Recall@1/5/10 and MRR are all **1.0** on this curated fixture.
- This test uses an in-memory PostgREST double. It does not verify PostgreSQL query behavior or RLS.

### Source chunking and lexical retrieval — implementation checkpoint, 2026-11-23

Added on `feat/krt-03-hybrid-retrieval`:

- `nlp/codebase/source_chunker.py`: deterministic line-window chunking with configurable source/chunk/line bounds, overlap, UTF-8 byte offsets, one-based line ranges, source/chunk SHA-256 hashes, and snapshot/revision-scoped stable IDs. Oversized files and individual lines fail closed.
- `nlp/codebase/source_chunk_indexer.py`: bounded idempotent batched writes to `source_code_chunks`, with explicit per-file coverage results.
- `nlp/codebase/source_chunk_retriever.py`: literal lexical retrieval filtered in storage by company, repository, and the repository's active snapshot; results become provenance-complete `EvidenceCandidate` objects.
- `supabase/migrations/20261123010000_add_source_code_chunks.sql`: durable chunk table, composite ownership/file/snapshot foreign keys, revision/building-snapshot trigger, publication count validation, coverage refresh function, indexes, and service-role-only table access.
- `nlp/tests/test_source_chunking.py`, `nlp/tests/test_source_chunk_retriever.py`, and `schema/tests/source_code_chunks.sql`.

**Verification superseding the initial implementation checkpoint — 2026-11-24:**

- Focused chunking/indexer/retriever/baseline-ingestion tests: **9 passed**.
- Full NLP suite at the latest reported revision: **292 passed, 4 skipped, 6 warnings, 4 subtests passed**.
- Migration applied and verified against disposable local PostgreSQL; `schema/tests/source_code_chunks.sql` passed.
- Migration applied to the configured development/test Supabase project. The opt-in Supabase API integration test passed and exercised persistence, idempotency, provenance, tenant/repository isolation, and active-snapshot switching.
- Source chunk indexing is wired into baseline ingestion. It uses content fetched from the exact snapshot revision and validates chunk coverage before snapshot publication.
- The source-chunk benchmark integration test passed (**1 passed**), but this is only pipeline verification; see the 2026-11-24 benchmark-quality note below.

**Boundaries:** no code embeddings, vector column/function, or rank fusion are implemented. Chunking remains line-oriented, and an individual line larger than the configured chunk byte limit is rejected rather than split. The in-memory benchmark double does not establish PostgreSQL query-planner or RLS behavior; those are covered separately by SQL and opt-in Supabase integration checks.


### Source-chunk benchmark checkpoint — 2026-11-24

The initial end-to-end benchmark test `nlp/tests/test_source_chunk_benchmark_integration.py` passed (**1 passed**). It exercises the real chunker, indexer, and retriever over the synthetic four-file repository using an in-memory PostgREST double.

Code review identified a benchmark-design weakness: default chunking produces only four chunks for this fixture, one per file. Ground truth is currently file-path based, so multiple chunks from a relevant file cannot be distinguished. The test's Recall@5/10 assertions consequently do not establish meaningful ranking quality. Treat this as an integration smoke test, not a retrieval-quality baseline.

**Next task — benchmark hardening:**

1. Produce multiple chunks per file and add distractor chunks.
2. Define exact relevant chunk ranges/IDs in the versioned fixture.
3. Preserve and inspect per-query candidate rankings; report exact Recall@1/5/10 and MRR.
4. Compare with symbol lexical retrieval only on a shared, defensible subset of queries and relevance units. Keep unsupported/non-comparable queries visible.
5. Record the benchmark method, results, and limitations here and in the roadmap.

Do not start semantic embeddings or RRF until this task produces a credible lexical baseline.

### Chunk-level benchmark revision — implementation pending local verification, 2026-11-24

The initial four-chunk/file-level benchmark has been replaced with a versioned chunk-level fixture:

- Five-line windows with one-line overlap create multiple candidates per source file; non-relevant chunks act as ranking distractors.
- Ground truth identifies exact `(file_path, start_line, end_line)` ranges rather than treating every chunk in a relevant file as relevant.
- Five supported lexical queries and one explicit no-evidence query are included.
- The integration test emits deterministic per-query candidate rankings, matched terms, relevant ranks, Recall@1/5/10, and MRR.
- The test continues to validate company/repository/active-snapshot/source-revision provenance and no-evidence/tenant/repository isolation.

**Developer-reported local verification — 2026-11-24:**

```text
uv run pytest tests/test_source_chunk_benchmark_integration.py -q -s
1 passed in 1.10s
```

Measured results from the five supported queries (the no-evidence query is reported separately):

| Metric | Result |
|---|---:|
| Recall@1 | 0.70 |
| Recall@5 | 1.00 |
| Recall@10 | 1.00 |
| MRR | 1.00 |

The benchmark emits per-query rankings and matched terms. Every supported query has at least one relevant chunk at rank 1. Recall@1 is lower than 1.0 because three queries have multiple relevant chunks and top-1 can return only one of them.

**Interpretation and limitations:** this verifies deterministic behavior of the real chunker, indexer, and retriever on a controlled synthetic four-file fixture. It is not evidence of real-world retrieval quality: there are only five supported queries, the lexical terms are explicit identifiers, relevance is manually specified at exact line-range level, and the test uses an in-memory PostgREST double. It does not measure PostgreSQL query planning/RLS or natural-language retrieval quality. The separate SQL and opt-in Supabase API tests cover persistence and scope behavior, not this benchmark's ranking quality.

The source-chunk and symbol retrievers are not directly comparable on all queries because their evidence units differ (chunks versus symbols/declarations). A comparison should be attempted only if a genuinely shared subset and relevance mapping can be defined without weakening either retriever's evidence semantics.

**Full-suite regression verification — developer-reported, 2026-11-24:** `uv run pytest -q` completed with **293 passed, 4 skipped, 6 warnings, and 4 subtests passed in 20.36s**. This is the first reported full-suite run after the revised chunk-level benchmark landed. The warnings are existing `pythonjsonlogger` and PyGithub deprecations.

**Next:** assess whether a defensible shared-subset comparison with symbol lexical retrieval is possible. Do not start embeddings, RRF, or reranking based on this smoke benchmark alone. KRT-03 remains **IN_PROGRESS**.

### Shared symbol/chunk comparison — implementation pending local verification, 2026-11-24

A narrow common evaluation has been added in:

- `nlp/tests/fixtures/retrieval/shared_definition_file_benchmark.json`
- `nlp/tests/test_shared_lexical_retrieval_comparison.py`

The benchmark uses four identical identifier queries (`register_routes`, `should_retry`, `record_payment`, and `_insert`) against the same indexed four-file fixture, same company/repository/active snapshot/source revision, and the same file-level ground truth. Symbol declarations and source chunks are both projected to unique file paths; chunk hits from the same file are deduplicated before ranking. Both retrievers therefore receive the same query signal and are scored against the same target unit.

**What this comparison can establish:** whether each lexical retriever can discover the file containing a named declaration, and how high that file ranks after projecting results to unique files.

**What it cannot establish:** passage-level relevance, call-site retrieval parity, natural-language understanding, broad repository performance, PostgreSQL/RLS behavior, or semantic retrieval quality. It is a deliberately narrow diagnostic. The source-chunk retriever has richer passage-level evidence, but this experiment discards that advantage to create a shared evaluation unit. Results must not be interpreted as a general winner between the retrievers.

**Developer-reported local verification — 2026-11-24:**

```text
uv run pytest tests/test_shared_lexical_retrieval_comparison.py -q -s
1 passed in 1.12s
```

| Metric | Symbol lexical | Chunk lexical |
|---|---:|---:|
| Recall@1 | 1.00 | 0.75 |
| Recall@5 | 1.00 | 1.00 |
| Recall@10 | 1.00 | 1.00 |
| MRR | 1.00 | 0.875 |

Per-query inspection shows the meaningful difference: for `record_payment`, symbol retrieval ranks the declaration file `src/storage/ledger.py` first. Chunk retrieval ranks `src/payments/service.py` first because it contains a call site, then ranks the declaration file second. This illustrates why symbol and chunk retrieval are complementary evidence sources rather than interchangeable retrievers.

**Interpretation remains narrow:** this is a four-query, synthetic, four-file identifier benchmark, evaluated at unique-file level with an in-memory PostgREST double. It establishes that both systems can retrieve the target declaration file within top five for these four cases, while symbol retrieval ranks it first more consistently. It does not establish general retrieval superiority, passage-level quality, natural-language performance, or real repository effectiveness. The initial empty chunk results were caused by a mismatch in the test double's ILIKE handling; the test double was aligned with the previously verified chunk benchmark. Production retriever behavior was not changed.

**Full-suite regression verification — developer-reported, 2026-11-24:** `uv run pytest -q` completed with **294 passed, 4 skipped, 6 warnings, and 4 subtests passed in 20.92s** after the shared comparison was added. The warnings remain the existing `pythonjsonlogger` and PyGithub deprecations.

**Next:** design a broader evaluation set with separate labels for declaration discovery, call-site/context discovery, and exact passage relevance. Keep those task types separate; do not collapse them into one score. KRT-03 remains **IN_PROGRESS**.


### Task-separated retrieval evaluation fixture — implementation pending local verification, 2026-11-24

Added a larger synthetic multi-module Python corpus under `nlp/tests/fixtures/retrieval/mini_repo_v2/` with nine files spanning catalog, billing, notifications, storage, API, and token operations.

Added `nlp/tests/fixtures/retrieval/retrieval_tasks_v1.json` with **33 labeled queries**:

| Task | Queries | Ground truth |
|---|---:|---|
| Declaration discovery | 10 | Declared symbol names and containing file paths |
| Call-site/context discovery | 10 | Exact one-based inclusive source line ranges for usage/context |
| Passage retrieval | 10 | Exact one-based inclusive answer-bearing source ranges |
| No evidence | 3 | Explicitly empty labels; query terms must be absent from the corpus |

The fixture keeps natural-language questions separate from explicit lexical terms. It defines range-overlap relevance for chunk-level evaluation and asks that exact-range match rate remain a separate diagnostic. Task metrics must be reported separately; declaration/file discovery must not be conflated with call-site or passage relevance.

Added `nlp/tests/test_retrieval_task_benchmark_fixture.py` to validate task balance, unique query IDs, Python declaration labels using AST, range bounds and term presence, and negative-query absence.

**Not yet verified:** the new fixture and validation tests have been committed but have not been run locally. They do not yet constitute a retrieval benchmark runner or measured retrieval-quality results. The current 33 labels are hand-authored synthetic ground truth and need inspection against actual indexer chunk boundaries. No semantic retrieval, embeddings, or RRF should begin based on the fixture alone.

**Next:** run the focused fixture validation tests, fix only incorrect labels/schema defects, then implement independent declaration, call-site, and passage evaluation runners using the real indexers/retrievers. Add a small number of multi-file and ambiguous-identifier cases only after this initial suite is verified.


### Task-separated retrieval runners — implementation pending local verification, 2026-11-24

Added `nlp/tests/test_retrieval_task_benchmark_integration.py`. It uses the real `CodeSymbolIndexer`, `SourceChunkIndexer`, `CodeLexicalRetriever`, and `SourceChunkRetriever` over the nine-file `mini_repo_v2` fixture with an in-memory PostgREST double.

The runner evaluates three tasks independently:

- **Declaration discovery:** symbol identity and ranked declaration candidates.
- **Call-site/context discovery:** source-chunk range overlap against labeled call/use ranges.
- **Passage retrieval:** source-chunk range overlap against answer-bearing ranges.
- **No evidence:** all three negative queries must return no symbol or chunk candidates.

The report includes per-query candidate rankings, relevant ranks, Recall@1/5/10, MRR, index coverage counts, and no-evidence candidate counts. Tenant/repository/snapshot/revision provenance is asserted for every returned candidate.

**Not yet verified:** the integration runner has been committed but has not been executed locally. The fixture's static label validator passed (developer-reported: 4 passed in 0.02s); that does not establish that actual retrieval finds the labels. The in-memory PostgREST double is not PostgreSQL/RLS verification. The lexical query terms are explicit benchmark signals and should not be interpreted as natural-language query understanding.

**Next:** run the focused integration test, inspect every task's per-query rankings, correct only demonstrably wrong benchmark labels or runner defects, then run the full NLP suite. Do not add embeddings or RRF until the runner is verified and its failure modes are understood. KRT-03 remains **IN_PROGRESS**.


### Task-separated lexical and SCIP evaluation — verified 2026-11-25

The 33-query task-separated fixture and its integration runner have now been executed locally against the real symbol/chunk indexers and lexical retrievers using an in-memory PostgREST double.

**Lexical task metrics (developer-reported):**

| Task | Queries | MRR | Recall@1 | Recall@5 | Recall@10 |
|---|---:|---:|---:|---:|---:|
| Declaration discovery | 10 | 1.00 | 1.00 | 1.00 | 1.00 |
| Call-site/context discovery | 10 | 0.75 | 0.50 | 1.00 | 1.00 |
| Passage retrieval | 10 | 0.95 | 0.90 | 1.00 | 1.00 |

All three explicit no-evidence queries returned zero symbol and chunk candidates. The fixture indexed 29 symbols and 36 chunks across nine source files.

Call-site lexical retrieval has a clear limitation: five of ten relevant ranges rank second rather than first, commonly because a definition chunk and a reference chunk share the same identifier and lexical scoring/tie-breaking does not distinguish their semantic roles. Do not add arbitrary ranking boosts. Use SCIP exact-symbol references when symbol resolution and index coverage are available; retain lexical chunks as fallback and for passage retrieval.

**SCIP call-site benchmark (separate metric family):**

- Real `scip-python` 0.6.8 indexing produced 99 definitions, 152 references, and 251 total occurrences.
- Symbol resolution: 9/10 queries (90%); `call-06` remains unresolved for built-in/general terms `startswith` and `authorized`.
- On the nine resolved queries, expected-range coverage: 9/9 (100%).
- Occurrence precision: 9/13 (69.2%).
- The two typed cross-file calls in `api/orders.py` are correctly resolved after annotating the fixture's `OrderStore` dependency and correcting expected source lines.

SCIP reports coverage and precision, not ranked Recall@k/MRR. These metrics must not be compared numerically with lexical ranking metrics. The 69.2% precision also means additional occurrences are returned beyond the query-specific expected ranges; inspect this behavior in future realistic evaluations rather than applying arbitrary filtering.

**Verification — developer-reported, 2026-11-25:**

```text
KMS_SCIP_PYTHON_BENCHMARK=1 uv run pytest -q tests/test_scip_call_site_benchmark_integration.py -s
1 passed in 2.13s

uv run pytest -q tests/test_retrieval_task_benchmark_integration.py -s
1 passed

uv run pytest -q tests/test_retrieval_task_benchmark_fixture.py
4 passed in 0.04s

uv run pytest -q
299 passed, 5 skipped, 6 warnings, 4 subtests passed in 16.45s
```

The warnings are the existing `pythonjsonlogger` and PyGithub deprecations. The five skipped tests include opt-in integrations; this full-suite run does not replace separately executed SCIP or Supabase integration checks.

**Interpretation and limitations:** this is a useful task-separated deterministic lexical baseline, not production-quality evidence. It uses a nine-file synthetic Python corpus, explicit lexical query terms, hand-authored relevance labels, and an in-memory PostgREST double. It does not measure natural-language semantic retrieval, production-repository generalization, PostgreSQL query planning/RLS, or latency/cost. The separate SCIP run uses real index generation but an in-memory occurrence persistence/retrieval double.

**Decision:** retain the hybrid *candidate-source* architecture as complementary deterministic components: symbol lexical retrieval for declarations, SCIP for resolvable exact-symbol references, and source-chunk lexical retrieval for passage/context fallback. Keep structured answers separate. Do not add embeddings, RRF, or a reranker yet; first test this routing against a realistic repository and naturally phrased queries, and inspect SCIP's extra occurrences and lexical call-site rank-2 cases.

KRT-03 remains **IN_PROGRESS**. The acceptance criteria requiring independently evaluated semantic retrieval and measured fusion are not met.

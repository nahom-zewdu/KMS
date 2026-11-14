# KMS Knowledge Pipeline — Current State and Target Architecture

**Status:** Architecture audit / target direction  
**Reviewed:** 2026-11-14  
**Repository baseline:** `feat/implementation-relations`  
**Implementation status:** No KRT implementation has started  
**Milestone specification:** `docs/development/milestones/2026-11-14-knowledge-reliability.md`

## 1. Purpose and scope

This document describes how KMS currently collects, stores, analyzes, retrieves, and presents engineering knowledge, then defines the architecture direction for making those operations trustworthy. It is an engineering audit, not a claim that all listed components are production-ready.

## 2. Current system boundary

- **Go/Gin API (`api/`)**: Slack/GitHub webhook ingress, signature validation, tenant resolution, event persistence/publication, Redis job publication, and query bridge.
- **Python NLP (`nlp/`)**: Redis consumers, extraction, graph writes, event embeddings, query processing, codebase analysis/baseline indexing, playbooks, visualizer, and Ramp.
- **Redis Streams**: asynchronous job transport and consumer lifecycle.
- **Supabase/Postgres**: canonical application/knowledge records, graph tables, metadata, and pgvector.
- **GitHub / Slack**: current source systems.
- **Next.js frontend**: separate repository `nahom-zewdu/kms-frontend`; owns authentication, workspace, integrations, Ramp UI, and query interaction.

The existing stack is sufficient for the next architecture steps. Replacing it is not a prerequisite.

## 3. Current data lifecycle

### 3.1 Collection

GitHub and Slack deliver events through their respective integration/webhook paths. The Go API validates supported events, resolves company context, persists applicable event/raw records, and publishes asynchronous jobs to Redis Streams.

GitHub baseline sync separately enumerates repository files and records repository/file/module metadata. The current Ramp relationship work indexes Python and Go imports. Read-only Go route/handler/direct-operation extractors exist for evidence evaluation, but are not yet a general persisted multi-language index.

### 3.2 Storage

The current Postgres knowledge model includes raw source/event records (`events`, `raw_data`), extracted entities and relationships (`entities`, `edges`), repository and source inventory (`repositories`, `codebase_files`, `codebase_modules`), product artifacts such as `ramp_plans`, and vector embeddings on raw event records.

The previous live data audit reported 235 indexed files, 96 modules, 406 entities, 600 edges, and 140 raw records (139 embedded). These are point-in-time figures, not current counters. Indexed file rows are metadata, not a durable, revisioned source-code chunk store. Source text is fetched from GitHub on demand by the bounded source retriever.

### 3.3 Analysis

Current analysis includes entity/relation extraction from events, embeddings for raw records, file/module inventory, and Python/Go import extraction. Ramp's Go route/handler/direct-operation evidence extractors provide narrow source-level evidence, but they are read-only and not integrated into the durable index.

A structural import is not a runtime trace. A direct call to an interface method is not proof of its concrete implementation or runtime dispatch. Evidence types must retain these distinctions.

### 3.4 Retrieval and answer generation

Current query handling consists of several partially separate paths:
- deterministic/regex-oriented structured facts;
- knowledge-graph retrieval;
- vector similarity over embedded `raw_data`;
- limited keyword fallback over event records;
- bounded source-file retrieval that heuristically selects indexed paths and fetches source from GitHub;
- LLM answer synthesis.

There is no single typed query planner routing structured, code, graph, historical, and conversational questions through a coherent retrieval plan. There is no unified lexical + vector + graph candidate fusion or consistently validated claim-level citation pipeline.

Adding RAG alone is insufficient: KMS first needs reliable source data, tenant filters, query intent, and the correct retrieval method for each question.

## 4. Observed limitations

| Layer | Current limitation | Consequence |
|---|---|---|
| Collection | Baseline lifecycle and webhook events are separate paths; reconciliation/deletion semantics need verification | Stale or missing source state can persist |
| Source storage | No durable code-chunk snapshot index | Source retrieval depends on live GitHub access and bounded file selection |
| Code analysis | Imports are the main persisted implementation relation | Dependencies can be mistaken for behavior if labels overstate evidence |
| Language coverage | Persisted import extraction is Python/Go; Go route/call evidence is narrow and read-only | Frontend TypeScript/TSX and broader symbol relationships are absent |
| Retrieval | Event embeddings are not code embeddings | Semantic search cannot reliably find relevant source-code passages |
| Query routing | Structured facts, graph, vectors, and source retrieval are disconnected | Wrong tool, wrong scope, or generic answer |
| Ranking | No evaluated hybrid fusion/reranker pipeline | Relevant evidence may be missed or ranked poorly |
| Synthesis | Citation and claim support are not consistently validated | Unsupported answers can appear more certain than evidence warrants |
| Conversation | Follow-up and courtesy handling is inconsistent | Context can be lost or irrelevant evidence can be returned |
| Evaluation | No stable end-to-end gold benchmark | Regressions and improvements are hard to quantify |
| Security | Live RLS/grant/RPC audit reported possible tenant-boundary exposure | Must be re-audited and fixed before broad customer exposure |

## 5. Target architecture

```text
GitHub / Slack / future sources
          |
          v
  validated source adapters
          |
          v
 immutable raw events + sync checkpoints
          |
          v
 durable job processing / retries / replay
          |
          v
 canonical, revision-aware source records
          |
          +--> code parser / symbol index / typed relationships
          |
          +--> event/document extraction / entity resolution
          |
          v
  tenant-scoped knowledge stores
          |
          +--> SQL / structured facts
          +--> PostgreSQL FTS / identifiers / paths
          +--> pgvector semantic chunks
          +--> typed graph relationships
          |
          v
 typed query planner + scoped retrieval
          |
          +--> SQL
          +--> lexical search
          +--> vector search
          +--> graph traversal
          +--> source/symbol navigation
          |
          v
 candidate fusion + optional reranking
          |
          v
 evidence-bounded answer synthesis
          |
          v
 claim-level citations + validation / abstention
          |
          v
 Slack / Ramp / web UI
```

### 5.1 Canonical source and provenance model

Every derived item should be traceable to company/authorization scope; source system/object ID; repository and commit SHA for code; path, symbol, and line range; content hash and immutable version; ingestion/source timestamps; extractor/indexer version; embedding model/version; and evidence kind/confidence semantics.

Raw events should remain immutable. Derived records and indexes should be reproducible from source snapshots and versioned extractors.

### 5.2 Code intelligence

Use syntax-aware parsing (Tree-sitter or equivalent) for supported language structure. Evaluate SCIP indexers for precise definitions and references in supported languages. Add narrow extractors for route registration, handler resolution, calls, queues/events, persistence, and test references.

Do not claim generic call-graph or runtime-flow support from import edges. Runtime traces, static call evidence, inferred relations, and imports must be distinct types with explicit provenance.

### 5.3 Retrieval

Use Postgres as the initial unified retrieval substrate:
- SQL for exact structured questions and aggregations;
- PostgreSQL full-text search for text and identifiers;
- path/symbol indexes for exact source navigation;
- pgvector for semantically similar source chunks and engineering knowledge;
- graph traversal for typed, provenance-backed relationships.

Merge candidates with Reciprocal Rank Fusion (RRF) after each retriever is independently tested. Add a reranker only if benchmark results show ranking improvement worth its latency/cost. Apply tenant/repository/revision/permission constraints before evidence reaches synthesis.

### 5.4 Query planning and synthesis

A typed query plan should carry intent and answer shape; company and authorization context; repository/revision constraints; time range; references resolved from conversation state; and retrieval strategies/limits.

Structured counts and inventory use SQL. Code questions use path/symbol/source retrieval. Ownership and dependencies use typed graph facts plus history. Explanatory questions can use hybrid retrieval.

The LLM explains retrieved facts, not invent them. Validate each factual claim against evidence. Citations identify source type, repository/path, line range, commit SHA, or source-event/PR link. Abstain when required evidence is absent or ambiguous.

## 6. Security and tenant isolation

A read-only live Supabase audit reported:
- RLS disabled on `raw_data`, `edges`, `repositories`, `codebase_files`, `codebase_modules`, and `events`;
- broad grants to `anon` and `authenticated` on those tables;
- permissive `entities` policies using `USING (true)`;
- `match_documents` permits an omitted company filter;
- `search_edges_by_entity` lacks a company filter and its deployed signature does not match the Python caller's company-scoped invocation;
- both RPCs were executable by `anon` and `authenticated`.

This is a potential cross-tenant exposure, not evidence of an actual unauthorized read. Re-run the audit before changes. Verify Data API exposure, role privileges, function security mode/search path, and actual frontend/server/service-role access.

Tenant scope must be enforced in database policies and RPC contracts, not merely in UI filters or optional application parameters.

## 7. Why not install a RAG framework first?

RAG describes a retrieval-augmented generation pattern, not the full knowledge system. KMS already has vector retrieval over event records and a separate code-source retrieval path. The missing capability is the reliable end-to-end pipeline: canonical source snapshots, code-aware indexing, hybrid retrieval, typed query planning, provenance, claim validation, security, and evaluation.

Keep the existing stack. Adopt libraries only where they solve a measured subproblem. Do not add a second vector database, graph database, or orchestration framework before the Postgres-based design is benchmarked.

## 8. Delivery sequence

See `docs/development/milestones/2026-11-14-knowledge-reliability.md`:
1. KRT-00 — tenant isolation/security;
2. KRT-01 — durable source snapshots and provenance;
3. KRT-02 — code intelligence;
4. KRT-03 — hybrid retrieval;
5. KRT-04 — typed query planning and grounded synthesis;
6. KRT-05 — evaluation and observability.

KRT-00 is the only first implementation batch. Do not begin code chunk embeddings or retrieval redesign before the security gate is accepted.

## 9. Related documentation

- `docs/development/roadmap.md` — canonical progress ledger.
- `docs/development/milestones/2026-11-14-knowledge-reliability.md` — task specification and acceptance gates.
- `docs/architecture/overview.md` — system boundaries and runtime responsibilities.
- `docs/data/schema.md` — schema authority and historical snapshot.
- `docs/product/ramp-intelligence-model.md` — Ramp evidence semantics.
- `docs/decisions/ADR-004-imports-are-not-workflows.md` — import edges are not workflow proof.

# KMS Knowledge Reliability & Trust — Implementation Brief

**Status:** IN_PROGRESS — audit confirmed critical exposure; frontend hardening started
**Document date:** 2026-11-14
**Target implementation base:** merged `feat/ramp` at `68ad38f4d2b40f9e9cb535243f1a2dab4ab1ea9b`
**Implementation branch:** `feat/krt-00-tenant-isolation` (backend and frontend repositories)
**Execution ledger:** `docs/development/roadmap.md`
**Scope owner:** KMS core platform

---

## 1. Purpose

This milestone establishes a trustworthy knowledge pipeline so KMS can collect engineering data, preserve its provenance, analyze code and engineering activity, retrieve the right evidence, and answer questions with verifiable sources.

The objective is not to add a fashionable RAG framework. It is to make KMS reliably answer questions about a company's codebase and engineering history, and to give Ramp evidence strong enough to support useful onboarding guidance.

**Core outcome:** every important answer or Ramp recommendation should be grounded in company-scoped, revision-aware evidence; structured questions should use exact structured data; uncertain questions should abstain rather than invent.

## 2. Current milestone and handoff boundary

The current implementation branch is `feat/krt-00-tenant-isolation`, created from merged `feat/ramp` at `68ad38f4d2b40f9e9cb535243f1a2dab4ab1ea9b`. PR #21 merged the prior `feat/implementation-relations` work into `feat/ramp`.

The merge sequence is deliberate:

1. Finish and verify the current `feat/implementation-relations` branch.
2. Open/review/merge it into `feat/ramp`.
3. Verify the resulting `feat/ramp` head and its tests.
4. Create a new implementation branch from that merged `feat/ramp` head.
5. Begin KRT implementation on that new branch.

Do not implement KRT on the previous `feat/implementation-relations` branch.

PR #20 is historical context: it merged `feat/ramp` into `feat/implementation-relations`, the opposite direction from the next merge requested here. It is not evidence that the current branch has been merged back.

## 3. Audit baseline — what exists today

The current system is a useful foundation, not a complete code intelligence or RAG platform.

### Existing stack

- Go/Gin API for webhook ingress, tenant resolution, event persistence/publication, and query bridging.
- Python worker/FastAPI services for extraction, knowledge-graph writes, embeddings, query processing, baseline indexing, and Ramp generation.
- Redis Streams for asynchronous processing.
- Supabase PostgreSQL for application data, knowledge records, graph edges, and vector storage.
- pgvector with `all-MiniLM-L6-v2` embeddings for raw engineering-event records.
- GitHub and Slack as connected source systems.
- Separate Next.js frontend repository.

### Existing knowledge stores and indexes

The current data model includes raw events/messages, entities, edges, repositories, indexed files/modules, and persisted Ramp plans. The prior live audit found 235 indexed files across two repositories (129 in `nahom-zewdu/KMS`, 106 in `nahom-zewdu/kms-frontend`), 96 modules, 406 entities, 600 edges, and 140 raw records. These are a dated audit snapshot, not live counters or guaranteed current totals.

139 of those 140 raw records had embeddings at the time of that audit. Embeddings apply to raw event records; there is no separate persisted code-chunk embedding index in the audited implementation.

### Existing retrieval behavior

- Structured facts use deterministic matching/regex-oriented paths.
- Graph retrieval searches entity relationships with heuristic/fallback behavior.
- Vector retrieval searches embedded `raw_data` records, not source-code chunks.
- Keyword fallback is limited and does not constitute full-text search over the indexed codebase.
- Source retrieval is a separate path: it selects a small number of indexed file paths heuristically and fetches file contents from GitHub at query time, pinned to the Ramp baseline revision/default branch where available.
- This is not a unified hybrid retrieval pipeline, and the code source path is not persistent code RAG.

### Existing code intelligence

- File and module inventory exists.
- Python and Go import relationships are indexed.
- Ramp has read-only Go route/handler, direct handler-operation, and evidence-composition work.
- These signals are not yet a general multi-language symbol/reference/call graph.
- Import edges are structural dependencies, not proof of runtime workflows. ADR-004 remains authoritative.

### Known query-quality symptoms

The observed chat transcript includes incorrect company-wide counts when a repository-specific count was requested, failure to list connected repositories, failure to list Ramp steps, unsupported creator/owner conclusions, generic responses to follow-ups, and irrelevant evidence after courtesy messages. These are routing, structured-query, evidence-selection, and conversational-state failures—not problems that can be fixed by adding embeddings alone.

## 4. Critical security baseline — P0

A direct live Supabase permission/RLS audit reported the following risks:

- RLS disabled on `raw_data`, `edges`, `repositories`, `codebase_files`, `codebase_modules`, and `events`.
- Broad table privileges granted to `anon` and `authenticated` on those tables.
- `entities` has RLS enabled, but permissive policies using `USING (true)` do not establish company isolation.
- `match_documents` accepts an optional company filter; when omitted, it can search across companies.
- `search_edges_by_entity` has no company filter, while the Python caller supplies a company-scoping argument that does not match the deployed function signature.
- Both RPCs were reported executable by `anon` and `authenticated`.

This is a **potential cross-tenant exposure**, not a claim that unauthorized access was observed or exploited. Re-run the audit against the active project before changing policies. Confirm Data API exposure, service-role boundaries, and all actual application call paths.

**P0 release gate:** do not onboard real multi-tenant customer data until tenant isolation is enforced and cross-tenant tests prove it across tables, views, RPCs, and application endpoints.

## 5. Target architecture principles

1. **Postgres remains the canonical system of record.** Do not add a separate vector database or graph database without measured evidence that Postgres cannot meet the workload.
2. **Raw source records are immutable; derived artifacts are versioned and rebuildable.**
3. **Every artifact carries tenant, source, revision/version, provenance, and extractor/model version where applicable.**
4. **Structured questions use SQL and typed application queries.** Do not route counts, repository lists, or plan metadata through semantic RAG.
5. **Code questions use code-aware retrieval.** Retrieve files, symbols, references, and bounded source chunks with exact line/commit provenance.
6. **Semantic retrieval is one candidate source, not the answer engine.** Combine lexical, vector, graph, and structured retrieval.
7. **LLMs synthesize from retrieved evidence; they do not create company facts.**
8. **Claims and citations are validated.** Unsupported claims are omitted or explicitly marked unknown.
9. **Tenant scope is mandatory at every retrieval and persistence boundary.**
10. **Evaluation fixtures and regression tests are product infrastructure, not optional polish.**

## 6. Implementation phases and task IDs

### KRT-00 — Security and tenant isolation (P0)

**Goal:** close cross-tenant access paths before broad customer exposure.

- Re-audit live schema, grants, RLS policies, views, RPC signatures, and function privileges.
- Define the trusted server/service-role boundary and ensure browser-facing roles cannot bypass tenant checks.
- Add company-scoped predicates/authorization to every tenant-owned table and RPC.
- Correct `match_documents` and `search_edges_by_entity` contracts; reject missing tenant scope for tenant data.
- Add cross-tenant negative tests for direct table access, RPCs, and API routes.
- Verify behavior with the actual Supabase roles used by the application.
- Record migration and rollback plans; do not apply destructive schema changes ad hoc.

**Acceptance:** tenant A cannot read, search, mutate, or infer tenant B data through any exposed path; tests cover anon/authenticated/service-role behavior; migrations are reproducible and reviewed.

### KRT-01 — Canonical source snapshots and provenance

**Goal:** make indexed source evidence durable and revision-aware.

- Define canonical records for repository snapshots, file versions, source blobs/chunks, and provenance.
- Pin every code artifact to repository, commit SHA, path, content hash, and extractor version.
- Store source text/chunks durably (Postgres for metadata; object storage where size warrants).
- Implement incremental sync, deletion reconciliation, retry/replay, and idempotency.
- Prefer GitHub App installation-scoped tokens over a global personal token for customer repository access.
- Preserve immutable raw events and make derived indexes rebuildable.

**Acceptance:** a retrieved source item can be resolved to the exact repository commit and file content; deleted/renamed files do not remain falsely current; repeat syncs are idempotent.

### KRT-02 — Code intelligence

**Goal:** move beyond file inventory and import-only relationships.

- Add Tree-sitter parsing for supported language syntax and stable symbol extraction.
- Evaluate SCIP indexers for precise definitions/references in supported languages, starting with Go and TypeScript/JavaScript, then Python as supported by the chosen indexer/tooling.
- Extract routes, handlers, direct calls, queue publication/consumption, persistence operations, and test references with explicit provenance.
- Distinguish structural imports, static call evidence, inferred relationships, and runtime-observed behavior.
- Keep language coverage explicit; unsupported constructs must not be silently guessed.

**Acceptance:** symbol/file navigation and selected implementation paths are source-backed, revision-aware, tenant-scoped, and tested against representative Go, Python, and TypeScript repositories.

### KRT-03 — Hybrid retrieval

**Goal:** retrieve relevant evidence from the correct index for each question.

- Structured SQL for counts, repository inventory, Ramp metadata, and exact attributes.
- PostgreSQL full-text search for natural-language text and identifiers.
- Trigram/path indexes for exact paths and symbols.
- pgvector for semantic retrieval over appropriately chunked source and engineering knowledge.
- Graph traversal for typed, provenance-backed relationships.
- Merge candidate sets with Reciprocal Rank Fusion (RRF); evaluate reranking before adopting it.
- Keep filters (company, repository, revision, permissions) applied before/through candidate generation.

**Acceptance:** a curated benchmark demonstrates retrieval recall and ranking quality; repository-scoped queries never leak company-wide or cross-repository results.

### KRT-04 — Typed query planner and grounded answer synthesis

**Goal:** route each question to the right retrieval method and make answers evidence-bound.

- Build a typed query plan containing intent, company, repository, revision, time range, and conversational references.
- Route structured questions to SQL; code navigation to symbol/source retrieval; ownership/dependency to graph + history; explanation questions to hybrid retrieval.
- Resolve follow-ups using explicit conversation state without carrying stale or unrelated evidence into courtesy/ambiguous turns.
- Synthesize only after retrieval; attach citations at claim level (repository/path/line range/commit or source event/PR/Slack link).
- Validate citations and claim support; abstain on missing evidence.
- Preserve exact repository/company scope in both planning and execution.

**Acceptance:** structured benchmark questions are exact; source answers cite correct file/line/commit; unsupported questions abstain; follow-up tests cover pronouns, corrections, repository narrowing, and courtesy turns.

### KRT-05 — Evaluation and observability

**Goal:** make quality measurable and regressions visible.

- Turn the observed Ramp/query transcript into a versioned benchmark with expected answer, evidence, scope, and abstention behavior.
- Add curated answerable and unanswerable questions across repositories, code, ownership, history, and Ramp.
- Track retrieval Recall@K, MRR/NDCG, citation precision, answer correctness, faithfulness, and abstention accuracy.
- Add OpenTelemetry traces across frontend/API, Go, Redis, Python, Postgres, and LLM calls.
- Measure ingestion freshness, queue lag, index coverage, retrieval latency, model latency/cost, and failure rates.
- Use automated metrics as signals; keep human-reviewed gold answers as the acceptance authority.

**Acceptance:** every query-engine change runs the benchmark; quality changes are measured against a stable baseline; traces can identify the slow/failing stage.

## 7. Initial quality gates

These are proposed targets to calibrate against the first benchmark, not claims about current performance:

| Dimension | Initial target |
|---|---:|
| Tenant isolation tests | 100% pass; zero known bypass |
| Structured counts and inventory | 100% exact on benchmark |
| Repository/path scope | 100% correct on benchmark |
| Code retrieval Recall@10 | ≥ 90% |
| Citation validity | ≥ 95% |
| Claim faithfulness | ≥ 95% |
| Correct abstention | ≥ 95% |
| Revision provenance for code answers | 100% |

A metric is not accepted until its benchmark definition, sample size, and calculation are documented.

## 8. Explicit non-goals

- No wholesale replacement of Go/Python/Postgres/Redis.
- No automatic adoption of LangChain, LlamaIndex, Pinecone, Elasticsearch, or Neo4j by default.
- No embedding of every file without chunking, provenance, retrieval evaluation, and a clear use case.
- No autonomous agent that edits customer repositories.
- No generic call-graph/SSA/CFG project before the narrow source evidence proves value.
- No expanding Ramp candidate heuristics to compensate for missing source evidence.
- No production schema changes before KRT-00 audit and migration review.

## 9. Delivery and verification discipline

For every task, record:

- task ID and status in `docs/development/roadmap.md`;
- exact branch and commit;
- files/components changed;
- migration impact and rollback plan, if any;
- focused tests and full relevant suite;
- manual/live verification with tenant and repository scope;
- benchmark before/after where retrieval or answer quality changes;
- known limitations and deferred work.

Statuses follow the repository lifecycle: `PLANNED → SPECIFIED → IN_PROGRESS → IMPLEMENTED → VERIFIED → ACCEPTED`. An agent's completion report alone is not acceptance.

## 10. First execution step after merge

After the current branch is merged into `feat/ramp`, create a new branch from the resulting `feat/ramp` head. Start with **KRT-00 only**:

1. Re-run the live Supabase security audit read-only.
2. Map each exposed table/RPC to the actual app/service access path.
3. Design the smallest complete migration and test plan.
4. Implement the tenant-isolation correction and negative tests.
5. Verify using real database roles and application paths before moving to KRT-01.

Do not start KRT-01 or add code embeddings before KRT-00 is accepted.

---

## Change log

| Date | Change |
|---|---|
| 2026-11-14 | Initial implementation brief created from the current architecture/data/retrieval audit. No implementation or database changes are included in this document. |


## 11. KRT-00 live audit and implementation log — 2026-11-14

**Status:** IN_PROGRESS  
**Backend branch:** `feat/krt-00-tenant-isolation`  
**Frontend branch:** `feat/krt-00-tenant-isolation`  
**Database changes:** none applied

### Confirmed critical findings

The active Supabase project's Security Advisor and direct catalog inspection confirm:
- 11 public tables have RLS disabled while `anon` and `authenticated` have broad table privileges.
- `company_members` has public self-insert and self-update policies; the update policy has no `WITH CHECK`. This is a membership self-enrollment/role-escalation path.
- `entities` and `playbooks` have permissive public `USING (true)` policies; `companies` is also publicly readable.
- `match_documents` is executable by `anon` and `authenticated`, permits a NULL tenant filter, and has no fixed search_path.
- `search_edges_by_entity` is executable by browser roles, has no company filter, and its live signature differs from the Python caller.
- `reconcile_repository_files` and `replace_implementation_edges` are executable by browser roles. Repository reconciliation does not validate repository/company ownership before deletion.
- `company_integrations` has broad browser table grants despite storing access tokens, refresh tokens, and webhook secrets.

These findings establish potential unauthorized access and privilege escalation. They do not establish that exploitation occurred.

### Data integrity checks

Live read-only checks found 2 companies, 2 admin memberships, 422 entities, 611 edges, 153 raw records, 149 events, 237 codebase files, and 96 modules. Tenant IDs were present on all checked entities, edges, raw records, and events; edge endpoints had no cross-company mismatches; files/modules referenced existing repositories. `contributions` is empty and has no `company_id` column, despite current application code expecting one.

### Frontend changes committed

The frontend KRT branch now:
- requires authentication and active-company repository scope for `GET /api/codebase`;
- accesses integration metadata through the server-only admin client after explicit membership/role checks;
- requires authentication and active-company filtering for legacy `/onboard/[slug]` playbooks;
- documents why public role-slug playbook sharing is disabled until a revocable share-token mechanism exists.

Commits are on `nahom-zewdu/kms-frontend:feat/krt-00-tenant-isolation`. Build/lint/tests have not yet been run.

### Remaining work and acceptance

The database migration and SQL regression harness are not yet implemented. Next implementation batch is the migration and tests, not vector/RAG work. It must include table RLS/grants, membership policy correction, safe function privileges/search_path, tenant-required RPC contracts, repository ownership checks, and contribution schema drift.

KRT-00 remains **IN_PROGRESS**, not VERIFIED. No live SQL changes have been applied.

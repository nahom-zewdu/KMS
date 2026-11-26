# KRT-05 — Evaluation and Observability

**Status:** IN_PROGRESS — KRT-05.1 verified; KRT-05.2 implemented, pending local verification  
**Date:** 2026-11-26  
**Branch:** `feat/krt-05-evaluation`  
**Base:** merged `feat/ramp` after KRT-04 PR #29

## 1. Objective

Establish reproducible evidence that KMS retrieves the right repository evidence, preserves tenant/repository/snapshot provenance, produces claims supported by cited evidence, and abstains when evidence is insufficient.

KRT-04 implementation and unit tests are not evidence of end-to-end answer quality. KRT-05 must evaluate the complete supported path and make quality regressions visible before any retrieval/ranking expansion.

## 2. Existing evaluation assets — reuse, do not duplicate

The repository already contains useful retrieval-only assets:

- `nlp/tests/fixtures/retrieval/retrieval_tasks_v1.json`: 30 positive task queries (10 declaration, 10 call-site/context, 10 passage) plus 3 no-evidence queries over a nine-file synthetic Python repository.
- `nlp/tests/test_retrieval_task_benchmark_integration.py`: indexes the fixture with the production symbol/chunk indexers and evaluates the production lexical retrievers against an in-memory PostgREST double.
- `nlp/query_engine/lexical_benchmark.py`: Recall@1/5/10 and MRR for the narrower lexical-input contract.
- `nlp/tests/test_kms_nlp_repository_retrieval_benchmark.py`: opt-in benchmark against a bounded sample of real KMS Python source.
- `nlp/tests/test_scip_call_site_benchmark_integration.py`: opt-in real SCIP call-site benchmark.
- `nlp/query_engine/grounded_answer.py`: validates citation identity/membership, but deliberately does not establish semantic entailment.

These assets measure retrieval slices, not the full KRT-04 path. Keep their scopes and limitations explicit; do not report a retrieval-only metric as end-to-end answer quality.

## 3. Evaluation layers

### Layer A — retrieval quality

Reuse the existing task-separated benchmark. Preserve task-specific relevance definitions:

- Declaration discovery: expected symbol identity and expected file path are distinct labels.
- Call-site navigation: expected use/reference ranges, not just the declaration.
- Passage retrieval: answer-bearing source ranges, with overlap and exact-range diagnostics.
- No-evidence: expected empty retrieval and explicit downstream abstention.

Report per-task macro Recall@1/5/10, MRR, and nDCG@10 where graded labels are available. Do not merge task types into one headline score without also reporting per-task results.

### Layer B — scope and provenance (hard gates)

For every returned candidate and citation, validate:

- authenticated company ID;
- resolved repository ID;
- active snapshot ID and source revision;
- source identity and range consistency;
- citation evidence IDs belong to the exact retrieved evidence set.

Any cross-company, cross-repository, wrong-snapshot, wrong-revision, or unknown-citation event is a hard failure. Do not average security/provenance failures into a quality score.

The in-memory PostgREST fixture validates application query behavior only. It is not proof of PostgreSQL RLS, grants, or production database isolation. Actual Supabase role/RLS tests remain a separate security gate.

### Layer C — answer and claim support

Create a small manually reviewed answer benchmark for the supported KRT-04 route. Each item records:

- stable query ID, task type, and version;
- trusted company/repository/snapshot fixture scope;
- expected answerability (answerable / partially answerable / unanswerable);
- required evidence identities or source ranges;
- required factual points and explicitly forbidden/unsupported conclusions;
- expected abstention reason/category where applicable;
- one or more reference claims with evidence links.

Review generated claims against cited evidence using a fixed rubric:

| Grade | Meaning |
|---|---|
| 2 — supported | cited evidence directly supports the claim |
| 1 — partial | evidence supports only part of the claim or requires a clearly stated qualification |
| 0 — unsupported | evidence does not support the claim, contradicts it, or is unrelated |

A claim with citation membership but grade 0 is a semantic citation failure. This is the gap KRT-04's validator explicitly does not solve.

Avoid exact answer-string matching. Evaluate required facts, contradictions, evidence support, and abstention behavior. Use human review as the authority for claim support; automated LLM judges may be explored only as a secondary signal and must not become the sole acceptance criterion.

### Layer D — abstention and routing

Measure separately:

- correct abstention on no-evidence, unsupported, ambiguous-symbol, and ambiguous-repository cases;
- false abstention on answerable cases;
- incorrect answer on unanswerable cases;
- routing correctness for structured facts and conversation-control turns, which must remain on their established paths.

Report the confusion matrix and denominators. Do not collapse all abstentions into success.

### Layer E — operational measurements

For each stage, capture latency and bounded operational metadata:

- classification/planning;
- repository-scope resolution;
- retrieval/evidence gathering;
- synthesis;
- citation validation;
- total query duration.

For LLM calls, record model identifier, prompt version, input/output token counts when available, and estimated cost only when a documented pricing source is configured. Report p50/p95 only with sample count and run conditions.

Do not log secrets, access tokens, full source files, or unrestricted raw customer prompts/evidence. Default evaluation uses synthetic fixtures. Real-repository benchmark outputs must be opt-in and sanitized.

## 4. Dataset plan

### Seed set v1

Start with a compact manually reviewed set of approximately 24–30 end-to-end cases, reusing the existing 33 retrieval tasks rather than duplicating them:

- 5 declaration-discovery cases;
- 5 call-site navigation cases;
- 5 passage-retrieval cases;
- 3 no-evidence / unsupported cases;
- 2 ambiguous-symbol or ambiguous-repository cases;
- 2 structured-fact routing cases;
- 2 conversation-control / follow-up cases.

This is a smoke/regression seed set, not a statistically representative benchmark. Expand it only after measuring failure categories and obtaining reviewer agreement.

Each case must have explicit expected evidence and scope. Cases without reviewed ground truth are marked draft and excluded from aggregate metrics.

### Annotation quality

- Keep labels separate from implementation output.
- Record annotator, review date, dataset version, and rationale.
- Double-review claim-support labels for the initial seed set where feasible; adjudicate disagreements rather than averaging them away.
- Preserve hard negatives and near-miss evidence.
- Do not use generated model answers as gold labels without independent review.

## 5. Reproducible report contract

Each benchmark run emits a machine-readable JSON report containing:

- benchmark name/version and dataset hash;
- KMS git commit, retrieval/indexer/chunker versions, model ID, and prompt version where applicable;
- run timestamp, environment identifier, and sample counts;
- per-task metrics and per-query outcomes;
- provenance/scope violation counts;
- citation-membership and claim-support outcomes;
- abstention confusion matrix;
- stage latency distributions and token/cost fields when available;
- unsupported/excluded cases and reasons.

Reports must not contain secrets or raw source content. Store deterministic fixture reports as versioned artifacts; store real-repository reports only when sanitized and explicitly reviewed.

## 6. Initial acceptance gates

These are protocol gates for the first evaluation harness, not claims about current quality:

1. Every scored query has reviewed expected evidence and an explicit scope.
2. All existing retrieval benchmark tasks remain independently reported; unsupported queries are not counted as misses.
3. All scope/provenance violations are zero in the synthetic integration run.
4. Citation-membership violations are zero for accepted answers; invalid citations must result in abstention.
5. Claim-support grades are reported per claim and per query; no automatic semantic-support threshold is asserted until the seed set is reviewed.
6. Abstention metrics include explicit answerable and unanswerable denominators.
7. Reports are deterministic for retrieval-only runs and identify model/prompt versions for LLM runs.
8. Latency/token metrics include sample count and environment; no p95 is claimed from a single observation.
9. The harness runs offline against synthetic fixtures in CI; live/real-repository runs remain opt-in.
10. No embeddings, RRF, reranking, or broad QueryEngine rewrite is introduced by this milestone's first slice.

## 7. Implementation sequence

### KRT-05.1 — benchmark contract and reviewed seed dataset

- Define typed dataset/report contracts and schema validation.
- Add the end-to-end seed dataset with explicit scope, answerability, evidence labels, required facts, and expected abstention categories.
- Reuse existing retrieval fixtures by reference/ID where possible; do not copy their query corpus into a second source of truth.
- Add fixture integrity tests (all paths/ranges/symbols resolve; all query IDs unique; all scopes valid).
- Produce a baseline report for deterministic retrieval and a clear placeholder for not-yet-evaluated synthesis.

### KRT-05.2 — offline planned-query evaluator

- Exercise the KRT-04 planned-query executor with injected deterministic synthesizer outputs and no live LLM or database writes.
- Score expected intent/route, evidence recall against linked retrieval-fixture labels, provenance, citation membership, and abstention category.
- Keep live LLM generation out of the default CI path. Treat this as a planned-executor harness, not a complete API/worker integration test.

### KRT-05.3 — claim-support review and LLM run capture

- Add a reviewable claim/evidence annotation artifact and report.
- Run opt-in LLM evaluation on the same fixed evidence set.
- Capture model/prompt/tokens/latency and human-reviewed claim support.

### KRT-05.4 — observability integration

- Add structured stage timings and correlation IDs across API/worker/query path.
- Add safe counters for failures, abstentions, scope rejections, and retrieval outcomes.
- Only add distributed tracing dependencies after confirming existing logging/metrics infrastructure and deployment constraints.

## 8. Explicit non-goals

- Embeddings, RRF, reranking, or changing retrieval algorithms before evaluation identifies a measured gap.
- Treating synthetic fixture results as production generalization.
- Claiming semantic entailment from citation membership.
- Using an LLM judge as the only quality authority.
- Persisting customer prompts/source content in telemetry.
- Fixing the separate Supabase RLS/security release gate as part of evaluation.

## 9. First implementation task

Implement KRT-05.1 and KRT-05.2 in order. Keep all seed labels in draft until independently reviewed. Do not add production telemetry or change the query pipeline in these slices.

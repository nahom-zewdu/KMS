# KRT-05 Seed Dataset — Human Review Protocol

**Dataset:** `kms-krt05-end-to-end-seed` v1.0.0  
**Cases:** 24  
**Status:** Review required; no case is approved by this document.

## Purpose

This protocol defines how to independently approve or reject the end-to-end seed labels in `nlp/tests/fixtures/evaluation/krt05_seed_v1.json`. The benchmark is a small synthetic regression set, not a representative sample of customer traffic.

Do not mark a case `reviewed` merely because its expected route or answer looks plausible. Verify it against the referenced source/evidence fixture and the intended product boundary.

## Current case inventory

| Task type | Cases | IDs |
|---|---:|---|
| Declaration discovery | 5 | `seed-decl-01`–`seed-decl-05` |
| Call-site navigation | 5 | `seed-call-01`–`seed-call-05` |
| Passage retrieval | 5 | `seed-passage-01`–`seed-passage-05` |
| No evidence | 3 | `seed-no-evidence-1`–`seed-no-evidence-3` |
| Ambiguous scope | 2 | `seed-ambiguous-repository`, `seed-ambiguous-symbol` |
| Unsupported intent | 2 | `seed-unsupported-ownership`, `seed-unsupported-runtime` |
| Structured fact | 1 | `seed-structured-count` |
| Conversation control | 1 | `seed-followup-context` |

The case mix above is the actual checked-in fixture. It differs from the initial design target: there is one structured-fact and one conversation-control case, with two unsupported-intent cases. Do not describe the fixture as having two cases in each of those first two categories.

## Review procedure

For each case:

1. Open the case in the seed JSON and follow every `retrieval_case_id` into `nlp/tests/fixtures/retrieval/retrieval_tasks_v1.json`.
2. Inspect the referenced source file/range in the synthetic corpus. Verify the expected symbol, call-site range, or passage actually supports the question.
3. Check the expected company, repository, snapshot, and source revision. These must agree with the retrieval fixture for cases that expect repository evidence.
4. Independently assess whether the question is answerable from the supplied evidence. Do not infer facts that are absent from the fixture.
5. Verify every required fact is precise and observable in the source. Add forbidden claims for tempting but unsupported conclusions.
6. For abstention cases, verify the expected reason is the correct failure category—not simply that the case is difficult.
7. For structured-fact and conversation-control cases, verify that the expected route belongs to the existing structured/conversation handler rather than the planned code-evidence route.
8. Record a concise rationale explaining the decision and any correction needed.

If any evidence link, scope field, expected fact, or abstention label is wrong or ambiguous, leave the case in `draft` and correct the benchmark fixture before approving it.

## Approval rules

- `review_status: "reviewed"` means the case's question, scope, answerability, expected route, evidence links, required facts, forbidden claims, and abstention expectation were all independently checked.
- `reviewer`, `reviewed_on`, and `rationale` must be populated for reviewed cases.
- Keep rejected cases as `rejected`; do not delete them merely to improve benchmark scores.
- Draft and rejected cases remain excluded from evaluator aggregates.
- Do not generate or infer review metadata from model output.
- If feasible, have a second reviewer independently assess claim/evidence support. Resolve disagreements explicitly; do not average grades.


## Pre-review consistency audit — 2026-11-26

The seed was compared against all 15 linked retrieval labels, the nine-file synthetic source corpus, the duplicate-symbol source pair, and the structured repository fixture.

Corrections made before any case can be approved:

- Replaced generic call-site and passage expected-fact text with observable source behavior. These now state the actual call relationship or calculation/branch behavior to check.
- Reframed the unsupported-ownership query as a concrete ownership/approval question and added an explicit forbidden inference.
- Reworded the ambiguous-repository query as a natural repository-location question. The absence of repository/snapshot/revision scope remains intentional.
- Made the structured repository-count case company-scoped: repository, snapshot, and source revision are null because the question asks for a company-wide count. The benchmark contract now rejects repository-specific scope for this task type.

Review notes:

- The ambiguous-symbol case's canonical production reason is `ambiguous_declaration`; the evaluator already accepts this as the implementation-level reason for the benchmark category `ambiguous_symbol`. These are category-versus-runtime names, not a mismatch.
- The 15 linked retrieval references resolve to the correct task types. The referenced source ranges align with the checked-in nine-file corpus.
- The two duplicate `process_task` declarations are present in separate fixture files. The structured fixture contains two distinct repository IDs for the benchmark company.
- The conversation-control case contains prior context and a reference, but its behavior still needs explicit review against the conversation handler contract.
- The unsupported-runtime case remains a deliberately conservative static-analysis boundary: the source fixture does not define payment-provider outage behavior.

**Approval status remains unchanged:** all 24 cases are draft; no reviewer identity/date or claim-support grades have been fabricated. This audit is preparation, not independent human approval. A reviewer must still inspect each case and confirm its answerability, route, evidence, required/forbidden facts, and abstention behavior.

## Claim-support annotation

Use `nlp/tests/fixtures/evaluation/krt05_claim_reviews_v1.json` for actual generated-claim annotations. Each annotation must identify the exact case and claim, list the exact `cited_evidence_ids` from that generated claim, and include exactly one assessment for every cited ID (no missing or extra assessments). Each assessment must explain its grade:

| Grade | Meaning |
|---:|---|
| 2 | Cited evidence directly supports the claim |
| 1 | Evidence supports only part of the claim or requires qualification |
| 0 | Evidence is unrelated, contradictory, or does not support the claim |

The overall claim grade is a human judgment. Citation-ID membership alone is not semantic support. Only set `status: "reviewed"` after the assessment is complete and reviewer/date metadata are supplied.

## Reporting constraints

- Report reviewed and excluded denominators beside every metric.
- Keep task-type results separate; this seed is too small for broad aggregate quality claims.
- Report scope/provenance violations as hard failures, not as an average quality penalty.
- A successful synthetic test run is not evidence of production generalization.
- Do not use live customer prompts, private source code, secrets, or credentials in this checked-in fixture.
- Do not claim KRT-05 quality acceptance while no independently reviewed cases or claim annotations exist.

## Local validation

After editing labels, run:

```bash
uv run pytest -q \
  tests/test_krt05_benchmark_contract.py \
  tests/test_krt05_planned_query_evaluator.py \
  tests/test_krt05_claim_review.py
```

Then run the full NLP suite. Include the exact results and commit in the milestone record; do not replace earlier results without preserving their context.


## Annotation completeness invariant

The claim-review schema enforces a one-to-one match between `cited_evidence_ids` and assessment evidence IDs. An annotation cannot be considered structurally valid if a citation is omitted from review or an uncited evidence item is graded. This prevents reviewers from selectively assessing only favorable citations. The invariant is covered by tests for missing, extra, and duplicate IDs.

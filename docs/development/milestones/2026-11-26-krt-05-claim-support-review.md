# KRT-05.3 — Human claim-support review

**Status:** IMPLEMENTED — pending local verification  
**Branch:** `feat/krt-05-evaluation`

## Purpose

KRT-04 validates that citations refer to evidence returned for the current query. That is citation membership, not semantic support. This slice adds a separate human annotation contract; it does not generate labels or claim that the current seed has been reviewed.

## Rubric

Each cited evidence item receives an independent grade:

- **2 — supported:** directly supports the claim.
- **1 — partial:** supports only part of the claim or requires qualification.
- **0 — unsupported:** unrelated, contradictory, or does not support the claim.

The reviewer also records an overall claim grade, rationale, reviewer identity, and review date. A reviewed annotation without reviewer metadata is invalid. Draft and rejected annotations are excluded from aggregate rates.

## Artifacts

- `nlp/evaluation/claim_review.py`: strict immutable annotation contract and summary metrics.
- `nlp/tests/fixtures/evaluation/krt05_claim_reviews_v1.json`: intentionally empty annotation file; no synthetic labels are presented as human judgments.
- `nlp/tests/test_krt05_claim_review.py`: contract and aggregation tests.

## Limits

The report is descriptive, not a model-quality score until claims are independently annotated. Multiple evidence items are graded separately so a claim cannot hide one irrelevant citation behind another supporting citation. Reviewer agreement/adjudication and opt-in LLM run capture remain future work. Never include customer secrets or unrestricted source text in committed annotations.

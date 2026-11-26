# KRT-04.5 — Claim-Level Grounded Synthesis and Citation Validation

**Status:** IMPLEMENTED — PENDING LOCAL VERIFICATION  
**Date:** 2026-11-26  
**Branch:** `feat/krt-04-evidence-gathering`

## Goal

Define a strict boundary between model-generated factual claims and the evidence records gathered by KRT-04.4. Every accepted claim must cite one or more exact retrieved evidence identities. Public source references are derived from those evidence records, never trusted from model output.

## Changes

- Added `nlp/query_engine/grounded_answer.py`:
  - `GroundedClaim` and `GroundedAnswerResult` immutable contracts.
  - `GroundedAnswerValidator` parses JSON output and validates claim structure, bounded text/counts, citation count, and exact evidence-ID membership.
  - Rejects unknown or invented citation IDs and fails closed on malformed/empty claims.
  - Derives source references from the matched `EvidenceCandidate` objects.
  - Emits claim-level `evidence_ids` alongside the existing answer/sources/owners/abstain_reason shape.
- Added `reasoning_synthesize_grounded` to `nlp/query_engine/synthesizer.py`:
  - Sends only bounded evidence records to the existing LLM boundary.
  - Requests JSON claims with exact evidence IDs.
  - Treats retrieved code/docs as untrusted data, not instructions.
  - Model output is not trusted until it passes through `GroundedAnswerValidator`.
- Added `nlp/tests/test_grounded_answer.py` for valid citations, invented IDs, malformed claims, empty claims, output bounds, duplicate citations, confidence normalization, and JSON-string parsing.

## Important limitation

Citation validation proves that a cited ID belongs to the evidence set supplied to the synthesizer. It does **not** prove that the evidence semantically entails the claim. The model can still attach a real but irrelevant evidence ID to a claim. Claim-evidence entailment needs a separate evaluation/verification stage and must not be implied by this milestone.

## Verification

Pending local execution:

```bash
uv run pytest -q tests/test_grounded_answer.py
uv run pytest -q
```

## Boundaries

No production QueryEngine routing change, database write, migration, embedding, RRF, or broad synthesis replacement is included. The legacy answer path remains untouched until a later integration slice has an explicit compatibility and fallback design.

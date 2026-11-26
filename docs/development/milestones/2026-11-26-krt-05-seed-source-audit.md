# KRT-05 Seed Dataset — Source and Label Audit

**Date:** 2026-11-26  
**Scope:** Static cross-check of the 24 end-to-end seed cases against the checked-in 9-file synthetic repository and the 33-query KRT-03 retrieval fixture.  
**Disposition:** Audit findings only. This is not independent human approval; no case is marked reviewed.

## Summary

The seed fixture is structurally consistent in its top-level scope and case count, and most positive examples point to real declarations or answer-bearing code. The cross-check found several label-quality issues that should be resolved before any case is approved. In particular, two call/passage ranges are broader or misaligned with the specific question, and two control cases cannot currently be validated from the synthetic corpus as written.

## Findings

### F-01 — Call-site range includes the docstring and misses the actual callee call

- **Case:** `seed-call-03` / retrieval case `call-03`
- **Question:** “Where are alternative product recommendations normalized?”
- **Current range:** `catalog/search.py:14-15`
- **Source facts:** In the checked-in file, line 13 declares `recommend_alternatives`, line 14 is its docstring, line 15 assigns `normalized = normalize_sku(sku)`, and line 16 calls `catalog.find_alternatives(normalized)`.
- **Assessment:** The current range includes the docstring and normalization assignment but does not include the actual alternative lookup. If the target is normalization, label line 15 (or the minimal relevant context); if the target is the complete recommendation operation, include line 16 and clarify the question/required fact.
- **Action:** Tighten the range and align the question with the intended evidence target.

### F-02 — Payment authorization range is broader than the asked condition

- **Case:** `seed-passage-05` / retrieval case `passage-05`
- **Question:** “What condition makes a payment authorization invalid?”
- **Current range:** `billing/payment.py:3-7`
- **Source facts:** The invalidity condition is `amount <= 0` at line 5 and the invalid result is returned at line 6. Lines 3-4 define/document the function; line 7 is the successful authorization path.
- **Assessment:** The full function is answer-bearing context, but the benchmark label is unnecessarily broad for this narrowly phrased question.
- **Action:** Prefer lines 5-6 as the primary range; optionally preserve the function signature as a separate context range if the benchmark explicitly scores contextual retrieval.

### F-03 — Refund invalid-amount range labels the entire function

- **Case:** Not currently included in the 24-case end-to-end seed; related retrieval case `passage-06`
- **Question:** “How does refund validation reject an invalid amount?”
- **Current range:** `billing/payment.py:13-17`
- **Source facts:** The invalidity condition is line 15 and the rejection is line 16. Line 17 is the valid-amount path.
- **Assessment:** The KRT-03 retrieval fixture's label is too broad for the question and includes the success path.
- **Action:** Correct the upstream retrieval label to lines 15-16 before using this query in a future end-to-end seed revision.

### F-04 — Ambiguous-symbol case has no matching declarations in the corpus

- **Case:** `seed-ambiguous-symbol`
- **Question:** “Find the declaration of `process_task` where multiple declarations share that identifier.”
- **Corpus:** The nine checked-in files cover catalog, billing, notifications, storage, API, and token operations. The source files do not define `process_task`.
- **Assessment:** The case asserts multiple exact candidates, but the fixture does not contain those candidates. As written, the expected `ambiguous_symbol` result cannot be distinguished from `declaration_not_found`.
- **Action:** Add a dedicated synthetic ambiguity fixture containing at least two distinct declarations with the same identifier and explicit scope, or change the case to expect no declaration evidence. Do not approve the current label.

### F-05 — Structured repository-count case lacks authoritative fixture data

- **Case:** `seed-structured-count`
- **Question:** “How many repositories are connected to this company?”
- **Expected route:** `structured_handler`
- **Required fact:** Exact count from authoritative structured data.
- **Assessment:** The checked-in code corpus and retrieval fixture do not define the authoritative company/repository records or expected count. The routing expectation is plausible, but the answerability and exact expected fact cannot be verified from this benchmark's supplied data.
- **Action:** Add a small explicit structured-data fixture with the company and repository records plus expected count, or convert this into a routing-only case that does not claim an answerable exact count.

### F-06 — Ambiguous-repository scope mixes an absent repository with snapshot metadata

- **Case:** `seed-ambiguous-repository`
- **Scope:** Repository ID is null while snapshot ID and source revision are populated.
- **Assessment:** This may be intentional to test fail-closed repository selection, but snapshot/revision metadata normally belongs to a selected repository snapshot. The fixture currently represents a partially contradictory scope.
- **Action:** Keep the expected abstention, but make the contract explicit: either model the snapshot fields as absent until repository selection, or document that they are deliberately untrusted hints that must not be used to resolve the repository.

## Checks that passed at static-inspection level

- The 24 case IDs are unique and the case-level company/repository/snapshot/revision values agree with the declared default scope wherever a repository is selected.
- The 15 positive cases included in the seed map to existing retrieval query IDs and source paths.
- The three no-evidence questions target concepts not represented in the nine-file synthetic repository.
- The follow-up case includes a prior user/assistant exchange and an explicit conversation reference; its expected behavior is to resolve only from that bounded context or request clarification.
- The seed's 24-case category distribution matches the review protocol.

These are static fixture checks, not execution results or human approval.

## Approval decision

**Do not approve the affected cases yet.** In particular, F-04 and F-05 are blockers because the expected behavior/fact is not grounded in the current fixture. F-01 through F-03 need label-range refinement. F-06 needs an explicit scope interpretation.

No `review_status`, reviewer identity, review date, or claim-support grade was changed by this audit.

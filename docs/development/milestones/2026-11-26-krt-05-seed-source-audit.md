# KRT-05 Seed Dataset — Source and Label Audit

**Date:** 2026-11-26  
**Scope:** Static cross-check of the 24 end-to-end seed cases against the checked-in synthetic repository, retrieval labels, and evaluation-only control fixtures.  
**Disposition:** Audit findings and fixture corrections. This is not independent human approval; no case is marked reviewed.

## Corrections made after the initial audit

The initial audit incorrectly described `call-03` as having a range that missed its call. Recounting the actual source lines shows that `catalog/search.py:14-15` correctly covers both the normalization assignment and `find_alternatives` call. **F-01 is retracted.** This correction is recorded explicitly rather than leaving a false finding in the audit trail.

Two passage labels were too broad and have been narrowed in `retrieval_tasks_v1.json`:
- `passage-05`: `billing/payment.py:5-6` (invalid-amount condition and return).
- `passage-06`: `billing/payment.py:15-16` (invalid-refund condition and rejection).

The seed's ambiguous-symbol case is now backed by a dedicated two-file ambiguity fixture, and the structured repository-count case is backed by explicit synthetic authoritative data. The relevant integrity tests are added alongside the fixtures.

## Findings and disposition

### F-02 — Payment authorization range was broader than the asked condition — FIXED

- **Case:** `seed-passage-05` / retrieval case `passage-05`
- **Question:** “What condition makes a payment authorization invalid?”
- **Correct range:** `billing/payment.py:5-6`
- **Reason:** These lines contain the `amount <= 0` condition and its invalid result. The successful authorization path is excluded.

### F-03 — Refund invalid-amount range labeled the entire function — FIXED

- **Retrieval case:** `passage-06`
- **Question:** “How does refund validation reject an invalid amount?”
- **Correct range:** `billing/payment.py:15-16`
- **Reason:** These lines contain the invalid-amount condition and rejection. The valid-amount path is excluded.

### F-04 — Ambiguous-symbol case lacked matching declarations — FIXED AT FIXTURE LEVEL

- **Case:** `seed-ambiguous-symbol`
- **Question:** “Find the declaration of `process_task` where multiple declarations share that identifier.”
- **Correction:** Added two separate evaluation-only Python modules defining `process_task`. Contract tests assert that both declarations exist. These files are deliberately separate from the retrieval corpus so they do not silently alter the KRT-03 retrieval benchmark.
- **Remaining limitation:** The fixture establishes a valid ambiguity scenario, but production resolver behavior must still be exercised by a dedicated integration test before this case can be approved.

### F-05 — Structured repository-count case lacked authoritative fixture data — FIXED AT FIXTURE LEVEL

- **Case:** `seed-structured-count`
- **Question:** “How many repositories are connected to this company?”
- **Correction:** Added a versioned synthetic structured-data fixture containing exactly two repository records for `benchmark-company`. The seed's required fact now states that expected count.
- **Remaining limitation:** The fixture is ground truth for the benchmark only; it does not prove the live structured handler reads equivalent authoritative records. That route needs an injected integration test before approval.

### F-06 — Ambiguous-repository scope mixes an absent repository with snapshot metadata — OPEN

- **Case:** `seed-ambiguous-repository`
- **Scope:** Repository ID is null while snapshot ID and source revision are populated.
- **Assessment:** This is internally inconsistent if those fields are trusted snapshot metadata. It can be retained only if explicitly treated as untrusted hints that must not resolve repository selection.
- **Action required:** Model snapshot/revision as absent for this case, or document and test that these values are ignored until a repository is resolved. Do not approve the case until that interpretation is explicit.

## Static checks

- The 24 case IDs remain unique.
- Positive retrieval labels continue to reference existing retrieval query IDs and task types.
- The call-site range for `call-03` is valid: `catalog/search.py:14-15` includes the normalization assignment and actual `find_alternatives` call.
- The duplicate-symbol fixture contains two declarations by construction and is excluded from the retrieval corpus.
- The structured count fixture contains two records for the benchmark company.
- All cases remain draft; this audit does not create reviewer identity, review date, or claim-support grades.

## Approval decision

The two source-label corrections and two missing-fixture issues have been addressed at fixture level. **The ambiguous-repository case remains open.** None of these changes constitute independent human approval or establish semantic claim support.

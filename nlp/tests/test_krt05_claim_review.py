from __future__ import annotations

import pytest
from pydantic import ValidationError

from evaluation.claim_review import (
    ClaimReview,
    ClaimReviewDataset,
    summarize_claim_reviews,
)


def _review(**overrides):
    values = {
        "annotation_id": "ann-1",
        "case_id": "seed-01",
        "claim_id": "claim-1",
        "claim_text": "The handler validates the request.",
        "cited_evidence_ids": ["ev-1", "ev-2"],
        "assessments": [
            {"evidence_id": "ev-1", "grade": 2, "rationale": "Directly shown."},
            {"evidence_id": "ev-2", "grade": 1, "rationale": "Supports only part."},
        ],
        "overall_grade": 2,
        "status": "reviewed",
        "reviewer": "reviewer@example.test",
        "reviewed_on": "2026-11-26",
        "rationale": "The core claim is supported.",
    }
    values.update(overrides)
    if isinstance(values.get("assessments"), list):
        values["assessments"] = tuple(values["assessments"])
    if isinstance(values.get("cited_evidence_ids"), list):
        values["cited_evidence_ids"] = tuple(values["cited_evidence_ids"])
    return ClaimReview.model_validate(values)


def test_reviewed_claim_requires_reviewer_and_date():
    with pytest.raises(ValidationError):
        _review(reviewer=None)


def test_unreviewed_claim_cannot_claim_review_metadata():
    with pytest.raises(ValidationError):
        _review(status="draft", reviewer="reviewer@example.test")


def test_duplicate_evidence_assessments_are_rejected():
    with pytest.raises(ValidationError):
        _review(assessments=[
            {"evidence_id": "ev-1", "grade": 2, "rationale": "A"},
            {"evidence_id": "ev-1", "grade": 1, "rationale": "B"},
        ])


def test_summary_excludes_draft_and_rejected_annotations():
    reviewed = _review()
    draft = _review(
        annotation_id="ann-2", status="draft", reviewer=None, reviewed_on=None,
    )
    rejected = _review(
        annotation_id="ann-3", status="rejected", reviewer=None, reviewed_on=None,
    )
    dataset = ClaimReviewDataset(
        schema_version=1,
        dataset_id="kms-krt05-end-to-end-seed",
        dataset_version="1.0.0",
        reviews=(reviewed, draft, rejected),
    )

    report = summarize_claim_reviews(dataset)

    assert report["reviewed_claims"] == 1
    assert report["excluded_annotations"] == 2
    assert report["claim_grade_counts"] == {"0": 0, "1": 0, "2": 1}
    assert report["evidence_pair_grade_counts"] == {"0": 0, "1": 1, "2": 1}
    assert report["supported_claim_rate"] == 1.0
    assert report["evidence_pair_supported_rate"] == 0.5


def test_empty_review_dataset_reports_unavailable_rates():
    dataset = ClaimReviewDataset(
        schema_version=1,
        dataset_id="kms-krt05-end-to-end-seed",
        dataset_version="1.0.0",
        reviews=(),
    )

    report = summarize_claim_reviews(dataset)

    assert report["reviewed_claims"] == 0
    assert report["supported_claim_rate"] is None
    assert report["evidence_pair_supported_rate"] is None



def test_review_requires_assessment_for_every_cited_evidence_item():
    with pytest.raises(ValidationError, match="every cited evidence ID"):
        _review(assessments=(
            {"evidence_id": "ev-1", "grade": 2, "rationale": "Directly shown."},
        ))


def test_review_rejects_assessments_for_uncited_evidence():
    with pytest.raises(ValidationError, match="every cited evidence ID"):
        _review(
            cited_evidence_ids=("ev-1",),
            assessments=(
                {"evidence_id": "ev-1", "grade": 2, "rationale": "Directly shown."},
                {"evidence_id": "ev-2", "grade": 1, "rationale": "Not cited."},
            ),
        )


def test_review_rejects_duplicate_cited_evidence_ids():
    with pytest.raises(ValidationError, match="cited evidence IDs must be unique"):
        _review(cited_evidence_ids=("ev-1", "ev-1"))

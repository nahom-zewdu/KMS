"""Human-reviewed semantic support annotations for KRT-05.

This module records claim-to-evidence judgments. It deliberately does not
generate labels or infer semantic support automatically.
"""
from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SupportGrade = Literal[0, 1, 2]


class ReviewModel(BaseModel):
    """Strict immutable review data; unknown fields indicate annotation drift."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ClaimEvidenceAssessment(ReviewModel):
    """Human judgment for one claim/evidence pair."""

    evidence_id: str = Field(min_length=1, max_length=256)
    grade: SupportGrade
    rationale: str = Field(min_length=1, max_length=1_000)


class ClaimReview(ReviewModel):
    """One generated claim reviewed against its cited evidence."""

    annotation_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1, max_length=64)
    claim_id: str = Field(min_length=1, max_length=128)
    claim_text: str = Field(min_length=1, max_length=2_000)
    cited_evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    assessments: tuple[ClaimEvidenceAssessment, ...] = Field(min_length=1, max_length=8)
    overall_grade: SupportGrade
    status: Literal["draft", "reviewed", "rejected"] = "draft"
    reviewer: str | None = Field(default=None, max_length=128)
    reviewed_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    rationale: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_review_metadata(self) -> "ClaimReview":
        if self.status == "reviewed":
            if not self.reviewer or not self.reviewed_on:
                raise ValueError("reviewed annotations require reviewer and reviewed_on")
        elif self.reviewer is not None or self.reviewed_on is not None:
            raise ValueError("unreviewed annotations cannot claim reviewer metadata")
        cited_ids = list(self.cited_evidence_ids)
        if any(not item or len(item) > 256 for item in cited_ids):
            raise ValueError("cited evidence IDs must be non-empty and bounded")
        if len(cited_ids) != len(set(cited_ids)):
            raise ValueError("cited evidence IDs must be unique")
        assessed_ids = [item.evidence_id for item in self.assessments]
        if len(assessed_ids) != len(set(assessed_ids)):
            raise ValueError("evidence assessments must have unique evidence IDs")
        if set(assessed_ids) != set(cited_ids):
            raise ValueError("every cited evidence ID must have exactly one assessment")
        return self


class ClaimReviewDataset(ReviewModel):
    """Versioned annotation artifact tied to one benchmark dataset version."""

    schema_version: Literal[1]
    dataset_id: str = Field(min_length=1, max_length=100)
    dataset_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    reviews: tuple[ClaimReview, ...] = Field(max_length=2_000)

    @model_validator(mode="after")
    def validate_unique_annotations(self) -> "ClaimReviewDataset":
        ids = [item.annotation_id for item in self.reviews]
        if len(ids) != len(set(ids)):
            raise ValueError("annotation IDs must be unique")
        return self

    @property
    def reviewed_annotations(self) -> tuple[ClaimReview, ...]:
        return tuple(item for item in self.reviews if item.status == "reviewed")


def summarize_claim_reviews(dataset: ClaimReviewDataset) -> dict[str, object]:
    """Return aggregate human-review grades; draft/rejected labels are excluded."""
    reviewed = dataset.reviewed_annotations
    grade_counts = Counter(item.overall_grade for item in reviewed)
    pair_grades = Counter(
        assessment.grade
        for item in reviewed
        for assessment in item.assessments
    )
    total_pairs = sum(pair_grades.values())
    return {
        "dataset_id": dataset.dataset_id,
        "dataset_version": dataset.dataset_version,
        "reviewed_claims": len(reviewed),
        "excluded_annotations": len(dataset.reviews) - len(reviewed),
        "claim_grade_counts": {str(grade): grade_counts.get(grade, 0) for grade in (0, 1, 2)},
        "evidence_pair_grade_counts": {
            str(grade): pair_grades.get(grade, 0) for grade in (0, 1, 2)
        },
        "supported_claim_rate": (
            grade_counts.get(2, 0) / len(reviewed) if reviewed else None
        ),
        "unsupported_claim_rate": (
            grade_counts.get(0, 0) / len(reviewed) if reviewed else None
        ),
        "evidence_pair_supported_rate": (
            pair_grades.get(2, 0) / total_pairs if total_pairs else None
        ),
        "semantic_claim_support": "human_review_only",
    }

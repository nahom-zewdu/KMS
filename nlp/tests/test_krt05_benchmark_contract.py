"""Contract and integrity tests for the KRT-05 end-to-end seed dataset."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluation.benchmark import (
    BenchmarkDataset,
    load_benchmark,
    validate_retrieval_references,
)

_FIXTURE_ROOT = Path(__file__).parent / "fixtures"
_DATASET_PATH = _FIXTURE_ROOT / "evaluation" / "krt05_seed_v1.json"
_RETRIEVAL_PATH = _FIXTURE_ROOT / "retrieval" / "retrieval_tasks_v1.json"


def test_seed_dataset_loads_with_unique_cases_and_explicit_scope():
    dataset = load_benchmark(_DATASET_PATH)

    assert dataset.schema_version == 1
    assert dataset.dataset_id == "kms-krt05-end-to-end-seed"
    assert dataset.dataset_version == "1.0.0"
    assert len(dataset.cases) == 24
    assert len({case.id for case in dataset.cases}) == 24
    assert all(case.scope.company_id == dataset.default_scope.company_id for case in dataset.cases)
    assert all(case.scope.snapshot_id == dataset.default_scope.snapshot_id for case in dataset.cases)
    assert all(case.scope.source_revision == dataset.default_scope.source_revision for case in dataset.cases)
    assert all(
        case.scope.repository_id == dataset.default_scope.repository_id
        or case.task_type == "ambiguous_scope"
        for case in dataset.cases
    )
    assert dataset.scored_cases == ()


def test_seed_dataset_reuses_existing_retrieval_labels_without_copying_them():
    dataset = load_benchmark(_DATASET_PATH)
    validate_retrieval_references(dataset, _RETRIEVAL_PATH)

    references = [
        reference
        for case in dataset.cases
        for reference in case.evidence
    ]
    assert len(references) == 15
    assert {reference.evidence_kind for reference in references} == {
        "declaration", "call_site", "passage"
    }


def test_draft_cases_are_never_counted_as_scored_cases():
    dataset = load_benchmark(_DATASET_PATH)
    assert all(case.review_status == "draft" for case in dataset.cases)
    assert dataset.scored_cases == ()


def test_duplicate_case_ids_are_rejected():
    payload = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"].append(payload["cases"][0])

    with pytest.raises(ValidationError, match="case IDs must be unique"):
        BenchmarkDataset.model_validate_json(json.dumps(payload))


def test_unanswerable_case_cannot_claim_planned_query_route():
    payload = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    case = payload["cases"][0]
    case["answerability"] = "unanswerable"

    with pytest.raises(ValidationError, match="unanswerable cases cannot expect planned_query"):
        BenchmarkDataset.model_validate_json(json.dumps(payload))


def test_abstention_requires_an_explicit_reason():
    payload = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    case = payload["cases"][15]
    case["expected_abstention"] = None

    with pytest.raises(ValidationError, match="abstention cases require"):
        BenchmarkDataset.model_validate_json(json.dumps(payload))


def test_reviewed_case_requires_reviewer_and_date():
    payload = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["review_status"] = "reviewed"

    with pytest.raises(ValidationError, match="reviewed cases require"):
        BenchmarkDataset.model_validate_json(json.dumps(payload))


def test_unknown_retrieval_reference_is_rejected(tmp_path):
    dataset = load_benchmark(_DATASET_PATH)
    payload = json.loads(_RETRIEVAL_PATH.read_text(encoding="utf-8"))
    payload["queries"] = [
        query for query in payload["queries"] if query["id"] != "decl-01"
    ]
    temporary_fixture = tmp_path / "retrieval_missing_case.json"
    temporary_fixture.write_text(json.dumps(payload), encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="unknown retrieval case"):
            validate_retrieval_references(dataset, temporary_fixture)
    finally:
        temporary_fixture.unlink(missing_ok=True)


def test_wrong_retrieval_task_type_is_rejected(tmp_path):
    dataset = load_benchmark(_DATASET_PATH)
    payload = json.loads(_RETRIEVAL_PATH.read_text(encoding="utf-8"))
    query = next(query for query in payload["queries"] if query["id"] == "decl-01")
    query["task_type"] = "passage_retrieval"
    temporary_fixture = tmp_path / "retrieval_wrong_type.json"
    temporary_fixture.write_text(json.dumps(payload), encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="wrong task type"):
            validate_retrieval_references(dataset, temporary_fixture)
    finally:
        temporary_fixture.unlink(missing_ok=True)

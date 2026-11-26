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
    assert all(
        case.scope.snapshot_id == dataset.default_scope.snapshot_id
        or (case.task_type in {"ambiguous_scope", "structured_fact"} and case.scope.snapshot_id is None)
        for case in dataset.cases
    )
    assert all(
        case.scope.source_revision == dataset.default_scope.source_revision
        or (case.task_type in {"ambiguous_scope", "structured_fact"} and case.scope.source_revision is None)
        for case in dataset.cases
    )
    assert all(
        case.scope.repository_id == dataset.default_scope.repository_id
        or case.task_type in {"ambiguous_scope", "structured_fact"}
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



def test_ambiguous_symbol_case_has_two_exact_declarations():
    root = _FIXTURE_ROOT / "evaluation" / "ambiguous_symbols"
    sources = [
        (root / "worker_a.py").read_text(encoding="utf-8"),
        (root / "worker_b.py").read_text(encoding="utf-8"),
    ]
    assert all("def process_task(" in source for source in sources)
    assert sum(source.count("def process_task(") for source in sources) == 2


def test_structured_repository_count_case_has_authoritative_fixture():
    path = _FIXTURE_ROOT / "evaluation" / "structured_company_repositories_v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    repositories = payload["companies"]["benchmark-company"]["repositories"]
    assert len(repositories) == 2
    assert len({item["id"] for item in repositories}) == 2



def test_company_level_structured_fact_uses_company_only_scope():
    dataset = load_benchmark(_DATASET_PATH)
    case = next(case for case in dataset.cases if case.id == "seed-structured-count")

    assert case.scope.company_id == "benchmark-company"
    assert case.scope.repository_id is None
    assert case.scope.snapshot_id is None
    assert case.scope.source_revision is None


def test_structured_fact_rejects_repository_specific_scope():
    payload = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    case = next(item for item in payload["cases"] if item["id"] == "seed-structured-count")
    case["scope"]["repository_id"] = "benchmark-repository"
    case["scope"]["snapshot_id"] = "benchmark-snapshot-v1"
    case["scope"]["source_revision"] = "benchmark-revision-v1"

    with pytest.raises(ValidationError, match="company-level structured facts"):
        BenchmarkDataset.model_validate_json(json.dumps(payload))


def test_ambiguous_repository_scope_has_no_snapshot_metadata():
    dataset = load_benchmark(_DATASET_PATH)
    case = next(case for case in dataset.cases if case.id == "seed-ambiguous-repository")
    assert case.scope.repository_id is None
    assert case.scope.snapshot_id is None
    assert case.scope.source_revision is None


def test_expected_intent_must_match_expected_route_and_task():
    payload = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["expected_intent"] = "unsupported"

    with pytest.raises(ValidationError, match="expected_intent is inconsistent"):
        BenchmarkDataset.model_validate_json(json.dumps(payload))


def test_task_type_cannot_be_paired_with_an_unrelated_intent():
    payload = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["task_type"] = "call_site_navigation"

    with pytest.raises(ValidationError, match="expected_intent is inconsistent with task_type"):
        BenchmarkDataset.model_validate_json(json.dumps(payload))

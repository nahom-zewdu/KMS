"""Tests for the shared hybrid-retrieval evidence candidate contract."""

import math

import pytest

from query_engine.evidence import EvidenceCandidate


def _code_candidate(**overrides):
    values = {
        "company_id": "company-a",
        "evidence_type": "code_chunk",
        "source": "github",
        "record_id": "src/payments/service.py",
        "content": "def charge(): pass",
        "retriever": "lexical",
        "rank": 1,
        "repository_id": "repo-a",
        "snapshot_id": "snapshot-a",
        "source_revision": "a" * 40,
        "file_path": "src/payments/service.py",
        "content_hash": "b" * 64,
        "start_line": 10,
        "end_line": 10,
        "start_byte": 120,
        "end_byte": 138,
        "raw_score": 0.91,
    }
    values.update(overrides)
    return EvidenceCandidate(**values)


def test_code_candidate_keeps_snapshot_and_source_provenance():
    candidate = _code_candidate()

    assert candidate.company_id == "company-a"
    assert candidate.repository_id == "repo-a"
    assert candidate.snapshot_id == "snapshot-a"
    assert candidate.source_revision == "a" * 40
    assert candidate.file_path == "src/payments/service.py"
    assert candidate.start_line == 10
    assert candidate.end_line == 10
    assert len(candidate.evidence_id) == 64


def test_code_evidence_identity_is_stable_for_same_source_range():
    first = _code_candidate()
    second = _code_candidate(retriever="semantic", rank=4, raw_score=0.72)

    assert first.evidence_id == second.evidence_id


@pytest.mark.parametrize(
    "change",
    [
        {"company_id": "company-b"},
        {"repository_id": "repo-b"},
        {"snapshot_id": "snapshot-b"},
        {"file_path": "src/other.py"},
        {"start_byte": 121, "end_byte": 139},
        {"content_hash": "c" * 64},
    ],
)
def test_code_evidence_identity_changes_with_source_identity(change):
    assert _code_candidate().evidence_id != _code_candidate(**change).evidence_id


def test_event_identity_is_scoped_to_company_and_source_record():
    first = EvidenceCandidate(
        company_id="company-a",
        evidence_type="event",
        source="github",
        record_id="pull/42",
        content="A pull request was merged.",
        retriever="event-vector",
        rank=1,
    )
    same = EvidenceCandidate(
        company_id="company-a",
        evidence_type="event",
        source="github",
        record_id="pull/42",
        content="Different excerpt from the same event.",
        retriever="event-lexical",
        rank=3,
    )
    other_company = EvidenceCandidate(
        company_id="company-b",
        evidence_type="event",
        source="github",
        record_id="pull/42",
        content="A pull request was merged.",
        retriever="event-vector",
        rank=1,
    )

    assert first.evidence_id == same.evidence_id
    assert first.evidence_id != other_company.evidence_id


@pytest.mark.parametrize("company_id", ["", "  ", "default", "DEFAULT"])
def test_candidate_rejects_missing_or_placeholder_tenant(company_id):
    with pytest.raises(ValueError, match="company_id"):
        EvidenceCandidate(
            company_id=company_id,
            evidence_type="event",
            source="github",
            record_id="pull/42",
            content="content",
            retriever="event-vector",
            rank=1,
        )


def test_code_candidate_rejects_missing_snapshot_provenance():
    with pytest.raises(ValueError, match="snapshot_id"):
        _code_candidate(snapshot_id=None)


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"rank": 0}, "rank"),
        ({"start_line": 0}, "line range"),
        ({"end_line": 9}, "line range"),
        ({"start_byte": -1}, "byte range"),
        ({"end_byte": 119}, "byte range"),
    ],
)
def test_code_candidate_rejects_invalid_rank_or_source_range(changes, message):
    with pytest.raises(ValueError, match=message):
        _code_candidate(**changes)


def test_candidate_rejects_non_finite_raw_score():
    with pytest.raises(ValueError, match="finite"):
        _code_candidate(raw_score=math.nan)


def test_to_dict_includes_computed_evidence_identity():
    candidate = _code_candidate()

    serialized = candidate.to_dict()

    assert serialized["evidence_id"] == candidate.evidence_id
    assert serialized["retriever"] == "lexical"
    assert serialized["snapshot_id"] == "snapshot-a"

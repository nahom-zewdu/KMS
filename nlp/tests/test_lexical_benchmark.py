"""Tests for lexical benchmark metrics and hard scope validation."""

import json

import pytest

from query_engine.evidence import EvidenceCandidate
from query_engine.lexical_benchmark import run_lexical_benchmark


def _candidate(
    *,
    rank=1,
    path="src/payments/service.py",
    qualified_name="PaymentService.charge",
    company_id="company-a",
    repository_id="mini-repo-a",
    snapshot_id="mini-repo-a@fixture-v1",
):
    return EvidenceCandidate(
        company_id=company_id,
        evidence_type="symbol",
        source="tree-sitter",
        record_id=f"symbol-{rank}",
        content=f"{qualified_name} in {path}",
        retriever="test",
        rank=rank,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        source_revision="fixture-v1",
        file_path=path,
        content_hash="a" * 64,
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=20,
        metadata={"qualified_name": qualified_name},
    )


class FakeRetriever:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return self.results


def _benchmark(tmp_path):
    path = tmp_path / "benchmark.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "default_scope": {
                    "company_id": "company-a",
                    "repository_id": "mini-repo-a",
                    "snapshot_id": "mini-repo-a@fixture-v1",
                    "source_revision": "fixture-v1",
                },
                "queries": [
                    {
                        "id": "q1",
                        "lexical_input": {"identifiers": ["charge"]},
                        "expected_paths": ["src/payments/service.py"],
                        "expected_symbols": ["PaymentService.charge"],
                    },
                    {
                        "id": "q2",
                        "question": "Natural-language question with no lexical plan",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_benchmark_reports_recall_mrr_and_unsupported_queries(tmp_path):
    retriever = FakeRetriever(
        [
            _candidate(rank=1, qualified_name="PaymentService.charge"),
            _candidate(
                rank=2,
                path="src/payments/retry.py",
                qualified_name="RetryPolicy.should_retry",
            ),
        ]
    )

    result = run_lexical_benchmark(_benchmark(tmp_path), retriever)

    assert result["evaluated_queries"] == 1
    assert result["unsupported_queries"] == ["q2"]
    assert result["metrics"] == {
        "recall_at_1": 1.0,
        "recall_at_5": 1.0,
        "recall_at_10": 1.0,
        "mrr": 1.0,
    }
    assert retriever.calls == [
        {
            "company_id": "company-a",
            "repository_id": "mini-repo-a",
            "identifiers": ["charge"],
        }
    ]


def test_benchmark_penalizes_missing_and_late_relevant_evidence(tmp_path):
    retriever = FakeRetriever(
        [
            _candidate(
                rank=1,
                path="src/payments/retry.py",
                qualified_name="RetryPolicy.should_retry",
            ),
            _candidate(rank=2),
        ]
    )

    result = run_lexical_benchmark(_benchmark(tmp_path), retriever)

    assert result["metrics"]["recall_at_1"] == 0.5
    assert result["metrics"]["recall_at_5"] == 1.0
    assert result["metrics"]["mrr"] == 0.5


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (_candidate(company_id="company-b"), "company scope"),
        (_candidate(repository_id="mini-repo-b"), "repository scope"),
        (_candidate(snapshot_id="mini-repo-a@old"), "snapshot scope"),
    ],
)
def test_benchmark_fails_on_scope_leakage(tmp_path, candidate, message):
    with pytest.raises(ValueError, match=message):
        run_lexical_benchmark(
            _benchmark(tmp_path),
            FakeRetriever([candidate]),
        )


def test_benchmark_rejects_invalid_cutoffs(tmp_path):
    with pytest.raises(ValueError, match="positive integers"):
        run_lexical_benchmark(_benchmark(tmp_path), FakeRetriever([]), cutoffs=(0, 5))

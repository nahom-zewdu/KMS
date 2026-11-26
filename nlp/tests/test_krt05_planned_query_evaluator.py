"""Deterministic tests for the offline planned-query evaluation harness."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from evaluation.benchmark import load_benchmark
from evaluation.planned_query_evaluator import evaluate_planned_queries, write_report
from query_engine.evidence import EvidenceCandidate
from query_engine.query_plan import (
    PlanDisposition, QueryIntent, QueryPlan, QueryScope,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _evidence(*, company="benchmark-company", repository="benchmark-repository",
              snapshot="benchmark-snapshot-v1", revision="benchmark-revision-v1"):
    return EvidenceCandidate(
        company_id=company, evidence_type="code_chunk", source="fixture",
        record_id="chunk-1", content="def find_available(): return True",
        retriever="fixture-retriever", rank=1, repository_id=repository,
        snapshot_id=snapshot, source_revision=revision,
        file_path="catalog/products.py", content_hash="a" * 64,
        start_line=1, end_line=2, start_byte=0, end_byte=42,
    )


def _reviewed_dataset():
    dataset = load_benchmark(_FIXTURES / "evaluation" / "krt05_seed_v1.json")
    first = dataset.cases[0].model_dump()
    first.update({
        "review_status": "reviewed",
        "reviewer": "test-reviewer",
        "reviewed_on": "2026-11-26",
    })
    from evaluation.benchmark import BenchmarkCase
    case = BenchmarkCase.model_validate(first)
    return dataset.model_copy(update={"cases": (case,)}), case


@dataclass
class FakeExecutor:
    result: object
    calls: list

    def execute(self, query, *, scope, **kwargs):
        self.calls.append((query, scope, kwargs))
        return self.result


def _result(case, evidence, answer):
    plan = QueryPlan(
        query=case.question,
        intent=QueryIntent.PASSAGE_RETRIEVAL,
        scope=QueryScope(case.scope.company_id, case.scope.repository_id),
        terms=("find_available",),
    )
    return SimpleNamespace(
        plan=plan, evidence=tuple(evidence), answer=answer, deferred=False, reason=None,
    )


def test_evaluator_scores_only_reviewed_cases_and_validates_provenance_and_citations():
    dataset, case = _reviewed_dataset()
    evidence = _evidence()
    executor = FakeExecutor(
        _result(case, [evidence], {
            "claims": [{"text": "Availability is checked.", "evidence_ids": [evidence.evidence_id]}],
            "abstain_reason": None,
        }),
        [],
    )

    report = evaluate_planned_queries(dataset, executor, commit="abc123")

    assert len(executor.calls) == 1
    assert report["summary"]["reviewed_cases"] == 1
    assert report["summary"]["excluded_cases"] == 23
    assert report["summary"]["passed_cases"] == 1
    assert report["summary"]["scope_violations"] == 0
    assert report["summary"]["citation_membership_violations"] == 0
    assert report["semantic_claim_support"]["status"] == "not_evaluated"


def test_evaluator_fails_closed_on_wrong_provenance_and_unknown_citation():
    dataset, case = _reviewed_dataset()
    evidence = _evidence(company="another-company")
    executor = FakeExecutor(
        _result(case, [evidence], {
            "claims": [{"text": "Unrelated claim.", "evidence_ids": ["invented-id"]}],
            "abstain_reason": None,
        }),
        [],
    )

    report = evaluate_planned_queries(dataset, executor, commit="abc123")
    outcome = report["outcomes"][0]

    assert not outcome["passed"]
    assert "evidence_provenance_mismatch" in outcome["failures"]
    assert "citation_membership_mismatch" in outcome["failures"]
    assert report["summary"]["scope_violations"] == 1
    assert report["summary"]["citation_membership_violations"] == 1


def test_draft_only_dataset_is_reported_as_excluded_without_running_executor():
    dataset = load_benchmark(_FIXTURES / "evaluation" / "krt05_seed_v1.json")
    executor = FakeExecutor(result=None, calls=[])

    report = evaluate_planned_queries(dataset, executor, commit="abc123")

    assert executor.calls == []
    assert report["summary"]["reviewed_cases"] == 0
    assert report["summary"]["excluded_cases"] == 24
    assert report["outcomes"] == []


def test_report_writer_emits_stable_sorted_json(tmp_path):
    dataset, _ = _reviewed_dataset()
    executor = FakeExecutor(result=None, calls=[])
    report = evaluate_planned_queries(dataset, executor, commit="abc123")
    path = tmp_path / "report.json"

    write_report(report, path)

    content = path.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert '"report_schema_version": 1' in content
    assert '"dataset_sha256"' in content

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
              snapshot="benchmark-snapshot-v1", revision="benchmark-revision-v1",
              evidence_type="symbol", start_line=1, end_line=2):
    return EvidenceCandidate(
        company_id=company, evidence_type=evidence_type, source="fixture",
        record_id="symbol-1", content="function find_available",
        retriever="fixture-retriever", rank=1, repository_id=repository,
        snapshot_id=snapshot, source_revision=revision,
        file_path="catalog/products.py", content_hash="a" * 64,
        start_line=start_line, end_line=end_line, start_byte=0, end_byte=42,
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
    return dataset.model_copy(update={
        "cases": (case, *dataset.cases[1:]),
    }), case


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
        intent=QueryIntent.DECLARATION_DISCOVERY,
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
    assert report["outcomes"][0]["evidence_recall"] == 1.0
    assert report["summary"]["mean_evidence_recall"] == 1.0
    assert report["semantic_claim_support"]["status"] == "not_evaluated"
    assert report["summary"]["route_confusion_matrix"] == {"planned_query->planned_query": 1}
    assert report["summary"]["per_task"]["declaration_discovery"]["cases"] == 1
    assert report["summary"]["abstention"]["answerable_cases"] == 1
    assert report["summary"]["abstention"]["false_abstentions"] == 0


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
    case = dataset.scored_cases[0]
    executor = FakeExecutor(
        result=_result(case, [], {"claims": [], "abstain_reason": "no_matching_evidence"}),
        calls=[],
    )
    report = evaluate_planned_queries(dataset, executor, commit="abc123")
    path = tmp_path / "report.json"

    write_report(report, path)

    content = path.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert '"report_schema_version": 1' in content
    assert '"dataset_sha256"' in content
    assert '"retrieval_fixture_sha256"' in content




def test_no_evidence_case_fails_if_executor_returns_any_candidate():
    dataset = load_benchmark(_FIXTURES / "evaluation" / "krt05_seed_v1.json")
    raw = next(
        case.model_dump() for case in dataset.cases
        if case.id == "seed-no-evidence-1"
    )
    raw.update({
        "review_status": "reviewed",
        "reviewer": "test-reviewer",
        "reviewed_on": "2026-11-26",
    })
    from evaluation.benchmark import BenchmarkCase
    case = BenchmarkCase.model_validate(raw)
    dataset = dataset.model_copy(update={"cases": (case,)})
    evidence = _evidence()
    plan = QueryPlan(
        query=case.question,
        intent=QueryIntent.PASSAGE_RETRIEVAL,
        scope=QueryScope(case.scope.company_id, case.scope.repository_id),
    )
    result = SimpleNamespace(
        plan=plan,
        evidence=(evidence,),
        answer={
            "claims": [],
            "abstain_reason": "no_matching_evidence",
        },
        deferred=False,
        reason="no_matching_evidence",
    )

    report = evaluate_planned_queries(
        dataset, FakeExecutor(result=result, calls=[]), commit="abc123",
    )

    outcome = report["outcomes"][0]
    assert not outcome["passed"]
    assert "unexpected_evidence_for_no_evidence_case" in outcome["failures"]



def test_dataset_carries_bounded_follow_up_context():
    dataset = load_benchmark(_FIXTURES / "evaluation" / "krt05_seed_v1.json")
    case = next(case for case in dataset.cases if case.task_type == "conversation_control")

    assert case.expected_intent == "follow_up"
    assert case.conversation_history
    assert case.conversation_refs



def test_call_site_recall_requires_occurrence_evidence_at_labeled_range():
    dataset = load_benchmark(_FIXTURES / "evaluation" / "krt05_seed_v1.json")
    raw = next(case.model_dump() for case in dataset.cases if case.id == "seed-call-01")
    raw.update({
        "review_status": "reviewed",
        "reviewer": "test-reviewer",
        "reviewed_on": "2026-11-26",
    })
    from evaluation.benchmark import BenchmarkCase
    case = BenchmarkCase.model_validate(raw)
    dataset = dataset.model_copy(update={"cases": (case,)})
    evidence = _evidence(
        evidence_type="occurrence", start_line=12, end_line=13,
    )
    plan = QueryPlan(
        query=case.question,
        intent=QueryIntent.CALL_SITE_NAVIGATION,
        scope=QueryScope(case.scope.company_id, case.scope.repository_id),
        terms=("find_available",),
    )
    result = SimpleNamespace(
        plan=plan,
        evidence=(evidence,),
        answer={"claims": [{"text": "Call site.", "evidence_ids": [evidence.evidence_id]}]},
        deferred=False,
        reason=None,
    )
    report = evaluate_planned_queries(
        dataset, FakeExecutor(result=result, calls=[]), commit="abc123",
    )

    assert report["outcomes"][0]["evidence_recall"] == 1.0
    assert report["summary"]["passed_cases"] == 1

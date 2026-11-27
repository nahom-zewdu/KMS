"""Tests for the production QueryEngine evaluation adapter."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from evaluation.benchmark import load_benchmark
from evaluation.production_path_evaluator import evaluate_production_path

_FIXTURES = Path(__file__).parent / "fixtures"


class _FakeEngine:
    def __init__(self, observer, event, answer):
        self.observer = observer
        self.event = event
        self.answer = answer

    def handle_query(self, _job):
        if self.event is not None:
            self.observer(self.event)
        return json.dumps(self.answer)


def _one_case(case_id):
    dataset = load_benchmark(_FIXTURES / "evaluation" / "krt05_seed_v1.json")
    case = next(item for item in dataset.cases if item.id == case_id)
    return dataset.model_copy(update={"cases": (case,)}), case


def test_production_evaluator_records_actual_structured_route():
    dataset, case = _one_case("seed-structured-count")

    def factory(observer):
        return _FakeEngine(
            observer,
            {
                "query_id": f"krt05:{case.id}",
                "route": "structured_handler",
                "outcome": "answered",
                "reason": None,
                "intent": "structured_fact",
                "evidence_count": 2,
            },
            {
                "answer": "2 connected repositories are registered for this company.",
                "sources": [{"record_id": "repo-catalog"}, {"record_id": "repo-billing"}],
                "abstain_reason": None,
            },
        )

    report = evaluate_production_path(dataset, factory, commit="abc123")
    outcome = report["outcomes"][0]

    assert outcome["observed_route"] == "structured_handler"
    assert outcome["observed_handler_route"] == "structured_handler"
    assert outcome["passed"]
    assert report["summary"]["passed_cases"] == 1
    assert report["semantic_claim_support"]["status"] == "not_evaluated"
    assert outcome["evidence_provenance"] == "not_available_for_route"


def test_production_evaluator_does_not_promote_follow_up_guard_to_handler():
    dataset, case = _one_case("seed-followup-context")

    def factory(observer):
        return _FakeEngine(
            observer,
            {
                "query_id": f"krt05:{case.id}",
                "route": "conversation_guard",
                "outcome": "abstained",
                "reason": "conversation_context_unresolved",
                "intent": "follow_up",
                "evidence_count": 0,
            },
            {"answer": "Please clarify.", "abstain_reason": "conversation_context_unresolved"},
        )

    report = evaluate_production_path(dataset, factory, commit="abc123")
    outcome = report["outcomes"][0]

    assert outcome["observed_route"] == "conversation_guard"
    assert outcome["observed_handler_route"] == "conversation_guard"
    assert not outcome["passed"]
    assert "route_mismatch" in outcome["failures"]


def test_production_evaluator_marks_missing_telemetry_unobserved():
    dataset, _ = _one_case("seed-structured-count")

    def factory(_observer):
        return _FakeEngine(
            lambda _event: None,
            None,
            {"answer": "2 repositories", "abstain_reason": None},
        )

    report = evaluate_production_path(dataset, factory, commit="abc123")
    outcome = report["outcomes"][0]

    assert outcome["observed_route"] == "unobserved"
    assert not outcome["passed"]
    assert "production_outcome_unobserved" in outcome["failures"]
    assert report["summary"]["unobserved_outcomes"] == 1


def test_production_evaluator_records_engine_exception():
    dataset, _ = _one_case("seed-structured-count")

    class BrokenEngine:
        def handle_query(self, _job):
            raise RuntimeError("fixture failure")

    report = evaluate_production_path(
        dataset, lambda _observer: BrokenEngine(), commit="abc123",
    )
    outcome = report["outcomes"][0]

    assert outcome["execution_error"] == "RuntimeError"
    assert not outcome["passed"]
    assert "execution_error" in outcome["failures"]


def test_production_evaluator_excludes_unreviewed_cases():
    dataset = load_benchmark(_FIXTURES / "evaluation" / "krt05_seed_v1.json")
    from evaluation.benchmark import BenchmarkCase

    cases = tuple(
        BenchmarkCase.model_validate({
            **case.model_dump(),
            "review_status": "draft",
            "reviewer": None,
            "reviewed_on": None,
        })
        for case in dataset.cases
    )
    draft_dataset = dataset.model_copy(update={"cases": cases})
    calls = []

    report = evaluate_production_path(
        draft_dataset,
        lambda observer: calls.append(observer),
        commit="abc123",
    )

    assert calls == []
    assert report["summary"]["reviewed_cases"] == 0
    assert report["summary"]["excluded_cases"] == 24
    assert report["outcomes"] == []



def test_production_evaluator_records_engine_factory_failure():
    dataset, _ = _one_case("seed-structured-count")

    def broken_factory(_observer):
        raise RuntimeError("fixture construction failed")

    report = evaluate_production_path(dataset, broken_factory, commit="abc123")
    outcome = report["outcomes"][0]

    assert outcome["execution_error"] == "RuntimeError"
    assert outcome["observed_route"] == "unobserved"
    assert "execution_error" in outcome["failures"]
    assert "production_outcome_unobserved" in outcome["failures"]



def test_production_evaluator_checks_observed_evidence_scope_and_citations():
    dataset, case = _one_case("seed-decl-01")
    evidence_id = "evidence:fixture-1"

    def factory(observer):
        return _FakeEngine(
            observer,
            {
                "query_id": f"krt05:{case.id}",
                "route": "planned_query",
                "outcome": "answered",
                "reason": None,
                "intent": "declaration_discovery",
                "evidence_count": 1,
                "evidence": [{
                    "evidence_id": evidence_id,
                    "company_id": "another-company",
                    "repository_id": case.scope.repository_id,
                    "snapshot_id": case.scope.snapshot_id,
                    "source_revision": case.scope.source_revision,
                }],
            },
            {
                "answer": "Found it.",
                "abstain_reason": None,
                "claims": [{"text": "A claim.", "evidence_ids": ["unknown-evidence"]}],
            },
        )

    report = evaluate_production_path(dataset, factory, commit="abc123")
    outcome = report["outcomes"][0]

    assert outcome["evidence_provenance"] == "mismatch"
    assert outcome["unknown_citation_ids"] == ["unknown-evidence"]
    assert "evidence_provenance_mismatch" in outcome["failures"]
    assert "citation_membership_mismatch" in outcome["failures"]
    assert report["summary"]["evidence_provenance_violations"] == 1
    assert report["summary"]["citation_membership_violations"] == 1



def test_production_evaluator_validates_structured_source_tenant_scope():
    dataset, case = _one_case("seed-structured-count")

    def factory(observer):
        return _FakeEngine(
            observer,
            {
                "query_id": f"krt05:{case.id}",
                "route": "structured_handler",
                "outcome": "answered",
                "reason": None,
                "intent": "structured_fact",
                "evidence_count": 2,
                "source_company_id": "another-company",
                "source_records": [
                    {"source": "repositories", "record_id": "repo-1"},
                    {"source": "repositories", "record_id": "repo-2"},
                ],
            },
            {
                "answer": "2 connected repositories are registered for this company.",
                "sources": [{"record_id": "repo-1"}, {"record_id": "repo-2"}],
                "abstain_reason": None,
            },
        )

    report = evaluate_production_path(dataset, factory, commit="abc123")
    outcome = report["outcomes"][0]

    assert outcome["evidence_provenance"] == "mismatch"
    assert "evidence_provenance_mismatch" in outcome["failures"]

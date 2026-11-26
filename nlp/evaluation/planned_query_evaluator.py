"""Offline KRT-05 evaluation of the planned-query orchestration boundary.

This harness injects no LLM and performs no database writes. It scores only
human-reviewed cases; draft and rejected cases are reported as excluded.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Protocol

from query_engine.query_plan import QueryScope

from .benchmark import BenchmarkCase, BenchmarkDataset


class PlannedExecutor(Protocol):
    """The narrow interface needed by the deterministic evaluation harness."""

    def execute(self, query: str, *, scope: QueryScope, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    """Sanitized per-case outcome; contains no prompt or source content."""

    case_id: str
    task_type: str
    answerability: str
    expected_route: str
    observed_intent: str
    observed_disposition: str
    observed_route: str
    evidence_count: int
    expected_evidence_count: int
    evidence_recall: float | None
    provenance_valid: bool
    citation_membership_valid: bool
    abstained: bool
    passed: bool
    failures: tuple[str, ...]


def _observed_route(result: Any) -> str:
    if getattr(result, "deferred", False):
        reason = getattr(result, "reason", "") or ""
        if reason == "legacy_structured_route":
            return "structured_handler"
        if reason == "conversation_context_route":
            return "conversation_handler"
        return "deferred"
    answer = getattr(result, "answer", None) or {}
    if answer.get("abstain_reason"):
        return "abstain"
    if answer.get("claims"):
        return "planned_query"
    return "empty"


def _validate_provenance(case: BenchmarkCase, evidence: tuple[Any, ...]) -> bool:
    return all(
        item.company_id == case.scope.company_id
        and item.repository_id == case.scope.repository_id
        and item.snapshot_id == case.scope.snapshot_id
        and item.source_revision == case.scope.source_revision
        for item in evidence
    )


def _validate_citation_membership(answer: Mapping[str, Any], evidence: tuple[Any, ...]) -> bool:
    allowed = {item.evidence_id for item in evidence}
    claims = answer.get("claims") or []
    return bool(claims) and all(
        isinstance(claim, Mapping)
        and isinstance(claim.get("evidence_ids"), (list, tuple))
        and bool(claim["evidence_ids"])
        and set(claim["evidence_ids"]).issubset(allowed)
        for claim in claims
    )


def _load_retrieval_labels(dataset: BenchmarkDataset, path: str | Path | None):
    fixture_path = Path(path) if path is not None else (
        Path(__file__).resolve().parents[1] / dataset.retrieval_fixture
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    return {item["id"]: item for item in payload.get("queries", [])}


def _evidence_recall(case: BenchmarkCase, evidence: tuple[Any, ...], labels: Mapping[str, Any]):
    expected: list[tuple[str, Any]] = []
    for reference in case.evidence:
        query = labels.get(reference.retrieval_case_id)
        if query is None:
            raise ValueError(f"{case.id}: missing retrieval label {reference.retrieval_case_id}")
        if reference.evidence_kind == "declaration":
            expected.extend(("declaration", (symbol, path)) for symbol in query.get("expected_symbols", [])
                            for path in query.get("expected_paths", []))
        else:
            expected.extend((reference.evidence_kind, item) for item in query.get("expected_ranges", []))

    if not expected:
        return 0, None

    hits = 0
    for kind, label in expected:
        matched = False
        for item in evidence:
            if kind == "declaration":
                symbol, expected_path = label
                symbol_text = str(item.content).split()[-1] if item.content else ""
                matched = (
                    item.evidence_type == "symbol"
                    and item.file_path == expected_path
                    and (symbol_text == symbol or symbol_text.endswith("." + symbol))
                )
            else:
                required_type = "occurrence" if kind == "call_site" else "code_chunk"
                matched = (
                    item.evidence_type == required_type
                    and item.file_path == label["file_path"]
                    and item.start_line <= label["end_line"]
                    and item.end_line >= label["start_line"]
                )
            if matched:
                break
        hits += int(matched)
    return len(expected), hits / len(expected)


def evaluate_planned_queries(
    dataset: BenchmarkDataset,
    executor: PlannedExecutor,
    *,
    commit: str,
    retrieval_fixture_path: str | Path | None = None,
    environment: str = "synthetic-offline",
) -> dict[str, Any]:
    """Run reviewed cases and return a deterministic, source-free report.

    The function intentionally does not assign semantic entailment grades.
    Claim-to-evidence relevance requires independent human review.
    """
    if not commit or not commit.strip():
        raise ValueError("commit is required for reproducible reports")
    if not environment or len(environment) > 128:
        raise ValueError("environment must be a non-empty bounded label")

    labels = _load_retrieval_labels(dataset, retrieval_fixture_path)
    outcomes: list[EvaluationOutcome] = []
    excluded = Counter()
    for case in dataset.cases:
        if case.review_status != "reviewed":
            excluded[case.review_status] += 1
            continue

        scope = QueryScope(
            company_id=case.scope.company_id,
            repository_id=case.scope.repository_id,
        )
        result = executor.execute(
            case.question,
            scope=scope,
            conversation_history=tuple(turn.model_dump() for turn in case.conversation_history),
            conversation_refs=case.conversation_refs,
        )
        plan = result.plan
        evidence = tuple(getattr(result, "evidence", ()) or ())
        answer = getattr(result, "answer", None) or {}
        route = _observed_route(result)
        provenance_valid = _validate_provenance(case, evidence)
        expected_evidence_count, evidence_recall = _evidence_recall(case, evidence, labels)
        citation_valid = (
            _validate_citation_membership(answer, evidence)
            if route == "planned_query" else not bool(answer.get("claims"))
        )
        abstained = route == "abstain"
        failures: list[str] = []
        if route != case.expected_route:
            failures.append("route_mismatch")
        if plan.intent.value != case.expected_intent:
            failures.append("intent_mismatch")
        if not provenance_valid:
            failures.append("evidence_provenance_mismatch")
        if not citation_valid:
            failures.append("citation_membership_mismatch")
        if case.expected_route == "planned_query" and (evidence_recall is None or evidence_recall == 0):
            failures.append("expected_evidence_missing")
        elif case.expected_route == "planned_query" and evidence_recall < 1.0:
            failures.append("expected_evidence_incomplete")
        if case.task_type == "no_evidence" and evidence:
            failures.append("unexpected_evidence_for_no_evidence_case")
        if case.expected_route == "abstain" and not abstained:
            failures.append("expected_abstention_missing")
        if case.expected_route == "abstain" and abstained:
            expected_reason = {
                "no_evidence": {"no_matching_evidence", "call_sites_not_found", "declaration_not_found"},
                "ambiguous_repository": {"repository_scope_required"},
                "ambiguous_symbol": {"ambiguous_declaration", "multiple_symbol_candidates"},
                "unsupported_intent": {"unsupported_query"},
                "insufficient_evidence": {"no_matching_evidence", "declaration_not_found", "call_sites_not_found"},
            }.get(case.expected_abstention, set())
            observed_reason = answer.get("abstain_reason") or getattr(result, "reason", None)
            if observed_reason not in expected_reason:
                failures.append("abstention_reason_mismatch")

        outcomes.append(EvaluationOutcome(
            case_id=case.id,
            task_type=case.task_type,
            answerability=case.answerability,
            expected_route=case.expected_route,
            observed_intent=str(plan.intent.value),
            observed_disposition=str(plan.disposition.value),
            observed_route=route,
            evidence_count=len(evidence),
            expected_evidence_count=expected_evidence_count,
            evidence_recall=evidence_recall,
            provenance_valid=provenance_valid,
            citation_membership_valid=citation_valid,
            abstained=abstained,
            passed=not failures,
            failures=tuple(failures),
        ))

    route_counts = Counter(item.observed_route for item in outcomes)
    task_counts = Counter(item.task_type for item in outcomes)
    route_confusion = Counter(
        (item.expected_route, item.observed_route) for item in outcomes
    )
    task_metrics: dict[str, Any] = {}
    for task_type in sorted(task_counts):
        task_outcomes = [item for item in outcomes if item.task_type == task_type]
        recalls = [item.evidence_recall for item in task_outcomes if item.evidence_recall is not None]
        task_metrics[task_type] = {
            "cases": len(task_outcomes),
            "passed_cases": sum(item.passed for item in task_outcomes),
            "failed_cases": sum(not item.passed for item in task_outcomes),
            "mean_evidence_recall": mean(recalls) if recalls else None,
            "route_counts": dict(sorted(Counter(item.observed_route for item in task_outcomes).items())),
        }
    answerable = [item for item in outcomes if item.answerability == "answerable"]
    partially_answerable = [item for item in outcomes if item.answerability == "partially_answerable"]
    unanswerable = [item for item in outcomes if item.answerability == "unanswerable"]
    false_abstentions = sum(item.observed_route == "abstain" for item in answerable + partially_answerable)
    correct_abstentions = sum(item.observed_route == "abstain" for item in unanswerable)
    incorrect_unanswerable_answers = sum(item.observed_route != "abstain" for item in unanswerable)
    return {
        "report_schema_version": 1,
        "benchmark": {
            "dataset_id": dataset.dataset_id,
            "dataset_version": dataset.dataset_version,
            "dataset_sha256": hashlib.sha256(
                dataset.model_dump_json().encode("utf-8")
            ).hexdigest(),
        },
        "execution": {
            "commit": commit,
            "environment": environment,
            "llm_calls": 0,
            "database_writes": 0,
        },
        "summary": {
            "reviewed_cases": len(outcomes),
            "passed_cases": sum(item.passed for item in outcomes),
            "failed_cases": sum(not item.passed for item in outcomes),
            "excluded_cases": sum(excluded.values()),
            "excluded_by_review_status": dict(sorted(excluded.items())),
            "scope_violations": sum(not item.provenance_valid for item in outcomes),
            "mean_evidence_recall": mean(
                item.evidence_recall for item in outcomes if item.evidence_recall is not None
            ) if any(item.evidence_recall is not None for item in outcomes) else None,
            "citation_membership_violations": sum(
                not item.citation_membership_valid for item in outcomes
            ),
            "route_counts": dict(sorted(route_counts.items())),
            "task_counts": dict(sorted(task_counts.items())),
            "route_confusion_matrix": {
                f"{expected}->{observed}": count
                for (expected, observed), count in sorted(route_confusion.items())
            },
            "per_task": task_metrics,
            "abstention": {
                "answerable_cases": len(answerable),
                "partially_answerable_cases": len(partially_answerable),
                "unanswerable_cases": len(unanswerable),
                "false_abstentions": false_abstentions,
                "correct_abstentions": correct_abstentions,
                "incorrect_answers_on_unanswerable_cases": incorrect_unanswerable_answers,
            },
        },
        "semantic_claim_support": {
            "status": "not_evaluated",
            "reason": "Requires independent human claim-to-evidence review.",
        },
        "outcomes": [asdict(item) for item in outcomes],
    }


def write_report(report: Mapping[str, Any], path: str | Path) -> None:
    """Write a stable JSON report; callers choose an approved artifact location."""
    Path(path).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

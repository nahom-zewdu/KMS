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
    expected_route: str
    observed_intent: str
    observed_disposition: str
    observed_route: str
    evidence_count: int
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


def evaluate_planned_queries(
    dataset: BenchmarkDataset,
    executor: PlannedExecutor,
    *,
    commit: str,
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
        history = ()
        result = executor.execute(case.question, scope=scope, conversation_history=history)
        plan = result.plan
        evidence = tuple(getattr(result, "evidence", ()) or ())
        answer = getattr(result, "answer", None) or {}
        route = _observed_route(result)
        provenance_valid = _validate_provenance(case, evidence)
        citation_valid = (
            _validate_citation_membership(answer, evidence)
            if route == "planned_query" else not bool(answer.get("claims"))
        )
        abstained = route == "abstain"
        failures: list[str] = []
        if route != case.expected_route:
            failures.append("route_mismatch")
        if not provenance_valid:
            failures.append("evidence_provenance_mismatch")
        if not citation_valid:
            failures.append("citation_membership_mismatch")
        if case.expected_route == "planned_query" and not evidence:
            failures.append("expected_evidence_missing")
        if case.expected_route == "abstain" and not abstained:
            failures.append("expected_abstention_missing")

        outcomes.append(EvaluationOutcome(
            case_id=case.id,
            task_type=case.task_type,
            expected_route=case.expected_route,
            observed_intent=str(plan.intent.value),
            observed_disposition=str(plan.disposition.value),
            observed_route=route,
            evidence_count=len(evidence),
            provenance_valid=provenance_valid,
            citation_membership_valid=citation_valid,
            abstained=abstained,
            passed=not failures,
            failures=tuple(failures),
        ))

    route_counts = Counter(item.observed_route for item in outcomes)
    task_counts = Counter(item.task_type for item in outcomes)
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
            "citation_membership_violations": sum(
                not item.citation_membership_valid for item in outcomes
            ),
            "route_counts": dict(sorted(route_counts.items())),
            "task_counts": dict(sorted(task_counts.items())),
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

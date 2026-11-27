"""Production QueryEngine execution adapter for KRT-05.

Records observable production routing and disposition. Evidence provenance and
semantic claim support remain explicitly unmeasured by this adapter.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
import hashlib
import json
from typing import Any

EngineFactory = Callable[[Any], Any]


def _observed_route(event: Mapping[str, Any]) -> str:
    handler_route = str(event.get("route") or "unobserved")
    outcome = str(event.get("outcome") or "unknown")
    if handler_route == "conversation_guard":
        return handler_route
    if outcome == "abstained":
        return "abstain"
    return handler_route


def evaluate_production_path(
    dataset: Any,
    engine_factory: EngineFactory,
    *,
    commit: str,
    environment: str = "synthetic-offline",
) -> dict[str, Any]:
    """Run reviewed cases through QueryEngine.handle_query using isolated engines."""
    if not commit or not commit.strip():
        raise ValueError("commit is required for reproducible reports")
    if not environment or len(environment) > 128:
        raise ValueError("environment must be a non-empty bounded label")

    outcomes = []
    excluded = Counter()
    for case in dataset.cases:
        if case.review_status != "reviewed":
            excluded[case.review_status] += 1
            continue

        events: list[dict[str, Any]] = []
        engine = engine_factory(events.append)
        job = {
            "record_id": f"krt05:{case.id}",
            "company_id": case.scope.company_id,
            "repository": case.scope.repository_id,
            "content": case.question,
            "payload": {
                "question": case.question,
                "conversation_history": [
                    turn.model_dump() for turn in case.conversation_history
                ],
                "conversation_refs": list(case.conversation_refs),
            },
        }
        failures: list[str] = []
        answer: dict[str, Any] = {}
        execution_error = None
        try:
            raw_answer = engine.handle_query(job)
            answer = json.loads(raw_answer) if isinstance(raw_answer, str) else {}
            if not isinstance(answer, dict):
                raise ValueError("QueryEngine returned a non-object answer")
        except Exception as exc:
            execution_error = type(exc).__name__
            failures.append("execution_error")

        event = events[-1] if events else {}
        handler_route = str(event.get("route") or "unobserved")
        disposition = str(event.get("outcome") or "unobserved")
        route = _observed_route(event) if event else "unobserved"
        observed_intent = event.get("intent")
        reason = event.get("reason") or answer.get("abstain_reason")

        if not event:
            failures.append("production_outcome_unobserved")
        if len(events) > 1:
            failures.append("multiple_production_outcomes")
        if route != case.expected_route:
            failures.append("route_mismatch")
        if observed_intent != case.expected_intent:
            failures.append("intent_mismatch")
        abstained = bool(answer.get("abstain_reason"))
        if case.expected_route == "abstain" and not abstained:
            failures.append("expected_abstention_missing")
        if case.expected_route != "abstain" and case.answerability == "answerable" and abstained:
            failures.append("unexpected_abstention")

        outcomes.append({
            "case_id": case.id,
            "task_type": case.task_type,
            "answerability": case.answerability,
            "expected_route": case.expected_route,
            "observed_route": route,
            "observed_handler_route": handler_route,
            "observed_intent": observed_intent,
            "observed_disposition": disposition,
            "abstain_reason": reason,
            "evidence_count": event.get("evidence_count"),
            "execution_error": execution_error,
            "passed": not failures,
            "failures": failures,
            "evidence_provenance": "not_observable",
            "semantic_claim_support": "not_evaluated",
        })

    route_counts = Counter(item["observed_route"] for item in outcomes)
    confusion = Counter(
        (item["expected_route"], item["observed_route"]) for item in outcomes
    )
    task_counts = Counter(item["task_type"] for item in outcomes)
    return {
        "report_schema_version": 1,
        "evaluation_kind": "production_query_engine_path",
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
            "entrypoint": "QueryEngine.handle_query",
            "llm_calls": 0,
            "database_writes": 0,
            "engine_instance_per_case": True,
        },
        "summary": {
            "reviewed_cases": len(outcomes),
            "executed_cases": sum(item["execution_error"] is None for item in outcomes),
            "passed_cases": sum(item["passed"] for item in outcomes),
            "failed_cases": sum(not item["passed"] for item in outcomes),
            "excluded_cases": sum(excluded.values()),
            "excluded_by_review_status": dict(sorted(excluded.items())),
            "route_counts": dict(sorted(route_counts.items())),
            "task_counts": dict(sorted(task_counts.items())),
            "route_confusion_matrix": {
                f"{expected}->{observed}": count
                for (expected, observed), count in sorted(confusion.items())
            },
            "unobserved_outcomes": sum(
                item["observed_route"] == "unobserved" for item in outcomes
            ),
            "execution_errors": sum(
                item["execution_error"] is not None for item in outcomes
            ),
        },
        "measurement_limits": [
            "Evidence objects and provenance are not exposed by QueryEngine.handle_query.",
            "Citation membership and evidence recall are not measured by this adapter.",
            "Semantic claim support requires independent human review.",
            "A deterministic fixture run does not establish production database or RLS behavior.",
        ],
        "semantic_claim_support": {
            "status": "not_evaluated",
            "reason": "Requires independent human claim-to-evidence review.",
        },
        "outcomes": outcomes,
    }

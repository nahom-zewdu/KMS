"""Production QueryEngine execution adapter for KRT-05.

Records observable production routing, disposition, evidence provenance, and
citation membership. Semantic claim support remains a separate human review.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

EngineFactory = Callable[[Any], Any]


def _observed_route(event: Mapping[str, Any], expected_route: str) -> str:
    handler_route = str(event.get("route") or "unobserved")
    outcome = str(event.get("outcome") or "unknown")
    # "abstain" is an explicit final-route contract. Other expected routes
    # describe the handler selected, even when that handler safely abstains.
    # The outcome remains separately available as observed_disposition.
    if expected_route == "abstain" and outcome == "abstained":
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
            engine = engine_factory(events.append)
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
        route = _observed_route(event, case.expected_route) if event else "unobserved"
        # A conversation guard is an internal safety path, not successful
        # conversation-handler execution. Score its abstention as the final
        # route while retaining the guard in observed_handler_route.
        if handler_route == "conversation_guard" and disposition == "abstained":
            route = "abstain"
        observed_intent = event.get("intent")
        reason = event.get("reason") or answer.get("abstain_reason")
        evidence_items = event.get("evidence") or []
        source_records = event.get("source_records") or []
        source_company_id = event.get("source_company_id")
        expected_scope = case.scope
        evidence_scope_violations = [
            item for item in evidence_items
            if (
                item.get("company_id") != expected_scope.company_id
                or (
                    expected_scope.repository_id is not None
                    and item.get("repository_id") != expected_scope.repository_id
                )
                or (
                    expected_scope.snapshot_id is not None
                    and item.get("snapshot_id") != expected_scope.snapshot_id
                )
                or (
                    expected_scope.source_revision is not None
                    and item.get("source_revision") != expected_scope.source_revision
                )
            )
        ]
        evidence_ids = {
            str(item.get("evidence_id"))
            for item in evidence_items if item.get("evidence_id")
        }
        citation_ids = {
            str(evidence_id)
            for claim in answer.get("claims", [])
            if isinstance(claim, Mapping)
            for evidence_id in (claim.get("evidence_ids") or [])
            if isinstance(evidence_id, str)
        }
        unknown_citations = sorted(citation_ids - evidence_ids)
        structured_source_scope_valid = (
            bool(source_records)
            and source_company_id == expected_scope.company_id
        )
        structured_source_scope_mismatch = (
            bool(source_records)
            and source_company_id != expected_scope.company_id
        )
        if evidence_scope_violations or structured_source_scope_mismatch:
            failures.append("evidence_provenance_mismatch")
        if unknown_citations:
            failures.append("citation_membership_mismatch")

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
            "expected_intent": case.expected_intent,
            "observed_route": route,
            "observed_handler_route": handler_route,
            "observed_intent": observed_intent,
            "observed_disposition": disposition,
            "abstain_reason": reason,
            "evidence_count": event.get("evidence_count"),
            "evidence_provenance": (
                "valid" if evidence_items and not evidence_scope_violations
                else "valid_structured_records" if structured_source_scope_valid
                else "no_evidence" if not evidence_items and not source_records and not event.get("evidence_count")
                else "mismatch" if evidence_scope_violations or structured_source_scope_mismatch
                else "not_available_for_route"
            ),
            "evidence_items": evidence_items,
            "structured_source_records": source_records,
            "structured_source_company_id": source_company_id,
            "citation_ids": sorted(citation_ids),
            "unknown_citation_ids": unknown_citations,
            "execution_error": execution_error,
            "passed": not failures,
            "failures": failures,
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
            "engine_instance_per_case": True,
            "offline_guarantees": [
                "QueryEngine offline_evaluation mode returns before legacy LLM retrieval/synthesis fallbacks.",
                "The integration fixture asserts zero query-time database inserts and zero RPC calls.",
            ],
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
            "acceptance_passed": bool(outcomes) and all(item["passed"] for item in outcomes),
            "evidence_provenance_violations": sum(
                "evidence_provenance_mismatch" in item["failures"] for item in outcomes
            ),
            "citation_membership_violations": sum(
                "citation_membership_mismatch" in item["failures"] for item in outcomes
            ),
        },
        "measurement_limits": [
            "Code evidence provenance is checked against bounded evidence metadata; structured source records are checked against their observed company scope.",
            "Citation membership is checked against the observed evidence IDs; evidence recall against retrieval-task labels is not measured here.",
            "Semantic claim support requires independent human review.",
            "A deterministic fixture run does not establish production database or RLS behavior.",
        ],
        "semantic_claim_support": {
            "status": "not_evaluated",
            "reason": "Requires independent human claim-to-evidence review.",
        },
        "outcomes": outcomes,
    }


def write_report(report: Mapping[str, Any], path: str | Path) -> None:
    """Persist a complete evaluation report as stable, inspectable JSON."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

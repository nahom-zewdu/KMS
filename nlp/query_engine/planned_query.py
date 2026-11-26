"""Conservative orchestration boundary for KRT-04 planned queries.

This executor is intentionally not wired into QueryEngine yet. It composes the
validated planning, resolution, evidence, and grounded-answer contracts so the
complete route can be tested before changing production routing behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from .evidence import EvidenceCandidate
from .evidence_gatherer import BoundedEvidenceGatherer
from .grounded_answer import GroundedAnswerValidator
from .query_plan import QueryIntent, QueryPlan, QueryScope
from .query_planner import classify_query
from .symbol_resolution import ConservativeScipSymbolResolver
from .synthesizer import reasoning_synthesize_grounded


@dataclass(frozen=True, slots=True)
class PlannedQueryResult:
    """Outcome of a planned route, including explicit legacy-route deferral."""

    plan: QueryPlan
    answer: Mapping[str, Any] | None
    evidence: tuple[EvidenceCandidate, ...] = ()
    reason: str | None = None
    deferred: bool = False

    @property
    def completed(self) -> bool:
        """Whether a grounded answer or intentional no-retrieval answer exists."""
        return self.answer is not None and not self.deferred


class PlannedQueryExecutor:
    """Execute one bounded KRT-04 route without changing QueryEngine behavior."""

    def __init__(
        self,
        *,
        evidence_gatherer: BoundedEvidenceGatherer,
        symbol_resolver: ConservativeScipSymbolResolver,
        synthesizer=reasoning_synthesize_grounded,
        validator: GroundedAnswerValidator | None = None,
    ) -> None:
        self.evidence_gatherer = evidence_gatherer
        self.symbol_resolver = symbol_resolver
        self.synthesizer = synthesizer
        self.validator = validator or GroundedAnswerValidator()

    def execute(
        self,
        query: str,
        *,
        scope: QueryScope,
        conversation_history: Sequence[Mapping[str, object]] | None = None,
        conversation_refs: Sequence[str] = (),
        stage_observer: Callable[[str, float], None] | None = None,
    ) -> PlannedQueryResult:
        """Classify, retrieve, synthesize, and validate one supported query.

        ``stage_observer`` receives bounded stage names and elapsed milliseconds.
        Observer failures are isolated from query execution.
        """
        plan = self._measure_stage(
            "classification",
            lambda: classify_query(
                query,
                scope=scope,
                conversation_history=conversation_history,
                conversation_refs=conversation_refs,
            ),
            stage_observer,
        )

        if plan.intent is QueryIntent.COURTESY:
            return PlannedQueryResult(
                plan=plan,
                answer={
                    "answer": "You're welcome." if query.strip().casefold() in {
                        "thanks", "thank you", "thx"
                    } else "Hello. What would you like to explore in the codebase?",
                    "confidence": "high",
                    "sources": [],
                    "owners": [],
                    "abstain_reason": None,
                    "claims": [],
                },
            )

        if plan.intent is QueryIntent.STRUCTURED_FACT:
            return PlannedQueryResult(
                plan=plan, answer=None, reason="legacy_structured_route",
                deferred=True,
            )

        if plan.intent in {QueryIntent.FOLLOW_UP, QueryIntent.CLARIFICATION}:
            return PlannedQueryResult(
                plan=plan, answer=None, reason="conversation_context_route",
                deferred=True,
            )

        if plan.intent is QueryIntent.UNSUPPORTED or plan.disposition.value != "ready":
            return PlannedQueryResult(
                plan=plan,
                answer={
                    "answer": "I need a more specific codebase question to answer that reliably.",
                    "confidence": "low",
                    "sources": [],
                    "owners": [],
                    "abstain_reason": plan.abstention_reason or plan.ambiguity_reason or "query_not_ready",
                    "claims": [],
                },
                reason=plan.abstention_reason or plan.ambiguity_reason,
            )

        if plan.intent is QueryIntent.CALL_SITE_NAVIGATION:
            resolution = self._measure_stage(
                "symbol_resolution", lambda: self.symbol_resolver.resolve(plan), stage_observer
            )
            if not resolution.resolved or resolution.plan is None:
                return self._abstain(plan, resolution.reason or "symbol_resolution_failed")
            plan = resolution.plan

        gathered = self._measure_stage(
            "evidence_gathering", lambda: self.evidence_gatherer.gather(plan), stage_observer
        )
        if not gathered.gathered:
            return self._abstain(plan, gathered.reason or "no_relevant_evidence")

        raw = self._measure_stage(
            "synthesis", lambda: self.synthesizer(plan.query, gathered.evidence), stage_observer
        )
        validated = self._measure_stage(
            "citation_validation", lambda: self.validator.validate(raw, gathered.evidence), stage_observer
        )
        if not validated.accepted:
            return PlannedQueryResult(
                plan=plan,
                answer=validated.to_dict(),
                evidence=gathered.evidence,
                reason=validated.abstain_reason,
            )

        return PlannedQueryResult(
            plan=plan,
            answer=validated.to_dict(),
            evidence=gathered.evidence,
        )

    @staticmethod
    def _measure_stage(
        name: str,
        operation: Callable[[], Any],
        observer: Callable[[str, float], None] | None,
    ) -> Any:
        """Measure one stage without allowing instrumentation to affect behavior."""
        started = perf_counter()
        try:
            return operation()
        finally:
            if observer is not None:
                elapsed_ms = (perf_counter() - started) * 1000
                try:
                    observer(name, round(elapsed_ms, 3))
                except Exception:
                    # Observability must never change answer or failure semantics.
                    pass

    @staticmethod
    def _abstain(plan: QueryPlan, reason: str) -> PlannedQueryResult:
        return PlannedQueryResult(
            plan=plan,
            answer={
                "answer": "Not enough validated evidence to answer that yet.",
                "confidence": "low",
                "sources": [],
                "owners": [],
                "abstain_reason": reason,
                "claims": [],
            },
            reason=reason,
        )

"""Candidate discovery, gating, scoring, and sequencing for Ramp.

This module contains product reasoning over normalized evidence. It never reads
raw database tables directly and never invents company-specific implementation facts.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, Iterable, List, Sequence

from .models import Evidence, ImplementationSurface, RampCandidate, WorkflowCandidate


_STAGE_ORDER = {
    "orient": 0,
    "mental_model": 1,
    "role_surface": 2,
    "workflow": 3,
    "change_model": 4,
    "contribution": 5,
}


class RampCandidateEngine:
    """Discover and select evidence-backed learning outcomes."""

    LEARNING_WEIGHTS = {
        "role_relevance": 25.0,
        "prerequisite_value": 20.0,
        "evidence_strength": 20.0,
        "workflow_value": 15.0,
        "actionability": 10.0,
        "verification_strength": 5.0,
        "help_available": 5.0,
    }

    def score(self, candidate: RampCandidate) -> float:
        """Return a deterministic weighted learning score."""
        return candidate.score

    def eligible(self, candidate: RampCandidate) -> bool:
        """Apply hard gates before a learning candidate can be selected."""
        if not candidate.company_scoped:
            return False
        if not candidate.evidence_refs or not candidate.implementation_refs:
            return False
        if not candidate.concrete_action or not candidate.verification_method:
            return False
        if candidate.risk in {"high", "unknown"}:
            return False
        if candidate.contribution_candidate:
            return self.contribution_eligible(candidate)
        return candidate.evidence_strength > 0.0

    def contribution_eligible(self, candidate: RampCandidate) -> bool:
        """Require stronger evidence before a candidate proposes real code changes."""
        return (
            candidate.company_scoped
            and candidate.contribution_candidate
            and candidate.evidence_strength >= 0.8
            and candidate.verification_strength >= 0.8
            and candidate.history_strength >= 0.6
            and candidate.risk == "low"
            and bool(candidate.implementation_refs)
            and bool(candidate.concrete_action)
            and bool(candidate.verification_method)
        )

    def from_workflow(self, workflow: WorkflowCandidate) -> RampCandidate:
        """Convert a workflow candidate into the common selection representation."""
        candidate = RampCandidate(
            candidate_id=workflow.candidate_id,
            candidate_type="workflow-learning",
            stage=workflow.stage,
            objective=workflow.objective,
            implementation_refs=list(workflow.implementation_refs),
            evidence_refs=list(workflow.evidence_refs),
            prerequisites=list(workflow.prerequisites),
            role_relevance=workflow.role_relevance,
            prerequisite_value=workflow.prerequisite_value,
            evidence_strength=self._normalize_confidence(workflow.confidence),
            workflow_value=workflow.workflow_value,
            actionability=workflow.actionability,
            verification_strength=workflow.verification_strength,
            help_available=workflow.help_available,
            risk=workflow.risk,
            company_scoped=True,
            concrete_action=workflow.action,
            verification_method=workflow.verification,
            contribution_candidate=workflow.contribution_candidate,
            metadata={"signals": workflow.signals, "selection_reason": workflow.selection_reason},
        )
        return candidate

    def select(self, candidates: Sequence[RampCandidate]) -> List[RampCandidate]:
        """Select a non-redundant ordered set, respecting prerequisites and stage progression."""
        eligible = [candidate for candidate in candidates if self.eligible(candidate)]
        selected: List[RampCandidate] = []
        satisfied = set()

        while eligible:
            ready = [
                candidate for candidate in eligible
                if all(prerequisite in satisfied for prerequisite in candidate.prerequisites)
            ]
            if not ready:
                # Missing prerequisites are evidence gaps, not permission to invent them.
                break
            ready.sort(key=lambda item: (-self.score(item), _STAGE_ORDER.get(item.stage, 99), item.candidate_id))
            chosen = ready[0]
            selected.append(chosen)
            satisfied.add(chosen.candidate_id)
            satisfied.add(chosen.stage)
            eligible = [item for item in eligible if item.candidate_id != chosen.candidate_id]

        return selected

    @staticmethod
    def _normalize_confidence(confidence: str) -> float:
        """Map qualitative evidence confidence to the bounded scoring scale."""
        return {"direct": 1.0, "derived": 0.8, "inferred": 0.4, "missing": 0.0}.get(
            (confidence or "missing").lower(), 0.0
        )

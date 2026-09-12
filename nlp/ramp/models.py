"""Core data structures for evidence-first Ramp generation.

These models intentionally separate company facts from Ramp presentation. The
intelligence layer works with typed evidence and candidates; the API layer later
serializes those candidates into the existing frontend contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Evidence:
    """A company-scoped fact or signal available to Ramp reasoning."""

    ref: str
    source: str
    kind: str
    strength: str = "direct"
    detail: str = ""
    repository_id: Optional[str] = None
    module_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImplementationSurface:
    """A concrete codebase surface that can be inspected or changed."""

    ref: str
    path: str
    repository_id: Optional[str]
    module_path: Optional[str]
    language: Optional[str]
    importance: float = 0.0
    last_author: Optional[str] = None
    last_commit_sha: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowCandidate:
    """An evidence-backed behavioral workflow candidate."""

    candidate_id: str
    name: str
    stage: str
    implementation_refs: List[str]
    evidence_refs: List[str]
    signals: List[Dict[str, Any]]
    confidence: str
    role_relevance: float
    prerequisite_value: float
    workflow_value: float
    actionability: float
    verification_strength: float
    help_available: float
    history_strength: float = 0.0
    risk: str = "unknown"
    objective: str = ""
    action: str = ""
    verification: str = ""
    prerequisites: List[str] = field(default_factory=list)
    contribution_candidate: bool = False
    selection_reason: str = ""


@dataclass(frozen=True)
class RampCandidate:
    """Normalized candidate used by deterministic selection and sequencing."""

    candidate_id: str
    candidate_type: str
    stage: str
    objective: str
    implementation_refs: List[str]
    evidence_refs: List[str]
    prerequisites: List[str]
    role_relevance: float
    prerequisite_value: float
    evidence_strength: float
    workflow_value: float
    actionability: float
    verification_strength: float
    help_available: float
    risk: str
    company_scoped: bool
    concrete_action: str
    verification_method: str
    contribution_candidate: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def score_breakdown(self) -> Dict[str, float]:
        """Return the RID-04 weighted learning score breakdown."""
        weights = {
            "role_relevance": 25.0,
            "prerequisite_value": 20.0,
            "evidence_strength": 20.0,
            "workflow_value": 15.0,
            "actionability": 10.0,
            "verification_strength": 5.0,
            "help_available": 5.0,
        }
        values = {
            "role_relevance": self.role_relevance,
            "prerequisite_value": self.prerequisite_value,
            "evidence_strength": self.evidence_strength,
            "workflow_value": self.workflow_value,
            "actionability": self.actionability,
            "verification_strength": self.verification_strength,
            "help_available": self.help_available,
        }
        return {key: round(values[key] * weight, 2) for key, weight in weights.items()}

    @property
    def score(self) -> float:
        """Return the total deterministic learning score."""
        return round(sum(self.score_breakdown.values()), 2)

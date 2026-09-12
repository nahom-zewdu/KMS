"""Workflow candidate discovery over the normalized KMS evidence model."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence

from .models import Evidence, ImplementationSurface, WorkflowCandidate


class WorkflowDiscoverer:
    """Find plausible behavioral workflow surfaces without claiming unsupported call graphs."""

    WORKFLOW_FAMILIES = {
        "github_ingestion": ("github", "webhook", "ingest", "redis"),
        "slack_ingestion": ("slack", "webhook", "ingest", "redis"),
        "query_retrieval": ("query", "retriever", "search", "vector"),
        "codebase_sync": ("codebase", "baseline", "sync", "repository"),
    }

    def discover(
        self,
        surfaces: Sequence[ImplementationSurface],
        evidence: Sequence[Evidence],
        role: str,
    ) -> List[WorkflowCandidate]:
        """Return workflow candidates supported by multiple implementation surfaces."""
        result: List[WorkflowCandidate] = []
        role_tokens = self._role_tokens(role)

        for name, tokens in self.WORKFLOW_FAMILIES.items():
            matching = [
                surface
                for surface in surfaces
                if self._contains_any(surface.path, tokens)
                or self._contains_any(surface.module_path or "", tokens)
            ]
            matching = sorted(matching, key=lambda item: (-item.importance, item.path))
            if len(matching) < 2:
                continue

            role_matches = [
                item for item in matching if self._contains_any(item.path, role_tokens)
            ]
            relevance = 1.0 if role_matches else 0.65
            refs = [item.path for item in matching[:8]]
            signals = [
                {
                    "label": token,
                    "kind": "inferred",
                    "source": "codebase_files",
                    "corroboration": sum(1 for item in matching if token in item.path.lower()),
                }
                for token in tokens
                if any(token in item.path.lower() for item in matching)
            ]
            family_label = name.replace("_", " ")
            result.append(
                WorkflowCandidate(
                    candidate_id=f"workflow:{name}",
                    name=family_label,
                    stage="workflow",
                    implementation_refs=refs,
                    evidence_refs=list(dict.fromkeys(refs)),
                    signals=signals,
                    confidence="derived" if len(matching) >= 3 else "inferred",
                    role_relevance=relevance,
                    prerequisite_value=0.8,
                    workflow_value=0.9,
                    actionability=0.9,
                    verification_strength=0.95,
                    help_available=0.7 if any(item.last_author for item in matching) else 0.0,
                    history_strength=0.0,
                    risk="review",
                    objective=self._objective(family_label, refs),
                    action=self._action(family_label, refs),
                    verification=self._verification(family_label, refs),
                    prerequisites=[],
                    contribution_candidate=False,
                    selection_reason=(
                        "Selected from multiple company-scoped implementation surfaces. "
                        "The workflow shape is a candidate inferred from indexed structure and must be verified in source."
                    ),
                )
            )
        return result

    @staticmethod
    def _contains_any(value: str, tokens: Sequence[str]) -> bool:
        lowered = (value or "").lower()
        return any(token in lowered for token in tokens)

    @staticmethod
    def _role_tokens(role: str) -> Sequence[str]:
        normalized = (role or "").lower()
        if "frontend" in normalized:
            return ("frontend", "components", "app", "ui")
        if "data" in normalized:
            return ("data", "pipeline", "worker", "nlp", "analytics")
        return ("api", "handler", "service", "repository", "worker", "ingest", "engine")

    @staticmethod
    def _objective(name: str, refs: Sequence[str]) -> str:
        return (
            f"Build a verified mental model of the {name} workflow using the indexed implementation surfaces, "
            "including its entry point, major boundaries, data movement, and failure/verification points."
        )

    @staticmethod
    def _action(name: str, refs: Sequence[str]) -> str:
        return (
            f"Start with the highest-ranked indexed implementation surface for {name}, then trace only relationships "
            "that are visible in source code. Record the actual control and data flow and flag unsupported links as unknown."
        )

    @staticmethod
    def _verification(name: str, refs: Sequence[str]) -> str:
        return (
            "Open the referenced source files and verify each claimed boundary directly. The outcome is complete only "
            "when the engineer can explain the observed flow and identify where the indexed evidence stops."
        )

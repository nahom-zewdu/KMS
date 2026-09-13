"""Evidence-derived workflow candidate discovery for Ramp."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from .models import Evidence, ImplementationSurface, WorkflowCandidate


class WorkflowDiscoverer:
    """Discover behavioral candidates from observed implementation relationships.

    Workflow names are labels assigned after a connected evidence cluster is found;
    they are never used as a lookup taxonomy. Path vocabulary is only a weak tie-breaker.
    """

    _RELATION_STRENGTH = {"direct": 1.0, "derived": 0.8, "inferred": 0.4, "missing": 0.0}

    def discover(
        self,
        surfaces: Sequence[ImplementationSurface],
        evidence: Sequence[Evidence],
        role: str,
    ) -> List[WorkflowCandidate]:
        """Return only workflow candidates supported by connected implementation evidence."""
        by_path = {surface.path: surface for surface in surfaces}
        relations = [
            item for item in evidence
            if item.kind == "implementation_relation"
            and item.metadata.get("source_ref") in by_path
            and item.metadata.get("target_ref") in by_path
        ]
        if not relations:
            return []

        adjacency: Dict[str, List[Tuple[str, Evidence]]] = defaultdict(list)
        for relation in relations:
            source = str(relation.metadata["source_ref"])
            target = str(relation.metadata["target_ref"])
            adjacency[source].append((target, relation))
            adjacency[target].append((source, relation))

        components = self._components(adjacency)
        role_tokens = self._role_tokens(role)
        result: List[WorkflowCandidate] = []

        for index, component in enumerate(components):
            component_surfaces = [by_path[path] for path in component if path in by_path]
            component_relations = [
                relation for relation in relations
                if relation.metadata.get("source_ref") in component
                and relation.metadata.get("target_ref") in component
            ]
            if len(component_surfaces) < 2 or not self._behaviorally_connected(component_relations):
                continue

            component_surfaces.sort(key=lambda item: (-item.importance, item.path))
            role_relevant = any(
                self._contains_any(surface.path, role_tokens)
                or self._contains_any(surface.module_path or "", role_tokens)
                for surface in component_surfaces
            )
            relation_strength = max(
                (self._RELATION_STRENGTH.get(item.strength, 0.0) for item in component_relations),
                default=0.0,
            )
            relation_count = len(component_relations)
            confidence = "direct" if relation_strength >= 1.0 else "derived" if relation_strength >= 0.8 else "inferred"
            label = self._label(component_surfaces)
            candidate_id = self._candidate_id(component_surfaces, component_relations)
            refs = [surface.path for surface in component_surfaces[:8]]
            result.append(
                WorkflowCandidate(
                    candidate_id=f"workflow:{candidate_id}",
                    name=label,
                    stage="workflow",
                    implementation_refs=refs,
                    evidence_refs=[item.ref for item in component_relations] + refs,
                    signals=[
                        {
                            "label": item.metadata.get("relation_type", "implementation relation"),
                            "kind": item.strength,
                            "source": item.source,
                            "from": item.metadata.get("source_ref"),
                            "to": item.metadata.get("target_ref"),
                        }
                        for item in component_relations[:12]
                    ],
                    confidence=confidence,
                    role_relevance=1.0 if role_relevant else 0.65,
                    prerequisite_value=min(1.0, 0.65 + min(relation_count, 5) * 0.07),
                    workflow_value=min(1.0, 0.65 + min(relation_count, 7) * 0.05),
                    actionability=0.9,
                    verification_strength=min(1.0, 0.55 + relation_strength * 0.35),
                    help_available=0.7 if any(surface.last_author for surface in component_surfaces) else 0.0,
                    history_strength=0.0,
                    risk="review",
                    objective=(
                        f"Trace the observed {label} behavior across the connected implementation surfaces, "
                        "separating verified relationships from unknown control or data flow."
                    ),
                    action=(
                        "Start from the highest-ranked referenced surface and follow only the observed implementation "
                        "relationships. Verify each boundary in source and mark any missing link as unknown."
                    ),
                    verification=(
                        "The workflow is complete when the engineer can explain the connected path using the referenced "
                        "source and identify exactly where KMS evidence ends."
                    ),
                    prerequisites=[],
                    contribution_candidate=False,
                    selection_reason=(
                        "Selected from a connected company-scoped implementation component; path names only influence "
                        "the human-readable label and role tie-breaker."
                    ),
                )
            )

        return self._deduplicate(result)

    @staticmethod
    def _components(adjacency: Dict[str, List[Tuple[str, Evidence]]]) -> List[List[str]]:
        """Return deterministic connected components of the observed relation graph."""
        components: List[List[str]] = []
        seen = set()
        for start in sorted(adjacency):
            if start in seen:
                continue
            stack = [start]
            component = []
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                component.append(current)
                stack.extend(neighbor for neighbor, _ in adjacency.get(current, []))
            components.append(sorted(component))
        return components

    @staticmethod
    def _behaviorally_connected(relations: Sequence[Evidence]) -> bool:
        """Require at least one relationship stronger than weak inference."""
        return any(item.strength in {"direct", "derived"} for item in relations)

    @staticmethod
    def _label(surfaces: Sequence[ImplementationSurface]) -> str:
        """Create a neutral label without pretending to know the business feature."""
        modules = [surface.module_path for surface in surfaces if surface.module_path]
        if modules:
            common = modules[0].split("/")[0]
            if common:
                return f"{common} implementation flow"
        return "connected implementation flow"

    @staticmethod
    def _candidate_id(
        surfaces: Sequence[ImplementationSurface], relations: Sequence[Evidence]
    ) -> str:
        """Create a stable content-derived identity for a workflow component."""
        relation_ids = sorted(str(item.ref) for item in relations)
        surface_ids = sorted(surface.path for surface in surfaces)
        import hashlib
        payload = "|".join(surface_ids + relation_ids)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _deduplicate(candidates: Sequence[WorkflowCandidate]) -> List[WorkflowCandidate]:
        """Remove exact and near-identical candidates deterministically."""
        result: List[WorkflowCandidate] = []
        seen = set()
        for candidate in sorted(candidates, key=lambda item: item.candidate_id):
            signature = tuple(sorted(candidate.implementation_refs))
            if signature in seen:
                continue
            seen.add(signature)
            result.append(candidate)
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

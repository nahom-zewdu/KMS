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
    _MAX_PATH_FILES = 8
    _MAX_CANDIDATES_PER_COMPONENT = 8

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

        directed_adjacency: Dict[str, List[Tuple[str, Evidence]]] = defaultdict(list)
        adjacency: Dict[str, List[Tuple[str, Evidence]]] = defaultdict(list)
        for relation in relations:
            source = str(relation.metadata["source_ref"])
            target = str(relation.metadata["target_ref"])
            directed_adjacency[source].append((target, relation))
            adjacency[source].append((target, relation))
            adjacency[target].append((source, relation))

        components = self._components(adjacency)
        role_tokens = self._role_tokens(role)
        result: List[WorkflowCandidate] = []

        for component in components:
            result.extend(
                self._discover_component_paths(
                    component, directed_adjacency, by_path, role_tokens, relations
                )
            )

        return self._deduplicate(result)

    def _discover_component_paths(
        self,
        component: Sequence[str],
        adjacency: Dict[str, List[Tuple[str, Evidence]]],
        by_path: Dict[str, ImplementationSurface],
        role_tokens: Sequence[str],
        relations: Sequence[Evidence],
    ) -> List[WorkflowCandidate]:
        """Return bounded directed paths from one weakly connected component."""
        component_set = set(component)
        incoming = {path: 0 for path in component}
        for source in component:
            for target, _ in adjacency.get(source, []):
                if target in component_set:
                    incoming[target] += 1

        starts = sorted(
            (path for path in component if adjacency.get(path) and incoming[path] == 0),
            key=lambda path: (-by_path[path].importance, path),
        )
        if not starts:
            starts = sorted(
                (path for path in component if adjacency.get(path)),
                key=lambda path: (-by_path[path].importance, path),
            )

        paths: List[Tuple[List[str], List[Evidence]]] = []
        for start in starts:
            paths.extend(self._bounded_paths(start, adjacency, component_set, by_path))

        candidates = [
            self._path_candidate(path, path_relations, by_path, role_tokens)
            for path, path_relations in paths
            if len(path) >= 2 and self._behaviorally_connected(path_relations)
        ]
        candidates.sort(
            key=lambda candidate: (
                -candidate.role_relevance,
                -max(by_path[path].importance for path in candidate.implementation_refs),
                -len(candidate.implementation_refs),
                tuple(candidate.implementation_refs),
            )
        )
        return candidates[: self._MAX_CANDIDATES_PER_COMPONENT]

    def _bounded_paths(
        self,
        start: str,
        adjacency: Dict[str, List[Tuple[str, Evidence]]],
        component: set[str],
        by_path: Dict[str, ImplementationSurface],
    ) -> List[Tuple[List[str], List[Evidence]]]:
        """Enumerate maximal simple paths with a fixed file bound."""
        paths: List[Tuple[List[str], List[Evidence]]] = []

        def visit(current_path: List[str], current_relations: List[Evidence]) -> None:
            neighbors = [
                (target, relation)
                for target, relation in adjacency.get(current_path[-1], [])
                if target in component and target not in current_path
            ]
            neighbors.sort(key=lambda item: (-by_path[item[0]].importance, item[0], item[1].ref))
            if len(current_path) >= self._MAX_PATH_FILES or not neighbors:
                if len(current_path) >= 2:
                    paths.append((current_path, current_relations))
                return
            for target, relation in neighbors:
                visit(current_path + [target], current_relations + [relation])

        visit([start], [])
        return paths

    def _path_candidate(
        self,
        path: List[str],
        path_relations: List[Evidence],
        by_path: Dict[str, ImplementationSurface],
        role_tokens: Sequence[str],
    ) -> WorkflowCandidate:
        """Build a candidate whose evidence is exactly the selected path."""
        path_surfaces = [by_path[item] for item in path]
        relation_strength = max(
            (self._RELATION_STRENGTH.get(item.strength, 0.0) for item in path_relations),
            default=0.0,
        )
        role_relevant = any(
            self._contains_any(surface.path, role_tokens)
            or self._contains_any(surface.module_path or "", role_tokens)
            for surface in path_surfaces
        )
        relation_count = len(path_relations)
        confidence = "direct" if relation_strength >= 1.0 else "derived" if relation_strength >= 0.8 else "inferred"
        label = self._label(path_surfaces)
        candidate_id = self._candidate_id(path_surfaces, path_relations)
        return WorkflowCandidate(
            candidate_id=f"workflow:{candidate_id}",
            name=label,
            stage="workflow",
            implementation_refs=path,
            evidence_refs=[item.ref for item in path_relations] + path,
            signals=[
                {
                    "label": item.metadata.get("relation_type", "implementation relation"),
                    "kind": item.strength,
                    "source": item.source,
                    "from": item.metadata.get("source_ref"),
                    "to": item.metadata.get("target_ref"),
                }
                for item in path_relations
            ],
            confidence=confidence,
            role_relevance=1.0 if role_relevant else 0.65,
            prerequisite_value=min(1.0, 0.65 + min(relation_count, 5) * 0.07),
            workflow_value=min(1.0, 0.65 + min(relation_count, 7) * 0.05),
            actionability=0.9,
            verification_strength=min(1.0, 0.55 + relation_strength * 0.35),
            help_available=0.7 if any(surface.last_author for surface in path_surfaces) else 0.0,
            history_strength=0.0,
            risk="review",
            objective=(
                f"Trace the observed {label} path across the referenced implementation surfaces, "
                "separating verified relationships from unknown control or data flow."
            ),
            action=(
                "Start from the first referenced surface and follow only the observed implementation "
                "relationships. Verify each boundary in source and mark any missing link as unknown."
            ),
            verification=(
                "The workflow is complete when the engineer can explain this bounded path using the referenced "
                "source and identify exactly where KMS evidence ends."
            ),
            prerequisites=[],
            contribution_candidate=False,
            selection_reason=(
                "Selected as a bounded directed implementation path; every referenced relationship is preserved "
                "as company-scoped evidence."
            ),
        )

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

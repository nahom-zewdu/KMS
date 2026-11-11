"""Evidence-first Ramp planner.

This is the new Ramp intelligence boundary. It does not inherit from or call the
legacy module-first generator. Persistence remains a separate adapter so the
planner can evolve independently of the API and frontend.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import quote
from typing import Any, Callable, Dict, List, Optional

from supabase import Client

from .candidates import RampCandidateEngine
from .evidence import RampEvidenceRetrievalError, RampEvidenceStore
from .models import Evidence, ImplementationSurface, RampCandidate
from .store import RampStore
from .workflows import WorkflowDiscoverer


logger = logging.getLogger(__name__)


class RampPlanner:
    """Generate deterministic, evidence-backed onboarding outcomes for a company role."""

    def __init__(self, supabase: Client):
        self.evidence = RampEvidenceStore(supabase)
        self.workflows = WorkflowDiscoverer()
        self.engine = RampCandidateEngine()
        self.store = RampStore(supabase)

    def generate(
        self,
        role: str,
        company_id: str,
        employee_name: Optional[str] = None,
        polish_why: bool = True,
    ) -> Dict[str, Any]:
        """Generate and persist a fresh Ramp plan from current company evidence."""
        company_id = (company_id or "").strip()
        if not company_id or company_id.lower() == "default":
            raise ValueError("A real company_id is required for Ramp generation")
        role_key = self._normalize_role(role)
        surfaces = self.evidence.implementation_surfaces(company_id)
        modules = self._optional_evidence(
            "module_records", lambda: self.evidence.module_records(company_id)
        )
        ownership = self._optional_evidence(
            "ownership", lambda: self.evidence.ownership(company_id)
        )
        history = self._optional_evidence(
            "github_history", lambda: self.evidence.github_history(company_id)
        )
        contribution_issues = self._optional_evidence(
            "github_contribution_issues", lambda: self.evidence.contribution_issues(company_id)
        )
        evidence = [self.evidence.evidence_for_surface(surface) for surface in surfaces]
        evidence.extend(
            Evidence(
                ref=issue["ref"],
                source="github_issue",
                kind="contribution_issue",
                strength="direct",
                detail=issue["title"],
                repository_id=issue["repository_id"],
                metadata=issue,
            )
            for issue in contribution_issues
        )
        evidence.extend(
            self._optional_evidence(
                "implementation_relationships",
                lambda: self.evidence.implementation_relationships(company_id),
            )
        )
        surfaces_by_path = {surface.path: surface for surface in surfaces}
        evidence_by_ref = {item.ref: item for item in evidence}

        candidates = self._build_candidates(
            role_key, company_id, surfaces, modules, evidence, ownership, history, contribution_issues
        )
        selected = self.engine.select(candidates)
        if not selected:
            raise ValueError(
                "Ramp generation produced no eligible candidates; the existing plan was left unchanged"
            )
        steps = [
            self._serialize(
                candidate, role_key, company_id, index + 1, surfaces_by_path, evidence_by_ref
            )
            for index, candidate in enumerate(selected)
        ]

        plan = {
            "company_id": company_id,
            "role": role_key,
            "employee_name": employee_name,
            "title": f"Ramp — {role_key}",
            "steps": steps,
            "meta": {
                "source": "ramp_v2",
                "version": 2,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "evidence": {
                    "implementation_surfaces": len(surfaces),
                    "modules": len(modules),
                    "ownership_signals": len(ownership),
                    "github_history_records": len(history),
                    "implementation_relationships": sum(
                        1 for item in evidence if item.kind == "implementation_relation"
                    ),
                    "contribution_issue_leads": len(contribution_issues),
                },
                "candidate_count": len(candidates),
                "selected_count": len(selected),
                "candidate_ids": [candidate.candidate_id for candidate in selected],
            },
            "is_active": True,
        }
        self.store.save_plan(plan)
        return plan

    @staticmethod
    def _optional_evidence(source: str, retrieve: Callable[[], List[Any]]) -> List[Any]:
        try:
            return retrieve()
        except RampEvidenceRetrievalError as exc:
            logger.warning(
                "Optional Ramp evidence unavailable; continuing without it",
                extra={
                    "ramp_evidence_source": source,
                    "ramp_evidence_operation": exc.operation,
                    "ramp_evidence_error_type": exc.error_type,
                },
            )
            return []

    def get_active(self, company_id: str, role: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the active plan through the persistence boundary."""
        return self.store.get_active(company_id, self._normalize_role(role), user_id)

    def update_step_progress(
        self, plan_id: str, step_id: str, company_id: str, user_id: str, status: str
    ) -> Dict[str, Any]:
        """Update one user's progress without coupling progress logic to generation."""
        return self.store.update_progress(plan_id, step_id, company_id, user_id, status)

    def get_step_progress(
        self, plan_id: str, step_id: str, company_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return one user's progress for one stable step."""
        return self.store.progress_for_plan(plan_id, company_id, user_id).get(str(step_id))

    def _build_candidates(
        self,
        role: str,
        company_id: str,
        surfaces: List[ImplementationSurface],
        modules: List[Dict[str, Any]],
        evidence: List[Evidence],
        ownership: List[Dict[str, Any]],
        history: List[Dict[str, Any]],
        contribution_issues: List[Dict[str, Any]],
    ) -> List[RampCandidate]:
        """Build the smallest useful candidate graph from currently available evidence."""
        candidates: List[RampCandidate] = []
        orientation = self._orientation_candidate(company_id, role, surfaces, modules, evidence)
        if orientation:
            candidates.append(orientation)

        role_surface = self._role_surface_candidate(company_id, role, surfaces, evidence, orientation)
        if role_surface:
            candidates.append(role_surface)

        workflows = self.workflows.discover(surfaces, evidence, role)
        for workflow in workflows:
            candidate = self.engine.from_workflow(workflow)
            candidate = self._with_prerequisite(candidate, role_surface.candidate_id if role_surface else "")
            candidates.append(candidate)

        candidates.extend(
            self._contribution_candidates(
                role, company_id, contribution_issues, surfaces,
                role_surface.candidate_id if role_surface else (orientation.candidate_id if orientation else ""),
            )
        )
        return candidates

    def _orientation_candidate(
        self,
        company_id: str,
        role: str,
        surfaces: List[ImplementationSurface],
        modules: List[Dict[str, Any]],
        evidence: List[Evidence],
    ) -> Optional[RampCandidate]:
        """Create an orientation outcome only when the company has structural evidence."""
        if not surfaces and not modules:
            return None
        refs = [surface.path for surface in surfaces[:6]]
        return RampCandidate(
            candidate_id=f"orient:codebase:{company_id}:{role}",
            candidate_type="orientation",
            stage="orient",
            objective="Understand the shape of the indexed engineering system before diving into a specific workflow.",
            implementation_refs=refs,
            evidence_refs=refs,
            prerequisites=[],
            role_relevance=0.75,
            prerequisite_value=1.0,
            evidence_strength=1.0 if refs else 0.0,
            workflow_value=0.45,
            actionability=0.8,
            verification_strength=0.8,
            help_available=0.5 if any(surface.last_author for surface in surfaces) else 0.0,
            risk="low",
            company_scoped=True,
            concrete_action="Review the highest-ranked indexed modules and files, identify the major repository boundaries, and write a short map of what each area appears to own. Mark any responsibility not supported by evidence as unknown.",
            verification_method="Verify the map against the indexed module/file records and source code; remove or mark unknown any responsibility that cannot be supported.",
            metadata={"module_count": len(modules)},
        )

    def _role_surface_candidate(
        self,
        company_id: str,
        role: str,
        surfaces: List[ImplementationSurface],
        evidence: List[Evidence],
        orientation: Optional[RampCandidate],
    ) -> Optional[RampCandidate]:
        """Identify the role's implementation surface without treating path names as ownership facts."""
        if not surfaces:
            return None
        role_tokens = self._role_tokens(role)
        relevant = [
            surface for surface in surfaces
            if any(token in surface.path.lower() or token in (surface.module_path or "").lower() for token in role_tokens)
        ]
        relevant = sorted(relevant, key=lambda item: (-item.importance, item.path))
        if not relevant:
            return None
        refs = [surface.path for surface in relevant[:8]]
        return RampCandidate(
            candidate_id=f"role-surface:{company_id}:{role}",
            candidate_type="role-surface",
            stage="role_surface",
            objective=f"Identify the implementation surfaces most relevant to the {role} role and understand what remains uncertain.",
            implementation_refs=refs,
            evidence_refs=refs,
            prerequisites=[orientation.candidate_id] if orientation else [],
            role_relevance=1.0,
            prerequisite_value=0.85,
            evidence_strength=0.9,
            workflow_value=0.7,
            actionability=0.85,
            verification_strength=0.9,
            help_available=0.7 if any(surface.last_author for surface in relevant) else 0.0,
            risk="low",
            company_scoped=True,
            concrete_action="Inspect the indexed role-relevant files and modules, group them by implementation boundary, and identify one boundary that the role is likely to work in. Treat path-based relevance as a discovery signal, not proof of ownership.",
            verification_method="Confirm the proposed role surface by reading source and available ownership/history evidence; record unsupported responsibility as unknown.",
        )

    def _contribution_candidates(
        self,
        role: str,
        company_id: str,
        issues: List[Dict[str, Any]],
        surfaces: List[ImplementationSurface],
        prerequisite: str = "",
    ) -> List[RampCandidate]:
        """Create narrowly gated contribution leads from explicit issue evidence."""
        by_path = {surface.path: surface for surface in surfaces}
        path_counts: Dict[str, int] = {}
        for surface in surfaces:
            path_counts[surface.path] = path_counts.get(surface.path, 0) + 1
        result: List[RampCandidate] = []
        role_tokens = self._role_tokens(role)
        for issue in issues:
            repository_id = str(issue.get("repository_id") or "")
            paths = [
                path for path in issue.get("file_paths", [])
                if path in by_path
                and by_path[path].repository_id == repository_id
                and path_counts.get(path) == 1
            ]
            if not paths:
                continue
            refs = [str(issue["ref"]), *paths]
            role_relevant = any(
                any(token in path.lower() for token in role_tokens) for path in paths
            )
            candidate = RampCandidate(
                candidate_id=f"contribution:{issue['repository_id']}:{issue['number']}",
                candidate_type="contribution-lead",
                stage="contribution",
                objective=f"Evaluate GitHub issue #{issue['number']}: {issue['title']}",
                implementation_refs=paths,
                evidence_refs=refs,
                prerequisites=[prerequisite] if prerequisite else [],
                role_relevance=1.0 if role_relevant else 0.65,
                prerequisite_value=0.7,
                evidence_strength=1.0,
                workflow_value=0.75,
                actionability=0.9,
                verification_strength=0.85,
                help_available=0.9,
                risk="low",
                company_scoped=True,
                concrete_action=(
                    f"Review the issue and its acceptance checks, then inspect {', '.join(paths)}. "
                    "Confirm the issue is still open and unassigned on GitHub before proposing a change. "
                    "Agree on scope with the maintainer before editing code."
                ),
                verification_method=(
                    "For each issue acceptance check, identify the relevant test or observable behavior. "
                    "Do not mark the issue complete until the maintainer-approved checks pass."
                ),
                contribution_candidate=True,
                history_strength=0.0,
                metadata={
                    "issue": issue,
                    "selection_reason": (
                        "Grounded in a tenant-scoped open, unassigned GitHub issue explicitly labeled "
                        "good-first-issue/help-wanted, with multiple acceptance checks and paths matching indexed files."
                    ),
                },
            )
            if self.engine.contribution_eligible(candidate):
                result.append(candidate)
        return result

    @staticmethod
    def _with_prerequisite(candidate: RampCandidate, prerequisite: str) -> RampCandidate:
        """Return a candidate with one explicit prerequisite when available."""
        if not prerequisite:
            return candidate
        return RampCandidate(**{**candidate.__dict__, "prerequisites": [prerequisite]})

    def _serialize(
        self,
        candidate: RampCandidate,
        role: str,
        company_id: str,
        order: int,
        surfaces_by_path: Dict[str, ImplementationSurface],
        evidence_by_ref: Dict[str, Evidence],
    ) -> Dict[str, Any]:
        """Serialize candidates with source paths and repository identity intact."""
        step_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"ramp-v2:{company_id}:{role}:{candidate.candidate_id}"))
        evidence = []
        for ref in candidate.evidence_refs:
            item = evidence_by_ref.get(ref)
            if item and item.kind == "contribution_issue":
                issue = item.metadata
                evidence.append({
                    "kind": "direct",
                    "source": "github_issue",
                    "label": issue.get("title"),
                    "detail": "Tenant-scoped GitHub issue event; status and assignment must be rechecked live.",
                    "record_id": issue.get("number"),
                    "issue_url": issue.get("url"),
                    "issue_number": issue.get("number"),
                    "repository_full_name": issue.get("repository_full_name"),
                    "repository_default_branch": issue.get("default_branch"),
                    "acceptance_checks": issue.get("acceptance_checks", []),
                })
                continue
            if item and item.kind == "implementation_relation":
                source_path = str(item.metadata.get("source_ref") or "")
                target_path = str(item.metadata.get("target_ref") or "")
                source_surface = surfaces_by_path.get(source_path)
                target_surface = surfaces_by_path.get(target_path)
                evidence.append({
                    "kind": item.strength,
                    "source": item.source,
                    "label": item.detail,
                    "detail": item.detail,
                    "record_id": ref.removeprefix("edge:"),
                    "file_path": source_path or None,
                    "related_file_path": target_path or None,
                    "repository_full_name": (source_surface.metadata.get("repository_full_name") if source_surface else None),
                    "repository_default_branch": (source_surface.metadata.get("repository_default_branch") if source_surface else None),
                })
                continue
            surface = surfaces_by_path.get(ref)
            if surface:
                evidence.append({
                    "kind": "direct",
                    "source": "codebase_files",
                    "label": ref,
                    "detail": "Company-scoped indexed implementation surface.",
                    "file_path": ref,
                    "module_path": surface.module_path,
                    "record_id": surface.ref,
                    "repository_full_name": surface.metadata.get("repository_full_name"),
                    "repository_default_branch": surface.metadata.get("repository_default_branch"),
                })
        implementation_surfaces = [
            surfaces_by_path[path] for path in candidate.implementation_refs if path in surfaces_by_path
        ]
        repository_names = {
            str(surface.metadata.get("repository_full_name"))
            for surface in implementation_surfaces
            if surface.metadata.get("repository_full_name")
        }
        repository_name = next(iter(repository_names)) if len(repository_names) == 1 else None
        repository_branches = {
            str(surface.metadata.get("repository_default_branch"))
            for surface in implementation_surfaces
            if surface.metadata.get("repository_default_branch")
        }
        repository_branch = next(iter(repository_branches)) if len(repository_branches) == 1 else "HEAD"

        def source_url(file_path: str) -> Optional[str]:
            surface = surfaces_by_path.get(file_path)
            if not surface:
                return None
            repository = surface.metadata.get("repository_full_name")
            branch = surface.metadata.get("repository_default_branch") or "HEAD"
            if not repository:
                return None
            encoded_path = "/".join(quote(part, safe="") for part in file_path.split("/"))
            return f"https://github.com/{repository}/blob/{quote(str(branch), safe='/')}/{encoded_path}"

        return {
            "id": step_id,
            "order": order,
            "title": self._title(candidate),
            "why": candidate.objective,
            "understand": candidate.objective,
            "do": candidate.concrete_action,
            "done_when": candidate.verification_method,
            "risk_tier": candidate.risk,
            "owners": [],
            "target": {
                "type": candidate.candidate_type,
                "path": candidate.candidate_id,
                "repo": repository_name,
                "default_branch": repository_branch,
                "files": [
                    {
                        "path": ref,
                        "type": "file",
                        "repository_id": surfaces_by_path[ref].repository_id,
                        "github_url": source_url(ref),
                    }
                    for ref in candidate.implementation_refs
                ],
            },
            "summary": {"what": candidate.objective, "how": candidate.concrete_action, "where": ", ".join(candidate.implementation_refs)},
            "resources": [
                {
                    "type": "file",
                    "path": ref,
                    "url": source_url(ref),
                }
                for ref in candidate.implementation_refs
            ],
            "checklist": [
                {"id": "inspect", "label": "Inspect the referenced implementation surfaces", "done": False},
                {"id": "trace", "label": "Verify the relevant boundary or workflow in source", "done": False},
                {"id": "unknowns", "label": "Record unsupported assumptions as unknown", "done": False},
                {"id": "explain", "label": "Explain the outcome without relying on path names alone", "done": False},
            ],
            "evidence": evidence,
            "machine": {
                "candidate_id": candidate.candidate_id,
                "candidate_type": candidate.candidate_type,
                "stage": candidate.stage,
                "score": candidate.score,
                "score_breakdown": candidate.score_breakdown,
                "prerequisites": candidate.prerequisites,
                "eligible": self.engine.eligible(candidate),
                "contribution_candidate": candidate.contribution_candidate,
                "selection_reason": candidate.metadata.get("selection_reason", "Selected from the evidence-backed Ramp candidate graph."),
                "evidence_refs": candidate.evidence_refs,
                "contribution_issue": candidate.metadata.get("issue") if candidate.contribution_candidate else None,
            },
            "overrides": {"title": False, "why": False, "owners": False, "risk_tier": False, "order": False},
        }

    @staticmethod
    def _title(candidate: RampCandidate) -> str:
        """Generate a user-facing title from the candidate outcome, not a directory name."""
        return {
            "orientation": "Map the engineering system",
            "role-surface": "Find your role's implementation surface",
            "workflow-learning": "Trace a connected implementation flow",
        }.get(candidate.candidate_type, "Understand a key engineering outcome")

    @staticmethod
    def _normalize_role(role: str) -> str:
        """Normalize role labels for stable candidate IDs and persistence."""
        return (role or "software-engineer").strip().lower().replace(" ", "-")

    @staticmethod
    def _role_tokens(role: str) -> List[str]:
        """Return discovery tokens for role relevance; these are never treated as ownership proof."""
        if "frontend" in role:
            return ["frontend", "components", "app", "ui"]
        if "data" in role:
            return ["data", "pipeline", "worker", "nlp", "analytics"]
        return ["api", "handler", "service", "repository", "worker", "ingest", "engine"]

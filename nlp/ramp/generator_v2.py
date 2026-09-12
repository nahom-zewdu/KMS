"""Evidence-first Ramp planner.

This is the new Ramp intelligence boundary. It does not inherit from or call the
legacy module-first generator. Persistence remains a separate adapter so the
planner can evolve independently of the API and frontend.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

from .candidates import RampCandidateEngine
from .evidence import RampEvidenceStore
from .models import Evidence, ImplementationSurface, RampCandidate
from .store import RampStore
from .workflows import WorkflowDiscoverer


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
        company_id: str = "default",
        employee_name: Optional[str] = None,
        polish_why: bool = True,
    ) -> Dict[str, Any]:
        """Generate and persist a fresh Ramp plan from current company evidence."""
        company_id = (company_id or "default").strip() or "default"
        role_key = self._normalize_role(role)
        surfaces = self.evidence.implementation_surfaces(company_id)
        modules = self.evidence.module_records(company_id)
        ownership = self.evidence.ownership(company_id)
        history = self.evidence.github_history(company_id)
        evidence = [self.evidence.evidence_for_surface(surface) for surface in surfaces]

        candidates = self._build_candidates(
            role_key, company_id, surfaces, modules, evidence, ownership, history
        )
        selected = self.engine.select(candidates)
        steps = [self._serialize(candidate, role_key, company_id, index + 1) for index, candidate in enumerate(selected)]

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
                },
                "candidate_count": len(candidates),
                "selected_count": len(selected),
                "candidate_ids": [candidate.candidate_id for candidate in selected],
            },
            "is_active": True,
        }
        self.store.save_plan(plan)
        return plan

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

        # Contribution candidates are intentionally absent until the evidence
        # model contains a bounded change plus reliable verification precedent.
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

    @staticmethod
    def _with_prerequisite(candidate: RampCandidate, prerequisite: str) -> RampCandidate:
        """Return a candidate with one explicit prerequisite when available."""
        if not prerequisite:
            return candidate
        return RampCandidate(**{**candidate.__dict__, "prerequisites": [prerequisite]})

    def _serialize(self, candidate: RampCandidate, role: str, company_id: str, order: int) -> Dict[str, Any]:
        """Serialize an evidence-backed candidate into the existing frontend step shape."""
        step_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"ramp-v2:{company_id}:{role}:{candidate.candidate_id}"))
        evidence = [
            {"kind": "direct", "source": "codebase_files", "label": ref, "detail": "Company-scoped indexed implementation surface.", "path": ref}
            for ref in candidate.evidence_refs
        ]
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
                "repo": None,
                "files": [{"path": ref, "type": "file"} for ref in candidate.implementation_refs],
            },
            "summary": {"what": candidate.objective, "how": candidate.concrete_action, "where": ", ".join(candidate.implementation_refs)},
            "resources": [{"type": "file", "path": ref} for ref in candidate.evidence_refs],
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
            },
            "overrides": {"title": False, "why": False, "owners": False, "risk_tier": False, "order": False},
        }

    @staticmethod
    def _title(candidate: RampCandidate) -> str:
        """Generate a user-facing title from the candidate outcome, not a directory name."""
        return {
            "orientation": "Map the engineering system",
            "role-surface": "Find your role's implementation surface",
            "workflow-learning": f"Trace the {candidate.candidate_id.split(':')[1].replace('_', ' ')} workflow",
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

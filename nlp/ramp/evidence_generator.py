"""Evidence-backed Ramp candidate generation for RID-05.

This module deliberately stays narrow: it derives one workflow-learning candidate
from KMS-indexed company evidence instead of embedding customer-specific source
paths or workflow facts in the generator.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ramp.generator import LearningCandidate, RampPlanGenerator


class EvidenceRampPlanGenerator(RampPlanGenerator):
    """Generate the first evidence-backed Ramp workflow from indexed company data.

    RID-05 intentionally implements one candidate class only. The base generator
    remains available as the compatibility implementation while this class owns
    the new evidence-first production path.
    """

    WORKFLOW_TOKENS = {
        "github": "GitHub integration surface",
        "webhook": "webhook entry surface",
        "handler": "request handling surface",
        "service": "service layer",
        "ingest": "ingestion surface",
        "repository": "persistence/queue repository surface",
        "redis": "Redis queue surface",
        "stream": "stream publication surface",
    }

    ROLE_TOKENS = {
        "backend": ("api", "handler", "service", "repository", "worker", "ingest", "redis"),
        "frontend": ("frontend", "components", "app", "ui"),
        "fullstack": ("api", "handler", "service", "repository", "frontend", "app"),
    }

    def _load_indexed_workflow_evidence(self, company_id: str, role: str) -> Dict[str, Any]:
        """Collect company-scoped file/module/history signals without hardcoded file paths."""
        company_id = (company_id or "default").strip() or "default"
        role_key = (role or "software-engineer").strip().lower()
        role_key = role_key.replace("-engineer", "").replace("-developer", "")

        files: List[Dict[str, Any]] = []
        modules: List[Dict[str, Any]] = []
        history: List[Dict[str, Any]] = []

        try:
            response = (
                self.supabase.table("codebase_files")
                .select(
                    "id, repository_id, file_path, file_name, module_path, language, "
                    "last_author, last_commit_sha, importance_score, metadata, company_id"
                )
                .eq("company_id", company_id)
                .limit(2000)
                .execute()
            )
            files = [row for row in (getattr(response, "data", None) or []) if isinstance(row, dict)]
        except Exception:
            files = []

        try:
            response = (
                self.supabase.table("codebase_modules")
                .select(
                    "id, repository_id, module_path, module_name, inferred_type, "
                    "description, importance_score, metadata, company_id"
                )
                .eq("company_id", company_id)
                .limit(500)
                .execute()
            )
            modules = [row for row in (getattr(response, "data", None) or []) if isinstance(row, dict)]
        except Exception:
            modules = []

        try:
            response = (
                self.supabase.table("raw_data")
                .select("record_id, event_id, source, content, created_at, company_id")
                .eq("company_id", company_id)
                .eq("source", "github")
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )
            history = [row for row in (getattr(response, "data", None) or []) if isinstance(row, dict)]
        except Exception:
            history = []

        def relevant(text: str) -> bool:
            lowered = (text or "").lower()
            return any(token in lowered for token in self.WORKFLOW_TOKENS)

        relevant_files = [
            row for row in files if relevant(row.get("file_path", "")) or relevant(row.get("module_path", ""))
        ]
        relevant_modules = [
            row for row in modules if relevant(row.get("module_path", "")) or relevant(row.get("module_name", ""))
        ]

        role_tokens = self.ROLE_TOKENS.get(role_key, self.ROLE_TOKENS["backend"])
        role_files = [
            row for row in relevant_files
            if any(token in (row.get("file_path") or row.get("module_path") or "").lower() for token in role_tokens)
        ]
        selected_files = role_files or relevant_files

        # Prefer concrete indexed file rows and preserve deterministic ordering.
        selected_files = sorted(
            selected_files,
            key=lambda row: (
                -(float(row.get("importance_score") or 0.0)),
                row.get("file_path") or "",
            ),
        )

        return {
            "files": selected_files,
            "modules": relevant_modules,
            "history": history,
            "company_id": company_id,
            "role": role,
        }

    def _derive_workflow_labels(self, evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Derive workflow labels from indexed path vocabulary, keeping them explicitly inferred."""
        labels: Dict[str, Dict[str, Any]] = {}
        for row in evidence.get("files", []):
            text = f"{row.get('file_path', '')} {row.get('module_path', '')}".lower()
            for token, label in self.WORKFLOW_TOKENS.items():
                if token in text:
                    labels.setdefault(
                        label,
                        {
                            "label": label,
                            "kind": "inferred",
                            "source": "codebase_files",
                            "corroboration": 0,
                        },
                    )["corroboration"] += 1

        return sorted(labels.values(), key=lambda item: item["label"])

    def build_github_ingestion_workflow_candidate(
        self, company_id: str, role: str
    ) -> Optional[LearningCandidate]:
        """Build a GitHub workflow candidate only from company-indexed evidence."""
        evidence = self._load_indexed_workflow_evidence(company_id, role)
        files = evidence["files"]
        modules = evidence["modules"]
        history = evidence["history"]
        workflow_labels = self._derive_workflow_labels(evidence)

        implementation_refs = [
            row.get("file_path")
            for row in files
            if row.get("file_path")
        ][:8]
        implementation_refs = list(dict.fromkeys(implementation_refs))

        # A learning candidate needs an actual implementation surface and a
        # workflow signal. If the index cannot provide both, stop rather than
        # inventing a company-specific workflow.
        if len(implementation_refs) < 2 or not workflow_labels:
            return None

        evidence_refs = list(implementation_refs)
        for row in modules[:5]:
            path = row.get("module_path")
            if path and path not in evidence_refs:
                evidence_refs.append(path)

        direct_signals = len(files) + len(modules)
        corroboration = max((item["corroboration"] for item in workflow_labels), default=0)
        evidence_strength = min(
            1.0,
            0.8 + (0.05 * min(4, max(0, direct_signals - 1))) + (0.05 * min(4, max(0, corroboration - 1))),
        )

        history_signal = any(
            isinstance(row.get("content"), str)
            and any(token in row["content"].lower() for token in ("github", "webhook", "ingest", "redis"))
            for row in history
        )
        workflow_value = 0.9 if len(workflow_labels) >= 2 else 0.75
        role_relevance = 1.0 if any(
            any(token in (row.get("file_path") or "").lower() for token in self.ROLE_TOKENS.get("backend", ()))
            for row in files
        ) else 0.65

        objective = (
            "Trace the indexed GitHub ingestion surface from its entry point through "
            "the implementation layers represented in the company codebase, then "
            "verify the actual runtime flow in code."
        )
        action = (
            "Start from the highest-ranked indexed GitHub-related implementation file, "
            "follow its calls into the other indexed workflow surfaces, and record the "
            "actual control/data flow without assuming a relationship that the code does not show."
        )
        verification = (
            "Open the referenced implementation files and verify the control/data-flow "
            "links directly in source code; mark any link not supported by source as unknown."
        )

        candidate = self._build_learning_candidate(
            candidate_id=f"workflow:github-ingestion:{company_id}:{role.strip().lower()}",
            candidate_type="workflow-learning",
            stage="workflow",
            objective=objective,
            evidence_refs=evidence_refs,
            implementation_refs=implementation_refs,
            workflow_refs=[item["label"] for item in workflow_labels],
            role_relevance=role_relevance,
            evidence_strength=evidence_strength,
            prerequisite_value=0.8,
            workflow_value=workflow_value,
            actionability=0.9,
            verification_strength=0.95,
            help_available=0.7 if any(row.get("last_author") for row in files) else 0.0,
            prerequisites=[],
            selection_reason=(
                "Selected from company-scoped indexed implementation evidence. "
                "Workflow labels are inferred from indexed paths and must be verified in source code."
            ),
            company_scoped=bool(company_id),
            concrete_action=action,
            verification_method=verification,
        )
        candidate.selection_metadata = {
            "company_id": company_id,
            "role": role,
            "eligible": True,
            "contribution_candidate": False,
            "selection_mode": "indexed_evidence",
            "evidence": [
                {
                    "path": row.get("file_path"),
                    "kind": "direct",
                    "source": "codebase_files",
                    "corroboration": 1,
                    "detail": "Company-scoped codebase index record.",
                }
                for row in files[:8]
                if row.get("file_path")
            ],
            "workflow_signals": workflow_labels,
            "history_signal": history_signal,
            "module_count": len(modules),
        }
        candidate.eligibility_status = "eligible" if self.is_learning_eligible(candidate) else "ineligible"
        candidate.score_breakdown = self.score_candidate(candidate)
        candidate.score = round(sum(candidate.score_breakdown.values()), 2)
        return candidate if candidate.eligibility_status == "eligible" else None

    def select_learning_candidate(
        self,
        role: str,
        company_id: str,
        prerequisites_met: bool = True,
    ) -> Optional[LearningCandidate]:
        """Select the RID-05 workflow candidate when indexed evidence is sufficient."""
        if not prerequisites_met:
            return None
        candidate = self.build_github_ingestion_workflow_candidate(company_id, role)
        if candidate is None:
            return None
        candidate.selection_metadata["prerequisites_satisfied"] = True
        candidate.selection_metadata["selection_reason"] = candidate.selection_reason
        candidate.eligibility_status = "selected"
        return candidate

    def _serialize_evidence_step(
        self, candidate: LearningCandidate, role: str, company_id: str
    ) -> Dict[str, Any]:
        """Serialize the RID-05 candidate into the existing Ramp frontend contract."""
        step_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"ramp-step:{company_id}:{role}:rid05:{candidate.candidate_id}",
            )
        )
        files = [{"path": ref, "type": "file"} for ref in candidate.implementation_refs]
        evidence = [
            {
                "kind": item.get("kind", "direct"),
                "source": item.get("source", "codebase_files"),
                "label": item.get("path"),
                "detail": item.get("detail", ""),
                "path": item.get("path"),
            }
            for item in candidate.selection_metadata.get("evidence", [])
        ]
        return {
            "id": step_id,
            "order": 1,
            "title": "Trace a real GitHub ingestion workflow",
            "why": candidate.selection_reason,
            "understand": candidate.objective,
            "do": candidate.concrete_action,
            "done_when": candidate.verification_method,
            "risk_tier": "review",
            "owners": [],
            "target": {"type": "workflow", "path": "github-ingestion", "repo": None, "files": files},
            "summary": {
                "what": candidate.objective,
                "how": candidate.concrete_action,
                "where": ", ".join(candidate.implementation_refs),
            },
            "resources": [{"type": "file", "path": ref} for ref in candidate.evidence_refs],
            "checklist": [
                {"id": "entry", "label": "Identify the indexed GitHub workflow entry surface", "done": False},
                {"id": "trace", "label": "Trace only relationships verified in source", "done": False},
                {"id": "unknowns", "label": "Record any unsupported relationship as unknown", "done": False},
                {"id": "verify", "label": "Verify the final flow directly in code", "done": False},
            ],
            "evidence": evidence,
            "machine": {
                "candidate_id": candidate.candidate_id,
                "path": "github-ingestion",
                "suggested_owners": [],
                "suggested_risk": "review",
                "selection_reason": candidate.selection_reason,
                "eligible": True,
                "contribution_candidate": False,
                "score": candidate.score,
                "score_breakdown": candidate.score_breakdown,
                "evidence_strength": candidate.evidence_strength,
                "workflow_signals": candidate.selection_metadata.get("workflow_signals", []),
            },
            "overrides": {
                "title": False,
                "why": False,
                "owners": False,
                "risk_tier": False,
                "order": False,
            },
        }

    def generate(
        self,
        role: str,
        company_id: str = "default",
        employee_name: Optional[str] = None,
        polish_why: bool = True,
    ) -> Dict[str, Any]:
        """Generate one evidence-backed Ramp outcome, or an explicit empty plan."""
        company_id = (company_id or "default").strip() or "default"
        role_key = role.strip().lower().replace(" ", "-")
        candidate = self.select_learning_candidate(role_key, company_id, prerequisites_met=True)
        if candidate is None:
            plan = self._empty_plan(
                role_key,
                company_id,
                employee_name,
                reason="no_evidence_backed_workflow_candidate",
            )
            self._save(plan)
            return plan

        step = self._serialize_evidence_step(candidate, role_key, company_id)
        plan = {
            "company_id": company_id,
            "role": role_key,
            "employee_name": employee_name,
            "title": f"First 7 Days — {role_key}",
            "steps": [step],
            "meta": {
                "source": "ramp_rid05",
                "module_count": int(candidate.selection_metadata.get("module_count") or 0),
                "file_count": len(candidate.implementation_refs),
                "owner_coverage": 0.0,
                "architecture_layers": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "candidate_id": candidate.candidate_id,
                "selection_score": candidate.score,
                "selection_metadata": candidate.selection_metadata,
            },
            "is_active": True,
        }
        self._save(plan)
        return plan

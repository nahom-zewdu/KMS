# nlp/ramp/generator.py
"""
First 7 Days ramp plan generator.

Builds a company-scoped, role-specific learning path from:
  - VisualizerService (modules, files, safe zones, ownership)
  - Knowledge graph edges (OWNS) when present
  - codebase_files.last_author when present

Structure is deterministic. LLM is used only to polish "why" text from facts.
Never invents people, files, or ownership.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

from visualizer.service import VisualizerService

logger = logging.getLogger(__name__)

# Optional LLM fail open to template why
try:
    from engine.llm import llm_infer
except Exception:  # pragma: no cover
    llm_infer = None  # type: ignore


class RampPlanGenerator:
    """Deterministic First 7 Days plan builder + persistence."""

    MAX_STEPS = 7

    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.visualizer = VisualizerService(supabase)

    def generate(
        self,
        role: str,
        company_id: str = "default",
        employee_name: Optional[str] = None,
        polish_why: bool = True,
    ) -> Dict[str, Any]:
        """
        Build and upsert an active ramp plan for (company_id, role).

        Returns the plan dict including steps and meta.
        """
        company_id = (company_id or "default").strip() or "default"
        role_key = role.strip().lower().replace(" ", "-")
        logger.info("Ramp generate | company=%s role=%s", company_id, role_key)

        viz = self.visualizer.build_for_role(role, company_id=company_id)
        if viz.get("error"):
            plan = self._empty_plan(
                role_key,
                company_id,
                employee_name,
                reason="visualizer_failed",
            )
            self._save(plan)
            return plan

        modules = viz.get("modules") or []
        key_files = viz.get("key_files") or []
        safe_zones = viz.get("safe_zones") or {}
        ownership = viz.get("ownership") or {}
        architecture = viz.get("architecture") or []

        if not modules and not key_files:
            plan = self._empty_plan(
                role_key,
                company_id,
                employee_name,
                reason="no_baseline",
            )
            self._save(plan)
            return plan

        owner_index = self._index_owners(ownership)
        safe_paths = {z.get("path") for z in (safe_zones.get("safe_first") or []) if z.get("path")}
        risk_paths = {z.get("path") for z in (safe_zones.get("high_risk") or []) if z.get("path")}

        steps = self._build_steps(
            role=role_key,
            modules=modules,
            key_files=key_files,
            owner_index=owner_index,
            safe_paths=safe_paths,
            risk_paths=risk_paths,
            architecture=architecture,
        )

        if polish_why and llm_infer and steps:
            steps = self._polish_why(steps, role_key, company_id)

        plan: Dict[str, Any] = {
            "company_id": company_id,
            "role": role_key,
            "employee_name": employee_name,
            "title": f"First 7 Days — {role_key}",
            "steps": steps,
            "meta": {
                "source": "ramp_v1",
                "module_count": len(modules),
                "file_count": len(key_files),
                "owner_coverage": self._owner_coverage(steps),
                "architecture_layers": [a.get("name") for a in architecture[:6]],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            "is_active": True,
        }
        self._save(plan)
        return plan

    def get_active(self, company_id: str, role: str) -> Optional[Dict[str, Any]]:
        """Fetch latest active plan for company + role."""
        company_id = (company_id or "default").strip() or "default"
        role_key = role.strip().lower().replace(" ", "-")
        try:
            res = (
                self.supabase.table("ramp_plans")
                .select("*")
                .eq("company_id", company_id)
                .eq("role", role_key)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if not res.data:
                return None
            row = res.data[0]
            return {
                "id": row.get("id"),
                "company_id": row.get("company_id"),
                "role": row.get("role"),
                "employee_name": row.get("employee_name"),
                "title": f"First 7 Days — {row.get('role')}",
                "steps": row.get("steps") or [],
                "meta": row.get("meta") or {},
                "is_active": row.get("is_active", True),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        except Exception as e:
            logger.error("ramp get_active failed: %s", e)
            return None

    # -------------------------------------------------------------------------
    # Step assembly
    # -------------------------------------------------------------------------

    def _build_steps(
        self,
        role: str,
        modules: List[Dict],
        key_files: List[Dict],
        owner_index: Dict[str, List[str]],
        safe_paths: set,
        risk_paths: set,
        architecture: List[Dict],
    ) -> List[Dict[str, Any]]:
        """
        Build a list of steps from modules and key files, with risk, owners, and evidence.
        """
        ranked = sorted(
            modules,
            key=lambda m: float(m.get("importance") or 0),
            reverse=True,
        )
        # Role keyword boost already applied in visualizer; keep top N
        steps: List[Dict[str, Any]] = []
        used_targets = set()

        # Fill from modules first
        for mod in ranked:
            if len(steps) >= self.MAX_STEPS:
                break
            path = (mod.get("path") or mod.get("name") or "").strip()
            if not path or path in used_targets:
                continue
            used_targets.add(path)

            related_files = [
                f
                for f in key_files
                if (f.get("module") or "").startswith(path)
                or (f.get("path") or "").startswith(path + "/")
                or (f.get("path") or "") == path
            ][:3]

            primary_file = related_files[0]["path"] if related_files else None
            risk = self._risk_tier(primary_file or path, safe_paths, risk_paths)
            owners = self._owners_for_target(path, related_files, owner_index)
            evidence = self._evidence_for(path, related_files)

            layer_hint = ""
            top = path.split("/")[0].lower()
            for layer in architecture:
                name = (layer.get("name") or "").lower()
                if top and top in name:
                    layer_hint = layer.get("name") or ""
                    break

            why = self._template_why(role, path, mod, risk, owners, layer_hint)

            steps.append(
                {
                    "order": len(steps) + 1,
                    "title": mod.get("name") or path.split("/")[-1],
                    "target": {
                        "type": "module",
                        "path": path,
                        "files": [f.get("path") for f in related_files if f.get("path")],
                    },
                    "why": why,
                    "risk_tier": risk,
                    "owners": owners,
                    "evidence": evidence,
                }
            )

        # If modules thin, fill from key files
        if len(steps) < self.MAX_STEPS:
            for f in key_files:
                if len(steps) >= self.MAX_STEPS:
                    break
                fpath = f.get("path")
                if not fpath or fpath in used_targets:
                    continue
                # skip pure noise
                if fpath.endswith((".gitignore", ".python-version")):
                    continue
                used_targets.add(fpath)
                risk = self._risk_tier(fpath, safe_paths, risk_paths)
                owners = self._owners_for_target(fpath, [f], owner_index)
                evidence = self._evidence_for(fpath, [f])
                steps.append(
                    {
                        "order": len(steps) + 1,
                        "title": f.get("name") or fpath.split("/")[-1],
                        "target": {"type": "file", "path": fpath, "files": [fpath]},
                        "why": self._template_why(
                            role, fpath, {"description": f.get("language")}, risk, owners, ""
                        ),
                        "risk_tier": risk,
                        "owners": owners,
                        "evidence": evidence,
                    }
                )

        return steps

    def _risk_tier(self, path: str, safe_paths: set, risk_paths: set) -> str:
        if path in risk_paths:
            return "high-risk"
        if path in safe_paths:
            return "safe"
        low = (path or "").lower()
        if any(k in low for k in ("test", "utils", "common", "helper", "docs", "config")):
            return "safe"
        if any(k in low for k in ("auth", "payment", "billing", "core", "main", "ingest")):
            return "high-risk"
        return "review"

    def _index_owners(self, ownership: Dict) -> Dict[str, List[str]]:
        """Map lowercase target token -> owner names."""
        idx: Dict[str, List[str]] = {}
        for row in ownership.get("key_owners") or []:
            person = (row.get("person") or "").strip()
            owns = str(row.get("owns") or "").strip()
            if not person:
                continue
            key = owns.lower()
            idx.setdefault(key, [])
            if person not in idx[key]:
                idx[key].append(person)
        return idx

    def _owners_for_target(
        self,
        target: str,
        files: List[Dict],
        owner_index: Dict[str, List[str]],
    ) -> List[str]:
        found: List[str] = []
        tokens = {target.lower(), target.split("/")[-1].lower()}
        for f in files:
            if f.get("path"):
                tokens.add(f["path"].lower())
                tokens.add(f["path"].split("/")[-1].lower())
            author = (f.get("last_author") or "").strip()
            if author and author not in found:
                found.append(author)

        for tok in tokens:
            for k, people in owner_index.items():
                if tok and (tok in k or k in tok):
                    for p in people:
                        if p not in found:
                            found.append(p)
        return found[:5]

    def _evidence_for(self, path: str, files: List[Dict]) -> List[Dict[str, str]]:
        evidence = [
            {
                "source": "codebase_module",
                "module_path": path,
                "record_id": "",
            }
        ]
        for f in files[:3]:
            if f.get("path"):
                evidence.append(
                    {
                        "source": "codebase_file",
                        "file_path": f["path"],
                        "record_id": "",
                    }
                )
        return evidence

    def _template_why(
        self,
        role: str,
        path: str,
        mod: Dict,
        risk: str,
        owners: List[str],
        layer_hint: str,
    ) -> str:
        desc = (mod.get("description") or "").strip()
        parts = [
            f"For a {role}, `{path}` is a high-signal area in this company's codebase."
        ]
        if layer_hint:
            parts.append(f"It sits under {layer_hint}.")
        if desc:
            parts.append(desc)
        if risk == "safe":
            parts.append("Marked lower risk for early exploration.")
        elif risk == "high-risk":
            parts.append("High business impact — read before changing.")
        if owners:
            parts.append("Known contacts: " + ", ".join(owners) + ".")
        else:
            parts.append("No ownership edge indexed yet — ask the team lead if unclear.")
        return " ".join(parts)

    def _polish_why(
        self, steps: List[Dict], role: str, company_id: str
    ) -> List[Dict]:
        """Optional LLM polish; facts only; never add new owners/paths."""
        if not llm_infer:
            return steps
        try:
            compact = [
                {
                    "order": s["order"],
                    "path": s["target"]["path"],
                    "risk": s["risk_tier"],
                    "owners": s["owners"],
                    "why": s["why"],
                }
                for s in steps
            ]
            prompt = f"""
You polish onboarding "why" blurbs for engineers.
Role: {role}
Company: {company_id}

Rules:
- Return valid JSON only: {{"items":[{{"order":1,"why":"..."}}]}}
- Only rephrase; do NOT add people, files, or claims not in input.
- Keep each why to 1-2 sentences.
- If owners empty, do not invent names.

Input:
{json.dumps(compact)}
""".strip()
            raw = llm_infer(prompt, temperature=0.2, max_tokens=800)
            cleaned = (raw or "").strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
            data = json.loads(cleaned)
            by_order = {int(i["order"]): i["why"] for i in data.get("items", []) if "order" in i and "why" in i}
            for s in steps:
                if s["order"] in by_order and by_order[s["order"]].strip():
                    s["why"] = by_order[s["order"]].strip()
        except Exception as e:
            logger.warning("why polish skipped: %s", e)
        return steps

    def _owner_coverage(self, steps: List[Dict]) -> float:
        if not steps:
            return 0.0
        with_owners = sum(1 for s in steps if s.get("owners"))
        return round(with_owners / len(steps), 2)

    def _empty_plan(
        self,
        role: str,
        company_id: str,
        employee_name: Optional[str],
        reason: str,
    ) -> Dict[str, Any]:
        msg = {
            "no_baseline": (
                "No indexed codebase for this company. "
                "Run baseline sync for a connected repo, then regenerate."
            ),
            "visualizer_failed": "Could not load codebase signals. Retry after baseline sync.",
        }.get(reason, "Insufficient company data for a grounded ramp.")

        return {
            "company_id": company_id,
            "role": role,
            "employee_name": employee_name,
            "title": f"First 7 Days — {role}",
            "steps": [],
            "meta": {
                "source": "ramp_v1",
                "empty_reason": reason,
                "message": msg,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "owner_coverage": 0.0,
            },
            "is_active": True,
        }

    def _save(self, plan: Dict[str, Any]) -> None:
        record = {
            "company_id": plan["company_id"],
            "role": plan["role"],
            "employee_name": plan.get("employee_name"),
            "steps": plan.get("steps") or [],
            "meta": plan.get("meta") or {},
            "is_active": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.supabase.table("ramp_plans").upsert(
                record, on_conflict="company_id,role"
            ).execute()
            logger.info(
                "Ramp saved | company=%s role=%s steps=%d",
                plan["company_id"],
                plan["role"],
                len(plan.get("steps") or []),
            )
        except Exception as e:
            logger.error("Ramp save failed: %s", e)
            raise

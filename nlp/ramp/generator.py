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

    ROLE_BOOST = {
        "backend": ("api", "handlers", "services", "repository", "domain", "nlp", "worker", "engine"),
        "frontend": ("app", "components", "ui", "web", "frontend"),
        "fullstack": ("api", "app", "nlp", "handlers"),
    }

    NOISE = (".gitignore", ".python-version", "go.sum", "package-lock.json", ".env")

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

        # Merge visualizer owners with DB signals (DB wins density)
        owner_index = self._index_owners(ownership)
        db_owners = self._load_owner_signals(company_id)
        for k, people in db_owners.items():
            bucket = owner_index.setdefault(k, [])
            for p in people:
                if p not in bucket:
                    bucket.append(p)

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

    def _load_owner_signals(self, company_id: str) -> Dict[str, List[str]]:
        """
        path/module/file token -> [person, ...]
        From codebase_files.last_author + OWNS edges.
        """
        idx: Dict[str, List[str]] = {}

        def add(token: str, person: str):
            token = (token or "").strip().lower()
            person = (person or "").strip().lower()
            if not token or not person:
                return
            bucket = idx.setdefault(token, [])
            if person not in bucket:
                bucket.append(person)

        try:
            files = (
                self.supabase.table("codebase_files")
                .select("file_path, module_path, last_author")
                .eq("company_id", company_id)
                .not_.is_("last_author", "null")
                .limit(2000)
                .execute()
            )
            for row in files.data or []:
                author = row.get("last_author")
                add(row.get("file_path"), author)
                add(row.get("module_path"), author)
                if row.get("file_path"):
                    add(row["file_path"].split("/")[-1], author)
        except Exception as e:
            logger.warning("last_author load failed: %s", e)

        try:
            edges = (
                self.supabase.table("edges")
                .select("source_id, target_id, type")
                .eq("company_id", company_id)
                .eq("type", "OWNS")
                .limit(2000)
                .execute()
            )
            if edges.data:
                ids = set()
                for e in edges.data:
                    ids.add(e["source_id"])
                    ids.add(e["target_id"])
                ent = (
                    self.supabase.table("entities")
                    .select("id, name, type, metadata")
                    .eq("company_id", company_id)
                    .in_("id", list(ids))
                    .execute()
                )
                by_id = {r["id"]: r for r in (ent.data or [])}
                for e in edges.data:
                    person = by_id.get(e["source_id"])
                    target = by_id.get(e["target_id"])
                    if not person or not target:
                        continue
                    if (person.get("type") or "").upper() != "PERSON":
                        continue
                    pname = person.get("name") or ""
                    meta = target.get("metadata") or {}
                    add(meta.get("file_path"), pname)
                    add(meta.get("module_path"), pname)
                    add(target.get("name"), pname)
        except Exception as e:
            logger.warning("OWNS edge load failed: %s", e)

        return idx

    def _build_steps( self, role: str, modules: List[Dict], key_files: List[Dict], owner_index: Dict[str, List[str]], safe_paths: set, risk_paths: set, architecture: List[Dict],) -> List[Dict[str, Any]]:
        """
        Path shape:
        1-2 safe entry
        3-5 role core
        6-7 high-risk / high-leverage
        """
        # Merge visualizer owners with DB signals (DB wins density)
        # owner_index already from _index_owners(viz); extend in generate() see note below

        def files_for(path: str) -> List[Dict]:
            out = []
            for f in key_files:
                fp = f.get("path") or ""
                if not fp or any(fp.endswith(n) or fp.split("/")[-1] == n for n in self.NOISE):
                    continue
                mod = f.get("module") or ""
                if mod == path or mod.startswith(path + "/") or fp.startswith(path + "/") or fp == path:
                    out.append(f)
                if len(out) >= 3:
                    break
            return out

        def score(mod: Dict) -> float:
            path = mod.get("path") or ""
            s = float(mod.get("importance") or 0) + self._role_boost(role, path)
            owners = self._owners_for_target(path, files_for(path), owner_index)
            if owners:
                s += 0.35
            fc = float((mod.get("file_count") or 0))
            s += min(0.25, fc / 40.0)
            return s

        safe_mods, core_mods, risk_mods = [], [], []
        for mod in modules:
            path = (mod.get("path") or "").strip()
            if not path or path in ("", "."):
                continue
            if path.lower() in ("doc", "docs") or path.lower().startswith("doc/"):
                # docs only allowed in safe slot, low priority
                safe_mods.append(mod)
                continue
            risk = self._risk_tier(path, safe_paths, risk_paths)
            if risk == "safe":
                safe_mods.append(mod)
            elif risk == "high-risk":
                risk_mods.append(mod)
            else:
                core_mods.append(mod)

        safe_mods.sort(key=score, reverse=True)
        core_mods.sort(key=score, reverse=True)
        risk_mods.sort(key=score, reverse=True)

        # Prefer role-boosted modules into core even if labeled review
        role_core = [m for m in core_mods if self._role_boost(role, m.get("path") or "") > 0]
        other_core = [m for m in core_mods if m not in role_core]
        core_ordered = role_core + other_core

        slots = [
            ("safe", safe_mods, 2),
            ("core", core_ordered, 3),
            ("high-risk", risk_mods, 2),
        ]

        steps: List[Dict[str, Any]] = []
        used = set()

        for slot_name, pool, limit in slots:
            taken = 0
            for mod in pool:
                if taken >= limit or len(steps) >= self.MAX_STEPS:
                    break
                path = (mod.get("path") or "").strip()
                if not path or path in used:
                    continue
                used.add(path)
                related = files_for(path)
                risk = self._risk_tier(path, safe_paths, risk_paths)
                if slot_name == "safe":
                    risk = "safe"
                elif slot_name == "high-risk":
                    risk = "high-risk"
                owners = self._owners_for_target(path, related, owner_index)
                layer_hint = ""
                top = path.split("/")[0].lower()
                for layer in architecture:
                    name = (layer.get("name") or "").lower()
                    if top and top in name:
                        layer_hint = layer.get("name") or ""
                        break
                title = self._step_title(slot_name, path, mod, role)
                steps.append(
                    {
                        "order": len(steps) + 1,
                        "title": title,
                        "target": {
                            "type": "module",
                            "path": path,
                            "files": [f.get("path") for f in related if f.get("path")],
                        },
                        "why": self._template_why(role, path, mod, risk, owners, layer_hint),
                        "risk_tier": risk,
                        "owners": owners,
                        "evidence": self._evidence_for(path, related),
                    }
                )
                taken += 1

        # Backfill if thin
        if len(steps) < self.MAX_STEPS:
            rest = sorted(modules, key=score, reverse=True)
            for mod in rest:
                if len(steps) >= self.MAX_STEPS:
                    break
                path = (mod.get("path") or "").strip()
                if not path or path in used:
                    continue
                used.add(path)
                related = files_for(path)
                risk = self._risk_tier(path, safe_paths, risk_paths)
                owners = self._owners_for_target(path, related, owner_index)
                steps.append(
                    {
                        "order": len(steps) + 1,
                        "title": self._step_title("core", path, mod, role),
                        "target": {
                            "type": "module",
                            "path": path,
                            "files": [f.get("path") for f in related if f.get("path")],
                        },
                        "why": self._template_why(role, path, mod, risk, owners, ""),
                        "risk_tier": risk,
                        "owners": owners,
                        "evidence": self._evidence_for(path, related),
                    }
                )

        return steps

    def _step_title(self, slot: str, path: str, mod: Dict, role: str) -> str:
        name = mod.get("name") or path.split("/")[-1]
        if slot == "safe":
            return f"Orient in `{name}`"
        if slot == "high-risk":
            return f"Read carefully: `{name}`"
        return f"Learn `{name}` ({role})"

    def _template_why(self, role: str, path: str, mod: Dict, risk: str, owners: List[str], layer_hint: str,) -> str:
        parts = []
        if risk == "safe":
            parts.append(f"`{path}` is a lower-risk place to learn how this repo is laid out.")
        elif risk == "high-risk":
            parts.append(f"`{path}` has high blast radius for a {role} — read before you change it.")
        else:
            parts.append(f"`{path}` is a core surface for a {role} on this codebase.")
        if layer_hint:
            parts.append(f"Architecture signal: {layer_hint}.")
        desc = (mod.get("description") or "").strip()
        if desc and "Module containing" not in desc:
            parts.append(desc)
        if owners:
            parts.append("Start with: " + ", ".join(owners) + ".")
        else:
            parts.append("No commit ownership indexed yet for this path.")
        return " ".join(parts)

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

    def _role_boost(self, role: str, path: str) -> float:
        role_l = role.lower()
        path_l = (path or "").lower()
        boost = 0.0
        for key, tokens in self.ROLE_BOOST.items():
            if key in role_l:
                if any(t in path_l for t in tokens):
                    boost += 0.4
                if path_l in ("doc", "docs") or path_l.startswith("doc/"):
                    boost -= 0.35
        return boost
    
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
import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

from visualizer.service import VisualizerService

logger = logging.getLogger(__name__)

STEP_PROGRESS_STATUSES = {"not_started", "in_progress", "completed"}

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
            company_id=company_id,
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

    def get_active(self, company_id: str, role: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
            plan = {
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
            if user_id:
                progress = self.get_progress_for_plan(plan_id=plan["id"], company_id=company_id, user_id=user_id)
                plan["progress"] = progress
            return plan
        except Exception as e:
            logger.error("ramp get_active failed: %s", e)
            return None

    def get_plan_by_id(self, plan_id: str, company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch a plan by id, optionally scoped to company."""
        try:
            query = self.supabase.table("ramp_plans").select("*").eq("id", plan_id)
            if company_id:
                query = query.eq("company_id", company_id)
            res = query.limit(1).execute()
            if not res.data:
                return None
            row = res.data[0]
            if company_id and str(row.get("company_id") or "").strip() and str(row.get("company_id") or "").strip() != str(company_id).strip():
                return None
            return {
                "id": row.get("id"),
                "company_id": row.get("company_id"),
                "role": row.get("role"),
                "employee_name": row.get("employee_name"),
                "title": row.get("title") or f"First 7 Days — {row.get('role')}",
                "steps": row.get("steps") or [],
                "meta": row.get("meta") or {},
                "is_active": row.get("is_active", True),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        except Exception as e:
            logger.error("ramp get_plan_by_id failed: %s", e)
            return None

    def get_progress_for_plan(self, plan_id: str, company_id: str, user_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Return per-step progress keyed by step id for a user in a company."""
        if not plan_id or not company_id:
            return {}
        try:
            query = self.supabase.table("ramp_step_progress").select("*").eq("plan_id", plan_id).eq("company_id", company_id)
            if user_id:
                query = query.eq("user_id", user_id)
            res = query.execute()
            rows = getattr(res, "data", []) or []
        except Exception as e:
            logger.warning("ramp progress fetch failed: %s", e)
            return {}

        progress = {}
        for row in rows:
            step_id = row.get("step_id")
            if not step_id:
                continue
            progress[str(step_id)] = {
                "id": row.get("id"),
                "plan_id": row.get("plan_id"),
                "company_id": row.get("company_id"),
                "step_id": step_id,
                "user_id": row.get("user_id"),
                "status": row.get("status", "not_started"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        return progress

    def get_step_progress(
        self,
        plan_id: str,
        step_id: str,
        company_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a single user's step-progress record."""
        if not plan_id or not step_id or not company_id or not user_id:
            return None
        try:
            res = (
                self.supabase.table("ramp_step_progress")
                .select("*")
                .eq("plan_id", plan_id)
                .eq("step_id", step_id)
                .eq("company_id", company_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = getattr(res, "data", []) or []
            if not rows:
                return None
            row = rows[0]
            return {
                "id": row.get("id"),
                "plan_id": row.get("plan_id"),
                "company_id": row.get("company_id"),
                "step_id": row.get("step_id"),
                "user_id": row.get("user_id"),
                "status": row.get("status", "not_started"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        except Exception as e:
            logger.warning("ramp get_step_progress failed: %s", e)
            return None

    def update_step_progress(
        self,
        plan_id: str,
        step_id: str,
        company_id: str,
        user_id: str,
        status: str,
    ) -> Dict[str, Any]:
        """Set a step progress state for a user in a company-scoped ramp plan."""
        normalized = (status or "").strip().lower()
        if normalized not in STEP_PROGRESS_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(STEP_PROGRESS_STATUSES))}")

        company_id = (company_id or "").strip() or "default"
        user_id = (user_id or "").strip()
        if not user_id:
            raise ValueError("user_id is required")

        plan = self.get_plan_by_id(plan_id, company_id=company_id)
        if not plan:
            raise ValueError(f"ramp plan not found for company_id={company_id} and plan_id={plan_id}")

        step = next((s for s in (plan.get("steps") or []) if str(s.get("id")) == str(step_id)), None)
        if step is None:
            raise KeyError(f"step_id {step_id} not found in plan {plan_id}")

        existing = self.get_step_progress(plan_id, step_id, company_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "plan_id": plan_id,
            "company_id": company_id,
            "step_id": step_id,
            "user_id": user_id,
            "status": normalized,
            "updated_at": now,
        }

        if existing:
            record["id"] = existing["id"]
            record["created_at"] = existing.get("created_at") or now
            if existing.get("status") == normalized:
                return {
                    "id": existing["id"],
                    "plan_id": plan_id,
                    "company_id": company_id,
                    "step_id": step_id,
                    "user_id": user_id,
                    "status": normalized,
                    "created_at": existing.get("created_at") or now,
                    "updated_at": existing.get("updated_at") or now,
                }
        else:
            record["id"] = str(uuid.uuid4())
            record["created_at"] = now

        try:
            self.supabase.table("ramp_step_progress").upsert(
                record,
                on_conflict="plan_id,step_id,user_id",
            ).execute()
        except Exception as e:
            logger.error("ramp step progress update failed: %s", e)
            raise

        return {
            "id": record["id"],
            "plan_id": plan_id,
            "company_id": company_id,
            "step_id": step_id,
            "user_id": user_id,
            "status": normalized,
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
        }

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

    def _resolve_target_reference(
        self,
        company_id: str,
        module_path: str,
        related_files: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Resolve the canonical repository + file references for a module target."""
        company_id = (company_id or "").strip()
        module_path = (module_path or "").strip()
        repo_rows: List[Dict[str, Any]] = []
        file_rows: List[Dict[str, Any]] = []

        def load_rows(table_name: str, columns: str, limit_count: int) -> List[Dict[str, Any]]:
            try:
                query = self.supabase.table(table_name).select(columns)
                if company_id:
                    query = query.eq("company_id", company_id)
                try:
                    query = query.limit(limit_count)
                except Exception:
                    pass
                response = query.execute()
                payload = getattr(response, "data", None)
                return payload if isinstance(payload, list) else []
            except Exception:
                return []

        repo_rows = load_rows("repositories", "id, full_name, company_id, default_branch", 50)
        file_rows = load_rows("codebase_files", "repository_id, file_path, file_name, module_path, company_id", 200)

        def valid_repo_row(row: Dict[str, Any]) -> bool:
            if not isinstance(row, dict):
                return False
            full_name = str(row.get("full_name") or "").strip()
            if not full_name:
                return False
            row_company_id = str(row.get("company_id") or "").strip()
            if company_id and row_company_id and row_company_id != company_id:
                return False
            return True

        def valid_file_row(row: Dict[str, Any]) -> bool:
            if not isinstance(row, dict):
                return False
            fp = row.get("file_path")
            if not isinstance(fp, str):
                return False
            fp = fp.strip()
            return bool(fp)

        repo_by_id = {str(r.get("id")): r for r in repo_rows if valid_repo_row(r) and str(r.get("id") or "").strip()}

        matched_files: List[Dict[str, Any]] = []
        for row in file_rows:
            if not valid_file_row(row):
                continue
            if company_id and str(row.get("company_id") or "").strip() and str(row.get("company_id") or "").strip() != company_id:
                continue
            fp = str(row.get("file_path") or "").strip()
            mod = str(row.get("module_path") or "").strip()
            if module_path:
                if mod and (mod == module_path or mod.startswith(module_path + "/")):
                    matched_files.append(row)
                elif fp == module_path or fp.startswith(module_path + "/"):
                    matched_files.append(row)
            elif fp:
                matched_files.append(row)

        if not matched_files and isinstance(related_files, list):
            for item in related_files:
                if not isinstance(item, dict):
                    continue
                fp = item.get("path") or item.get("file_path")
                if not isinstance(fp, str):
                    continue
                fp = fp.strip()
                if not fp:
                    continue
                matched_files.append({"file_path": fp, "module_path": module_path})

        repo_ref: Optional[Dict[str, Any]] = None
        chosen_repo_id: Optional[str] = None
        if matched_files:
            for row in matched_files:
                repo_id = row.get("repository_id")
                if repo_id:
                    chosen_repo_id = str(repo_id)
                    break

        if chosen_repo_id and chosen_repo_id in repo_by_id:
            repo_ref = repo_by_id[chosen_repo_id]
        elif repo_rows:
            for row in repo_rows:
                if valid_repo_row(row):
                    repo_ref = row
                    break

        full_name = str(repo_ref.get("full_name") or "").strip() if isinstance(repo_ref, dict) else ""
        default_branch = str(repo_ref.get("default_branch") or "main").strip() or "main" if isinstance(repo_ref, dict) else "main"
        repo_url = f"https://github.com/{full_name}" if full_name else None
        module_url = None
        if repo_url:
            if module_path:
                module_url = f"{repo_url}/tree/{default_branch}/{module_path.lstrip('/')}"
            else:
                module_url = repo_url

        repo_info: Optional[Dict[str, Any]] = None
        if repo_ref and valid_repo_row(repo_ref) and full_name:
            repo_info = {
                "id": repo_ref.get("id"),
                "full_name": full_name,
                "company_id": repo_ref.get("company_id") or company_id,
                "default_branch": default_branch,
                "github_url": module_url,
                "repository_url": repo_url,
            }

        resource_files: List[Dict[str, Any]] = []
        for row in matched_files[:3]:
            fp = str(row.get("file_path") or "").strip()
            if not fp:
                continue
            file_name = str(row.get("file_name") or fp.rsplit("/", 1)[-1]).strip()
            file_url = None
            if repo_url:
                file_url = f"{repo_url}/blob/{default_branch}/{fp.lstrip('/')}"
            resource_files.append({
                "path": fp,
                "file_name": file_name,
                "module_path": str(row.get("module_path") or module_path or "").strip(),
                "repository_id": row.get("repository_id"),
                "github_url": file_url,
            })

        if not resource_files and module_path and repo_info is not None:
            resource_files.append({
                "path": module_path,
                "file_name": module_path.rsplit("/", 1)[-1] or module_path,
                "module_path": module_path,
                "repository_id": repo_ref.get("id") if isinstance(repo_ref, dict) else None,
                "github_url": module_url,
            })

        return {
            "repo": repo_info,
            "files": resource_files,
            "github_url": module_url,
        }

    def _build_steps(
        self,
        role: str,
        company_id: str,
        modules: List[Dict],
        key_files: List[Dict],
        owner_index: Dict[str, List[str]],
        safe_paths: set,
        risk_paths: set,
        architecture: List[Dict],
    ) -> List[Dict[str, Any]]:
        """
        Build steps for the given role and company.
        Path shape:
        1-2 safe entry
        3-5 role core
        6-7 high-risk / high-leverage

        Each step gets a stable id so the UI can deep-link to a step workspace.
        """

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

        def make_step(
            slot_name: str,
            path: str,
            mod: Dict,
            related: List[Dict],
            risk: str,
            owners: List[str],
            layer_hint: str,
            order: int,
        ) -> Dict[str, Any]:
            step_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"ramp-step:{company_id}:{role}:{path}:{order}",
                )
            )
            file_paths = [f.get("path") for f in related if f.get("path")]
            resolved = self._resolve_target_reference(company_id, path, related)
            if resolved.get("files"):
                target_files = resolved.get("files")
            elif resolved.get("repo"):
                target_files = [{"path": path, "github_url": resolved.get("github_url")}]
            else:
                target_files = []
            summary = self._module_summary(path, mod, related)
            understand = self._understand_text(role, path, mod, related, owners, layer_hint)
            do_text = self._do_text(role, path, mod, related, owners, risk)
            done_text = self._done_when_text(role, path, mod, related, owners)
            return {
                "id": step_id,
                "order": order,
                "title": self._step_title(slot_name, path, mod, role),
                "why": self._template_why(role, path, mod, risk, owners, layer_hint, related),
                "understand": understand,
                "do": do_text,
                "done_when": done_text,
                "risk_tier": risk,
                "owners": owners,
                "target": {
                    "type": "module",
                    "path": path,
                    "repo": resolved.get("repo"),
                    "files": target_files,
                },
                "summary": summary,
                "resources": [
                    {"type": "repository", **(resolved.get("repo") or {})},
                    *target_files,
                ],
                "checklist": [
                    {
                        "id": "orient",
                        "label": f"Open and skim `{path}`",
                        "done": False,
                    }
                ],
                "evidence": self._evidence_for(path, mod, related, owners, risk, layer_hint),
                "machine": {
                    "path": path,
                    "suggested_owners": list(owners),
                    "suggested_risk": risk,
                },
                "overrides": {
                    "title": False,
                    "why": False,
                    "owners": False,
                    "risk_tier": False,
                    "order": False,
                },
            }

        safe_mods, core_mods, risk_mods = [], [], []
        for mod in modules:
            path = (mod.get("path") or "").strip()
            if not path or path in ("", "."):
                continue
            if path.lower() in ("doc", "docs") or path.lower().startswith("doc/"):
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
                steps.append(
                    make_step(
                        slot_name,
                        path,
                        mod,
                        related,
                        risk,
                        owners,
                        layer_hint,
                        len(steps) + 1,
                    )
                )
                taken += 1

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
                    make_step(
                        "core",
                        path,
                        mod,
                        related,
                        risk,
                        owners,
                        "",
                        len(steps) + 1,
                    )
                )

        return steps

    def _step_title(self, slot: str, path: str, mod: Dict, role: str) -> str:
        name = mod.get("name") or path.split("/")[-1]
        if slot == "safe":
            return f"Orient in `{name}`"
        if slot == "high-risk":
            return f"Read carefully: `{name}`"
        return f"Learn `{name}` ({role})"

    def _understand_text(
        self,
        role: str,
        path: str,
        mod: Dict,
        related: List[Dict],
        owners: List[str],
        layer_hint: str,
    ) -> str:
        pieces = [f"Understand how {path} fits into this codebase for a {role} role."]
        desc = (mod.get("description") or "").strip()
        if desc and "Module containing" not in desc:
            pieces.append(f"KMS currently indexes it as: {desc}")
        elif path:
            pieces.append("KMS has a module path for this area, but not much descriptive text yet.")
        if related:
            files = [f.get("path") for f in related[:3] if f.get("path")]
            if files:
                pieces.append(f"Use the nearby files {', '.join(files)} to confirm the module boundary and responsibilities.")
        if layer_hint:
            pieces.append(f"The current architecture signal places it in the {layer_hint} layer.")
        if owners:
            pieces.append(f"Current owner signals point to {', '.join(owners)}.")
        else:
            pieces.append("There is no strong ownership signal for this path yet, so treat the evidence as a starting point rather than a confirmed ownership map.")
        return " ".join(pieces)

    def _module_summary(self, path: str, mod: Dict, related: List[Dict]) -> Dict[str, Optional[str]]:
        desc = (mod.get("description") or "").strip()
        if desc and "Module containing" not in desc:
            what = desc
        elif path:
            what = f"KMS has indexed module {path} in the repo, but the module description is sparse."
        else:
            what = None
        files = [f.get("path") for f in related[:3] if f.get("path")]
        where = path if path else (", ".join(files) if files else None)
        if files:
            how = f"Look at the nearby files {', '.join(files)} to confirm how this module connects to adjacent code."
        elif path:
            how = f"Trace the module boundary in {path} and the files that import or call it."
        else:
            how = "Inspect the relevant repository area and confirm the neighbor modules before making assumptions."
        return {"what": what, "how": how, "where": where}

    def _do_text(
        self,
        role: str,
        path: str,
        mod: Dict,
        related: List[Dict],
        owners: List[str],
        risk: str,
    ) -> str:
        files = [f.get("path") for f in related[:3] if f.get("path")]
        if path and path.startswith("app/"):
            if files:
                return (
                    f"Inspect {path} together with {', '.join(files)} to identify what this component renders or wires up, "
                    "then explain how that component connects to the surrounding UI flow."
                )
            return (
                f"Inspect {path} to identify what this component renders or wires up, then note the closest neighboring UI modules "
                "and the data they pass across."
            )

        if files:
            if any(token in (path or "").lower() for token in ("api", "handler", "repository", "service", "worker", "ingest")) or "backend" in role:
                return (
                    f"Inspect {path} and the nearby files {', '.join(files)} to identify the module's responsibility, trace the request/data path, "
                    "and explain how the module relates to its adjacent backend code."
                )
            return (
                f"Inspect {path} and the nearby files {', '.join(files)} to identify the module's responsibility, locate the relevant implementation, "
                "and explain how it connects to the surrounding repository flow."
            )

        if owners:
            return (
                f"Inspect {path} and verify the current owner signal ({', '.join(owners)}) by locating the implementation and explaining how this "
                "module connects to the code that uses it."
            )

        if risk == "high-risk":
            return (
                f"Inspect {path} and note the specific behaviors or files that make this a higher-risk area, then explain which neighboring modules "
                "depend on it before making any assumptions."
            )

        return (
            f"Inspect {path} and identify the implementation boundary in the repo, then explain what this module is responsible for and which "
            "neighboring area most directly depends on it."
        )

    def _done_when_text(
        self,
        role: str,
        path: str,
        mod: Dict,
        related: List[Dict],
        owners: List[str],
    ) -> str:
        files = [f.get("path") for f in related[:2] if f.get("path")]
        if "backend" in role or any(token in (path or "").lower() for token in ("api", "handler", "repository", "service", "worker", "ingest")):
            statement = (
                f"You can explain what {path} is responsible for, identify the request or data flow in the nearby repository code, "
                "and state which adjacent backend module it calls or depends on."
            )
        elif path and path.startswith("app/"):
            statement = (
                f"You can explain what {path} is responsible for, identify the relevant UI component path in the repository, "
                "and state how the component connects to the surrounding interface flow."
            )
        else:
            statement = (
                f"You can explain what {path} is responsible for, identify the relevant implementation in the repository, "
                "and state how it relates to the neighboring code."
            )

        if files:
            statement = statement + f" You have used {', '.join(files)} as the concrete evidence trail."
        elif path:
            statement = statement + f" You have used {path} as the concrete evidence trail."

        if owners:
            statement = statement + f" Current owner signals for this area are {', '.join(owners)}; if no confirmed owner is available, say so explicitly."
        else:
            statement = statement + " If the ownership signal is weak or absent, you say so explicitly instead of inferring a person or team."

        return statement

    def _template_why(
        self,
        role: str,
        path: str,
        mod: Dict,
        risk: str,
        owners: List[str],
        layer_hint: str,
        related: List[Dict],
    ) -> str:
        desc = (mod.get("description") or "").strip()
        bits = []
        if path:
            bits.append(f"KMS currently indexes `{path}` as part of this repo's codebase evidence.")
        if desc and "Module containing" not in desc:
            bits.append(f"The indexed module description says: {desc}.")
        if related:
            sample = ", ".join(f.get("path") for f in related[:2] if f.get("path"))
            if sample:
                bits.append(f"Related files such as {sample} are also present in the current indexing.")
        if owners:
            bits.append(f"Current ownership signals point to {', '.join(owners)}.")
        elif path:
            bits.append("There is not enough ownership evidence for this path to treat a person as confirmed.")
        if risk == "high-risk":
            bits.append(f"This is a higher-risk path for a {role}, so it is worth learning before changing anything here.")
        elif risk == "safe":
            bits.append(f"This is a lower-risk entry point for understanding the repo structure for a {role}.")
        elif layer_hint:
            bits.append(f"The repository currently signals it as part of the {layer_hint} layer.")
        if not bits:
            return (
                "This area is worth starting with because the repo has only sparse evidence for it right now; "
                "treat this as a low-confidence starting point until nearby files clarify the module."
            )
        if not (desc or related or owners):
            return (
                "This area is worth checking because KMS has indexed the module path, but the evidence is limited. "
                "The current signal is a low-confidence starting point rather than a strong architectural claim."
            )
        return " ".join(bits)

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

    def _evidence_for(
        self,
        path: str,
        mod: Dict,
        files: List[Dict],
        owners: List[str],
        risk: str,
        layer_hint: str,
    ) -> List[Dict[str, str]]:
        observed: List[Dict[str, str]] = []
        if path:
            observed.append(
                {
                    "kind": "observed",
                    "source": "module",
                    "label": "Indexed module",
                    "detail": f"KMS indexed the repository module at {path}.",
                    "module_path": path,
                }
            )
        desc = (mod.get("description") or "").strip()
        if desc and "Module containing" not in desc:
            observed.append(
                {
                    "kind": "observed",
                    "source": "module",
                    "label": "Module description",
                    "detail": f"Current module description: {desc}",
                    "module_path": path,
                }
            )
        for f in files[:3]:
            fp = (f.get("path") or "").strip()
            if fp:
                observed.append(
                    {
                        "kind": "observed",
                        "source": "file",
                        "label": "Related file",
                        "detail": f"Repository evidence includes {fp}.",
                        "file_path": fp,
                    }
                )
        if owners:
            observed.append(
                {
                    "kind": "observed",
                    "source": "owner",
                    "label": "Ownership signal",
                    "detail": f"Current codebase signals mention {', '.join(owners)}.",
                    "owners": ", ".join(owners),
                }
            )

        if path and (layer_hint or risk):
            explanation = ["The evidence suggests this module is relevant based on the repo structure."]
            if layer_hint:
                explanation.append(f"Architecture context places it in the {layer_hint} layer.")
            if risk == "high-risk":
                explanation.append("The path is marked higher-risk, which is why it is a useful early read.")
            elif risk == "safe":
                explanation.append("The path is lower-risk, which makes it a good learning entry point.")
            observed.append(
                {
                    "kind": "inference",
                    "source": "generated_explanation",
                    "label": "Why this step matters",
                    "detail": " ".join(explanation),
                    "verified": False,
                }
            )
        elif not observed:
            observed.append(
                {
                    "kind": "inference",
                    "source": "generated_explanation",
                    "label": "Limited evidence",
                    "detail": "KMS has very little evidence for this area; treat the recommendation as a low-confidence starting point.",
                    "verified": False,
                }
            )
        return observed

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
    
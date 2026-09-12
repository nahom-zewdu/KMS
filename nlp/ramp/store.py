"""Persistence boundary for Ramp plans and per-user progress."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from supabase import Client


STATUSES = {"not_started", "in_progress", "completed"}


class RampStore:
    """Persist and retrieve Ramp data without embedding product reasoning."""

    def __init__(self, supabase: Client):
        self.supabase = supabase

    def save_plan(self, plan: Dict[str, Any]) -> None:
        """Upsert one active company/role plan."""
        record = {
            "company_id": plan["company_id"],
            "role": plan["role"],
            "employee_name": plan.get("employee_name"),
            "steps": plan.get("steps") or [],
            "meta": plan.get("meta") or {},
            "is_active": bool(plan.get("is_active", True)),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.supabase.table("ramp_plans").upsert(record, on_conflict="company_id,role").execute()

    def get_active(self, company_id: str, role: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the active plan and optionally hydrate user progress."""
        response = (
            self.supabase.table("ramp_plans")
            .select("*")
            .eq("company_id", company_id)
            .eq("role", role.strip().lower().replace(" ", "-"))
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        if not rows:
            return None
        row = rows[0]
        plan = dict(row)
        if user_id:
            progress = self.progress_for_plan(str(row["id"]), company_id, user_id)
            plan["progress"] = progress
            for step in plan.get("steps") or []:
                item = progress.get(str(step.get("id")))
                step["progress"] = item
                step["status"] = item.get("status", "not_started") if item else "not_started"
        return plan

    def get_plan(self, plan_id: str, company_id: str) -> Optional[Dict[str, Any]]:
        """Return a plan only when it belongs to the requested company."""
        response = (
            self.supabase.table("ramp_plans")
            .select("*")
            .eq("id", plan_id)
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        return dict(rows[0]) if rows else None

    def progress_for_plan(self, plan_id: str, company_id: str, user_id: str) -> Dict[str, Dict[str, Any]]:
        """Return one user's progress keyed by stable step ID."""
        response = (
            self.supabase.table("ramp_step_progress")
            .select("*")
            .eq("plan_id", plan_id)
            .eq("company_id", company_id)
            .eq("user_id", user_id)
            .execute()
        )
        result: Dict[str, Dict[str, Any]] = {}
        for row in getattr(response, "data", []) or []:
            if row.get("step_id"):
                result[str(row["step_id"])] = dict(row)
        return result

    def update_progress(self, plan_id: str, step_id: str, company_id: str, user_id: str, status: str) -> Dict[str, Any]:
        """Set one user's status after validating plan and step ownership."""
        status = (status or "").strip().lower()
        if status not in STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")
        if not user_id:
            raise ValueError("user_id is required")
        plan = self.get_plan(plan_id, company_id)
        if not plan:
            raise ValueError("ramp plan not found")
        if not any(str(step.get("id")) == str(step_id) for step in plan.get("steps") or []):
            raise KeyError(f"step_id {step_id} not found in plan {plan_id}")

        existing = self.progress_for_plan(plan_id, company_id, user_id).get(str(step_id))
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": existing.get("id") if existing else str(uuid.uuid4()),
            "plan_id": plan_id,
            "company_id": company_id,
            "step_id": step_id,
            "user_id": user_id,
            "status": status,
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        self.supabase.table("ramp_step_progress").upsert(record, on_conflict="plan_id,step_id,user_id").execute()
        return record

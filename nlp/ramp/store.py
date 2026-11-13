"""Persistence boundary for Ramp plans and per-user progress."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from supabase import Client


STATUSES = {"not_started", "in_progress", "completed"}
FEEDBACK_RATINGS = {"useful", "partially_useful", "not_useful"}


class RampPlanPersistenceError(RuntimeError):
    """A Ramp plan could not be persisted; database details are intentionally omitted."""

    def __init__(self, error_type: str):
        self.error_type = error_type
        super().__init__("Ramp plan persistence failed")


class RampStore:
    """Persist and retrieve Ramp data without embedding product reasoning."""

    def __init__(self, supabase: Client):
        self.supabase = supabase

    def save_plan(self, plan: Dict[str, Any]) -> None:
        """Atomically upsert one complete active company/role plan."""
        self._validate_plan(plan)
        self._require_company_id(plan.get("company_id"))
        record = {
            "company_id": plan["company_id"],
            "role": plan["role"],
            "employee_name": plan.get("employee_name"),
            "steps": plan.get("steps") or [],
            "meta": plan.get("meta") or {},
            "is_active": bool(plan.get("is_active", True)),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.supabase.table("ramp_plans").upsert(
                record, on_conflict="company_id,role"
            ).execute()
        except Exception as exc:
            raise RampPlanPersistenceError(type(exc).__name__) from None

    @classmethod
    def _validate_plan(cls, plan: Dict[str, Any]) -> None:
        """Reject incomplete plans before the single-row upsert can replace an active plan."""
        if not isinstance(plan, dict) or not str(plan.get("role") or "").strip():
            raise ValueError("A Ramp plan role is required")
        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("An active Ramp plan must contain at least one step")
        required_fields = ("id", "title", "do", "done_when")
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict) or any(not step.get(field) for field in required_fields):
                raise ValueError(f"Ramp plan step {index} is incomplete")
            if not isinstance(step.get("evidence"), list) or not step["evidence"]:
                raise ValueError(f"Ramp plan step {index} has no evidence")
            machine = step.get("machine")
            if not isinstance(machine, dict) or machine.get("eligible") is not True:
                raise ValueError(f"Ramp plan step {index} is not eligible")

    def get_active(self, company_id: str, role: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the active plan in the shape expected by the Ramp API."""
        self._require_company_id(company_id)
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
        plan = {
            "id": row.get("id"),
            "company_id": row.get("company_id"),
            "role": row.get("role"),
            "employee_name": row.get("employee_name"),
            "title": row.get("title") or f"Ramp — {row.get('role')}",
            "steps": row.get("steps") or [],
            "meta": row.get("meta") or {},
            "is_active": row.get("is_active", True),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
        if user_id:
            progress = self.progress_for_plan(str(row["id"]), company_id, user_id)
            plan["progress"] = progress
            for step in plan["steps"]:
                item = progress.get(str(step.get("id")))
                step["progress"] = item
                step["status"] = item.get("status", "not_started") if item else "not_started"
        return plan

    def get_plan(self, plan_id: str, company_id: str) -> Optional[Dict[str, Any]]:
        """Return a plan only when it belongs to the requested company."""
        self._require_company_id(company_id)
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
        self._require_company_id(company_id)
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
        self._require_company_id(company_id)
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

    def submit_step_feedback(
        self,
        plan_id: str,
        step_id: str,
        company_id: str,
        user_id: str,
        rating: str,
        reason: str | None = None,
    ) -> Dict[str, Any]:
        """Create or replace one member's feedback for a validated Ramp step."""
        normalized_rating = (rating or "").strip().lower()
        if normalized_rating not in FEEDBACK_RATINGS:
            raise ValueError(f"rating must be one of: {', '.join(sorted(FEEDBACK_RATINGS))}")
        if not user_id:
            raise ValueError("user_id is required")
        self._require_company_id(company_id)
        plan = self.get_plan(plan_id, company_id)
        if not plan:
            raise ValueError("ramp plan not found")
        if not any(str(step.get("id")) == str(step_id) for step in plan.get("steps") or []):
            raise KeyError(f"step_id {step_id} not found in plan {plan_id}")

        if reason is not None and not isinstance(reason, str):
            raise ValueError("reason must be text")
        normalized_reason = (reason or "").strip() or None
        if normalized_reason and len(normalized_reason) > 1000:
            raise ValueError("reason must be 1000 characters or fewer")
        existing = (
            self.supabase.table("ramp_step_feedback")
            .select("id, created_at")
            .eq("plan_id", plan_id)
            .eq("step_id", step_id)
            .eq("company_id", company_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(existing, "data", []) or []
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": rows[0].get("id") if rows else str(uuid.uuid4()),
            "plan_id": plan_id,
            "company_id": company_id,
            "step_id": step_id,
            "user_id": user_id,
            "rating": normalized_rating,
            "reason": normalized_reason,
            "created_at": (rows[0].get("created_at") if rows else None) or now,
            "updated_at": now,
        }
        self.supabase.table("ramp_step_feedback").upsert(
            record, on_conflict="plan_id,step_id,user_id"
        ).execute()
        return {
            "plan_id": plan_id,
            "step_id": step_id,
            "rating": normalized_rating,
            "reason": normalized_reason,
            "updated_at": now,
        }

    def get_step_feedback(
        self, plan_id: str, step_id: str, company_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return only the requesting engineer's feedback for a validated step."""
        self._require_company_id(company_id)
        plan = self.get_plan(plan_id, company_id)
        if not plan:
            raise ValueError("ramp plan not found")
        if not any(str(step.get("id")) == str(step_id) for step in plan.get("steps") or []):
            raise KeyError(f"step_id {step_id} not found in plan {plan_id}")
        response = (
            self.supabase.table("ramp_step_feedback")
            .select("plan_id, step_id, rating, reason, updated_at")
            .eq("plan_id", plan_id)
            .eq("step_id", step_id)
            .eq("company_id", company_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        return dict(rows[0]) if rows else None

    def feedback_summary(self, plan_id: str, company_id: str) -> Dict[str, Any]:
        """Return tenant-scoped aggregate ratings without exposing individual identities."""
        self._require_company_id(company_id)
        plan = self.get_plan(plan_id, company_id)
        if not plan:
            raise ValueError("ramp plan not found")
        response = (
            self.supabase.table("ramp_step_feedback")
            .select("step_id, rating")
            .eq("plan_id", plan_id)
            .eq("company_id", company_id)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        counts = {rating: 0 for rating in sorted(FEEDBACK_RATINGS)}
        by_step: Dict[str, Dict[str, int]] = {}
        for row in rows:
            rating = row.get("rating")
            if rating not in FEEDBACK_RATINGS:
                continue
            counts[rating] += 1
            step_counts = by_step.setdefault(
                str(row.get("step_id")), {key: 0 for key in sorted(FEEDBACK_RATINGS)}
            )
            step_counts[rating] += 1
        return {
            "plan_id": plan_id,
            "total": sum(counts.values()),
            "ratings": counts,
            "steps": by_step,
        }

    @staticmethod
    def _require_company_id(company_id: str | None) -> None:
        if not company_id or company_id.strip().lower() == "default":
            raise ValueError("A real company_id is required for Ramp persistence")

"""
KMS Onboard API HTTP endpoints for playbook generation.
"""
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from codebase.baseline import CodebaseBaselineSync
from playbooks.generator import PlaybookGenerator
from visualizer.service import VisualizerService
from ramp.generator_v2 import RampPlanner
from utils.supabase import init_supabase
import logging
import uvicorn

app = FastAPI(title="KMS Onboard API")
supabase = init_supabase()
ramp_generator = RampPlanner(supabase)
generator = PlaybookGenerator(supabase)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/ramp-plans/generate")
async def generate_ramp(payload: dict):
    """Generate or refresh Ramp for a company and role."""
    try:
        plan = ramp_generator.generate(
            role=payload.get("role") or "software-engineer",
            company_id=payload.get("company_id") or "default",
            employee_name=payload.get("employee_name"),
            polish_why=bool(payload.get("polish_why", True)),
        )
        return JSONResponse({"success": True, "plan": plan})
    except Exception as exc:
        logging.exception("Ramp generation failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/ramp-plans")
async def get_ramp(
    company_id: str = "default",
    role: str = "software-engineer",
    user_id: str | None = Header(default=None, alias="X-User-Id"),
    company_header: str | None = Header(default=None, alias="X-Company-Id"),
):
    """Fetch active Ramp and hydrate caller progress when requested."""
    effective_company_id = company_header or company_id or "default"
    try:
        plan = ramp_generator.get_active(effective_company_id, role, user_id)
        if not plan:
            return JSONResponse({"success": False, "error": "No active ramp plan", "plan": None}, status_code=404)
        return JSONResponse({"success": True, "plan": plan})
    except Exception as exc:
        logging.exception("Ramp fetch failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.patch("/ramp-plans/{plan_id}/steps/{step_id}/progress")
async def update_step_progress(
    plan_id: str,
    step_id: str,
    payload: dict,
    company_id: str = Header(default="default", alias="X-Company-Id"),
    user_id: str = Header(..., alias="X-User-Id"),
):
    """Update one user's Ramp step progress."""
    if not user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header is required")
    status = str((payload or {}).get("status") or "").strip().lower()
    if not status:
        raise HTTPException(status_code=400, detail="status is required")
    try:
        progress = ramp_generator.update_step_progress(plan_id, step_id, company_id, user_id, status)
        return JSONResponse({"success": True, "progress": progress})
    except ValueError as exc:
        code = 400 if "status" in str(exc).lower() else 404
        return JSONResponse({"success": False, "error": str(exc)}, status_code=code)
    except KeyError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=404)
    except Exception as exc:
        logging.exception("Ramp step progress update failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/ramp-plans/{plan_id}/steps/{step_id}/progress")
async def get_step_progress(
    plan_id: str,
    step_id: str,
    company_id: str = Header(default="default", alias="X-Company-Id"),
    user_id: str = Header(..., alias="X-User-Id"),
):
    """Read one user's Ramp step progress."""
    progress = ramp_generator.get_step_progress(plan_id, step_id, company_id, user_id)
    if not progress:
        return JSONResponse({"success": False, "error": "Step progress not found", "progress": None}, status_code=404)
    return JSONResponse({"success": True, "progress": progress})


@app.post("/playbooks/generate")
async def generate_playbook(payload: dict):
    """Generate a role-specific onboarding playbook."""
    try:
        role = payload.get("role", "software-engineer")
        employee_name = payload.get("employee_name", "New Engineer")
        company_id = payload.get("company_id", "default")
        playbook = generator.generate(role=role, employee_name=payload.get("employee_name", "New Engineer"), company_id=company_id)
        return JSONResponse({"success": True, "role": role, "playbook": playbook, "message": f"Playbook for {role} generated successfully."})
    except Exception as exc:
        logging.exception("Playbook generation failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/github/sync-baseline")
async def sync_baseline(repo: str, company_id: str = "default"):
    """Sync the baseline for a specific repository."""
    try:
        success = CodebaseBaselineSync(supabase).sync_repository(repo, company_id=company_id)
        if success:
            return JSONResponse({"success": True, "message": f"Baseline synced for {repo}"})
        return JSONResponse({"success": False, "error": f"Failed to sync baseline for {repo}"}, status_code=500)
    except Exception as exc:
        logging.exception("Baseline sync failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/visualizer")
async def get_visualizer(role: str = "backend-engineer", company_id: str = "default"):
    """Get visualizer data for a specific role."""
    try:
        data = VisualizerService(supabase).build_for_role(role, company_id=company_id)
        return JSONResponse({"success": True, "data": data})
    except Exception as exc:
        logging.exception("Visualizer failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

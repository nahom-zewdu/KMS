# nlp/api.py
"""
KMS Onboard API HTTP endpoints for playbook generation.
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from codebase.baseline import CodebaseBaselineSync
from playbooks.generator import PlaybookGenerator
from visualizer.service import VisualizerService
from ramp.generator import RampPlanGenerator
from utils.supabase import init_supabase
import logging
import uvicorn

app = FastAPI(title="KMS Onboard API")
supabase = init_supabase()
ramp_generator = RampPlanGenerator(supabase)
generator = PlaybookGenerator(supabase)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/ramp-plans/generate")
async def generate_ramp(payload: dict):
    """Generate or refresh First 7 Days ramp for a company + role."""
    try:
        role = payload.get("role") or "software-engineer"
        company_id = payload.get("company_id") or "default"
        employee_name = payload.get("employee_name")
        polish = payload.get("polish_why", True)
        plan = ramp_generator.generate(
            role=role,
            company_id=company_id,
            employee_name=employee_name,
            polish_why=bool(polish),
        )
        return JSONResponse({"success": True, "plan": plan})
    except Exception as e:
        logging.error("Ramp generation failed: %s", e)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/playbooks/generate")
async def generate_playbook(payload: dict):
    """Generate a role-specific onboarding playbook."""
    try:
        role = payload.get("role", "software-engineer")
        employee_name = payload.get("employee_name", "New Engineer")
        company_id = payload.get("company_id", "default")

        playbook = generator.generate(role=role, employee_name=employee_name, company_id=company_id)
        logging.info(f"Role: {role}, Playbook generated: {playbook}")
        
        return JSONResponse({
            "success": True,
            "role": role,
            "playbook": playbook,
            "message": f"Playbook for {role} generated successfully."
        })
    except Exception as e:
        logging.error(f"Playbook generation failed: {e}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)
    

@app.get("/github/sync-baseline")
async def sync_baseline(repo: str, company_id: str = "default"):
    """Sync the baseline for a specific repository."""
    try:
        syncer = CodebaseBaselineSync(supabase)
        success = syncer.sync_repository(repo, company_id=company_id)
        if success:
            return JSONResponse({"success": True, "message": f"Baseline synced for {repo}"})
        else:
            return JSONResponse({"success": False, "error": f"Failed to sync baseline for {repo}"}, status_code=500)
    except Exception as e:
        logging.error(f"Baseline sync failed: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.get("/visualizer")
async def get_visualizer(role: str = "backend-engineer", company_id: str = "default"):
    """Get visualizer data for a specific role."""
    try:
        data = VisualizerService(supabase).build_for_role(role, company_id=company_id)
        return JSONResponse({"success": True, "data": data})
    except Exception as e:
        logging.error(f"Visualizer failed: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

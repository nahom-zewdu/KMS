# nlp/api.py
"""
KMS Onboard API HTTP endpoints for playbook generation.
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from playbooks.generator import PlaybookGenerator
from visualizer.service import VisualizerService
from utils.supabase import init_supabase
import logging
import uvicorn

app = FastAPI(title="KMS Onboard API")
supabase = init_supabase()
generator = PlaybookGenerator(supabase)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/playbooks/generate")
async def generate_playbook(payload: dict):
    """Generate a role-specific onboarding playbook."""
    try:
        role = payload.get("role", "software-engineer")
        employee_name = payload.get("employee_name")

        playbook = await generator.generate(role=role, employee_name=employee_name)
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

@app.get("/visualizer")
async def get_visualizer(role: str = "backend-engineer"):
    """Get visualizer data for a specific role."""
    try:
        data = VisualizerService(supabase).build_for_role(role)
        return JSONResponse({"success": True, "data": data})
    except Exception as e:
        logging.error(f"Visualizer failed: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

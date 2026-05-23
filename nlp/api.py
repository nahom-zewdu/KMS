# nlp/api.py
"""
KMS Onboard API HTTP endpoints for playbook generation.
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from playbooks.generator import PlaybookGenerator
from utils.supabase import init_supabase
import logging
import uvicorn

app = FastAPI(title="KMS Onboard API")
supabase = init_supabase()
generator = PlaybookGenerator(supabase)

@app.post("/playbooks/generate")
async def generate_playbook(payload: dict):
    try:
        role = payload.get("role", "backend-engineer")
        employee_name = payload.get("employee_name")

        playbook = await generator.generate(role=role, employee_name=employee_name)
        
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
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
supabase = None


def get_supabase_client():
    """Lazily initialize Supabase so authz helpers can be unit tested without env configuration."""
    global supabase
    if supabase is None:
        supabase = init_supabase()
    return supabase


def verify_bearer_token(token: str | None, *, secret_env: str) -> dict[str, Any]:
    """Verify a bearer token using the configured secret and return the verified claims."""
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is required")

    secret = os.getenv(secret_env)
    if not secret:
        raise HTTPException(status_code=503, detail=f"{secret_env} is not configured")

    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["sub"]})
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired bearer token") from exc

    user_id = claims.get("sub") or claims.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Bearer token does not include a user identity")

    return {"user_id": str(user_id), "claims": claims}


def require_authenticated_identity(
    authorization: str | None = None,
    *,
    legacy_user_id: str | None = None,
) -> dict[str, Any]:
    """Require a verified JWT or internal service token; reject legacy X-User-Id carrier headers."""
    if legacy_user_id is not None:
        raise HTTPException(
            status_code=401,
            detail="X-User-Id is not accepted for authentication. Use Authorization: Bearer <jwt>",
        )

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Authorization header must use Bearer token format")

    for secret_env in ("SUPABASE_JWT_SECRET", "JWT_SECRET"):
        try:
            return verify_bearer_token(token, secret_env=secret_env)
        except HTTPException as exc:
            if exc.status_code == 503:
                continue
            last_error = exc
    service_secret = os.getenv("INTERNAL_SERVICE_SECRET")
    if service_secret:
        try:
            claims = jwt.decode(token, service_secret, algorithms=["HS256"], options={"require": ["sub"]})
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired bearer token") from exc
        service_user_id = claims.get("sub") or claims.get("user_id")
        if service_user_id and str(claims.get("role") or "").lower() in {"service", "internal", "system"}:
            return {"user_id": str(service_user_id), "claims": claims, "source": "internal_service"}

    raise HTTPException(status_code=401, detail="Invalid or expired bearer token")


def normalize_company_id(company_id: str | None) -> str:
    """Reject blank or shared fallback company identifiers."""
    normalized = (company_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="company_id is required")
    if normalized.lower() == "default":
        raise HTTPException(status_code=400, detail="company_id cannot be the shared default tenant")
    return normalized


def require_company_membership(user_id: str | None, company_id: str | None, *, require_role: str | None = None) -> dict:
    """Validate that a user belongs to the requested company and optionally has a required role."""
    if not user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header is required")

    effective_company_id = normalize_company_id(company_id)
    membership = {
        "company_id": effective_company_id,
        "user_id": user_id,
        "role": "member",
    }

    try:
        client = get_supabase_client()
        response = (
            client.table("company_members")
            .select("company_id, user_id, role")
            .eq("user_id", user_id)
            .eq("company_id", effective_company_id)
            .execute()
        )
        rows = getattr(response, "data", []) or []
        if not rows:
            raise HTTPException(status_code=403, detail="User is not a member of this company")
        membership = rows[0]
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive boundary for invalid DB client state
        logging.exception("Company membership lookup failed")
        raise HTTPException(status_code=500, detail="Failed to validate company membership") from exc

    if require_role:
        role = str((membership.get("role") or "")).lower()
        allowed_roles = {"admin", "manager"} if require_role == "admin" else {require_role.lower()}
        if role not in allowed_roles and role != "admin":
            raise HTTPException(status_code=403, detail=f"User does not have {require_role} access to this company")

    return membership


ramp_generator = RampPlanner(get_supabase_client())
generator = PlaybookGenerator(get_supabase_client())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_company_id(company_id: str | None, field_name: str = "company_id") -> str:
    """Reject shared default tenant values and empty company IDs."""
    normalized = (company_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    if normalized.lower() == "default":
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be the shared default tenant")
    return normalized


@app.post("/ramp-plans/generate")
async def generate_ramp(
    payload: dict,
    user_id: str | None = Header(default=None, alias="X-User-Id"),
    company_id_header: str | None = Header(default=None, alias="X-Company-Id"),
):
    """Generate or refresh Ramp for a company and role."""
    try:
        company_id = require_company_id(company_id_header or payload.get("company_id"), "company_id")
        require_company_membership(user_id, company_id)
        plan = ramp_generator.generate(
            role=payload.get("role") or "software-engineer",
            company_id=company_id,
            employee_name=payload.get("employee_name"),
            polish_why=bool(payload.get("polish_why", True)),
        )
        return JSONResponse({"success": True, "plan": plan})
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Ramp generation failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/ramp-plans")
async def get_ramp(
    company_id: str | None = None,
    role: str = "software-engineer",
    user_id: str | None = Header(default=None, alias="X-User-Id"),
    company_header: str | None = Header(default=None, alias="X-Company-Id"),
):
    """Fetch active Ramp and hydrate caller progress when requested."""
    effective_company_id = require_company_id(company_header or company_id, "company_id")
    try:
        require_company_membership(user_id, effective_company_id)
        plan = ramp_generator.get_active(effective_company_id, role, user_id)
        if not plan:
            return JSONResponse({"success": False, "error": "No active ramp plan", "plan": None}, status_code=404)
        return JSONResponse({"success": True, "plan": plan})
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Ramp fetch failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.patch("/ramp-plans/{plan_id}/steps/{step_id}/progress")
async def update_step_progress(
    plan_id: str,
    step_id: str,
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    legacy_user_id: str | None = Header(default=None, alias="X-User-Id"),
    company_id: str | None = Header(default=None, alias="X-Company-Id"),
):
    """Update one user's Ramp step progress."""
    effective_company_id = require_company_id(company_id, "X-Company-Id")
    try:
        identity = require_authenticated_identity(authorization, legacy_user_id=legacy_user_id)
        require_company_membership(identity["user_id"], effective_company_id)
        status = str((payload or {}).get("status") or "").strip().lower()
        if not status:
            raise HTTPException(status_code=400, detail="status is required")
        progress = ramp_generator.update_step_progress(plan_id, step_id, effective_company_id, identity["user_id"], status)
        return JSONResponse({"success": True, "progress": progress})
    except ValueError as exc:
        code = 400 if "status" in str(exc).lower() else 404
        return JSONResponse({"success": False, "error": str(exc)}, status_code=code)
    except KeyError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=404)
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Ramp step progress update failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/ramp-plans/{plan_id}/steps/{step_id}/progress")
async def get_step_progress(
    plan_id: str,
    step_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    legacy_user_id: str | None = Header(default=None, alias="X-User-Id"),
    company_id: str | None = Header(default=None, alias="X-Company-Id"),
):
    """Read one user's Ramp step progress."""
    effective_company_id = require_company_id(company_id, "X-Company-Id")
    try:
        identity = require_authenticated_identity(authorization, legacy_user_id=legacy_user_id)
        require_company_membership(identity["user_id"], effective_company_id)
        progress = ramp_generator.get_step_progress(plan_id, step_id, effective_company_id, identity["user_id"])
        if not progress:
            return JSONResponse({"success": False, "error": "Step progress not found", "progress": None}, status_code=404)
        return JSONResponse({"success": True, "progress": progress})
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Ramp step progress read failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.post("/playbooks/generate")
async def generate_playbook(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    legacy_user_id: str | None = Header(default=None, alias="X-User-Id"),
    company_id_header: str | None = Header(default=None, alias="X-Company-Id"),
):
    """Generate a role-specific onboarding playbook."""
    try:
        identity = require_authenticated_identity(authorization, legacy_user_id=legacy_user_id)
        role = payload.get("role", "software-engineer")
        employee_name = payload.get("employee_name", "New Engineer")
        company_id = require_company_id(company_id_header or payload.get("company_id"), "company_id")
        require_company_membership(identity["user_id"], company_id)
        playbook = generator.generate(role=role, employee_name=employee_name, company_id=company_id)
        return JSONResponse({"success": True, "role": role, "playbook": playbook, "message": f"Playbook for {role} generated successfully."})
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Playbook generation failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/github/sync-baseline")
async def sync_baseline(
    repo: str,
    company_id: str | None = None,
    authorization: str | None = Header(default=None, alias="Authorization"),
    legacy_user_id: str | None = Header(default=None, alias="X-User-Id"),
    company_header: str | None = Header(default=None, alias="X-Company-Id"),
):
    """Sync the baseline for a specific repository."""
    try:
        identity = require_authenticated_identity(authorization, legacy_user_id=legacy_user_id)
        effective_company_id = require_company_id(company_header or company_id, "company_id")
        require_company_membership(identity["user_id"], effective_company_id)
        success = CodebaseBaselineSync(get_supabase_client()).sync_repository(repo, company_id=effective_company_id)
        if success:
            return JSONResponse({"success": True, "message": f"Baseline synced for {repo}"})
        return JSONResponse({"success": False, "error": f"Failed to sync baseline for {repo}"}, status_code=500)
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Baseline sync failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/visualizer")
async def get_visualizer(
    role: str = "backend-engineer",
    company_id: str | None = None,
    authorization: str | None = Header(default=None, alias="Authorization"),
    legacy_user_id: str | None = Header(default=None, alias="X-User-Id"),
    company_header: str | None = Header(default=None, alias="X-Company-Id"),
):
    """Get visualizer data for a specific role."""
    try:
        identity = require_authenticated_identity(authorization, legacy_user_id=legacy_user_id)
        effective_company_id = require_company_id(company_header or company_id, "company_id")
        require_company_membership(identity["user_id"], effective_company_id)
        data = VisualizerService(get_supabase_client()).build_for_role(role, company_id=effective_company_id)
        return JSONResponse({"success": True, "data": data})
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Visualizer failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

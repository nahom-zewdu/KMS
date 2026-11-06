"""
KMS Onboard API HTTP endpoints for playbook generation.
"""
import logging
import os
from typing import Any

import jwt
import uvicorn
from functools import lru_cache
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from codebase.baseline import CodebaseBaselineSync
from playbooks.generator import PlaybookGenerator
from ramp.generator_v2 import RampPlanner
from utils.supabase import init_supabase
from visualizer.service import VisualizerService

app = FastAPI(title="KMS Onboard API")
supabase = None


def get_supabase_client():
    """Lazily initialize Supabase so authz helpers can be unit tested without env configuration."""
    global supabase
    if supabase is None:
        supabase = init_supabase()
    return supabase

@lru_cache(maxsize=8)
def get_supabase_jwks_client(jwks_url: str) -> PyJWKClient:
    """Create a cached JWKS client for Supabase signing keys."""
    return PyJWKClient(
        jwks_url,
        cache_jwk_set=True,
        lifespan=300,
    )


def verify_bearer_token(token: str | None) -> dict[str, Any]:
    """Verify a Supabase ES256 user token using the project's public JWKS."""
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is required")

    supabase_url = os.getenv("SUPABASE_URL")
    if not supabase_url:
        raise HTTPException(status_code=503, detail="SUPABASE_URL is not configured")

    issuer = os.getenv("SUPABASE_JWT_ISSUER")
    if not issuer:
        issuer = f"{supabase_url.rstrip('/')}/auth/v1"

    audience = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")

    jwks_url = os.getenv("SUPABASE_JWKS_URL")
    if not jwks_url:
        jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    try:
        signing_key = get_supabase_jwks_client(
            jwks_url
        ).get_signing_key_from_jwt(token)

        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            issuer=issuer,
            audience=audience,
            options={
                "require": ["exp", "iat", "iss", "aud", "sub", "role"],
            },
        )

    except PyJWKClientConnectionError as exc:
        logging.exception("Could not retrieve Supabase signing keys")
        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve Supabase signing keys",
        ) from exc

    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired bearer token",
        ) from exc

    if str(claims.get("role", "")).lower() != "authenticated":
        raise HTTPException(
            status_code=401,
            detail="Bearer token is not a user token",
        )

    return {
        "user_id": str(claims["sub"]),
        "claims": claims,
        "source": "supabase_user",
    }

def verify_internal_service_token(token: str | None) -> dict[str, Any]:
    """Validate a service token independently; this identity is not accepted by user routes."""
    if not token:
        raise HTTPException(status_code=401, detail="Service bearer token is required")

    secret = os.getenv("INTERNAL_SERVICE_SECRET")
    issuer = os.getenv("INTERNAL_SERVICE_ISSUER")
    audience = os.getenv("INTERNAL_SERVICE_AUDIENCE")
    if not secret or not issuer or not audience:
        raise HTTPException(status_code=503, detail="Internal service token configuration is incomplete")
    if len(secret.encode("utf-8")) < 32:
        raise HTTPException(status_code=503, detail="INTERNAL_SERVICE_SECRET must be at least 32 bytes")

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "role"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired service token") from exc

    if str(claims.get("role", "")).lower() != "service":
        raise HTTPException(status_code=401, detail="Token is not an internal service token")
    return {"service_id": str(claims["sub"]), "claims": claims, "source": "internal_service"}


def require_company_scoped_service_identity(
    authorization: str | None,
    company_id: str,
) -> dict[str, Any]:
    """Require an internal token cryptographically bound to the requested company."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Authorization header must use Bearer format")

    identity = verify_internal_service_token(token)
    token_company = str(identity["claims"].get("company_id") or "").strip()
    if not token_company or token_company.lower() == "default":
        raise HTTPException(status_code=401, detail="Service token is not scoped to a company")
    if token_company != company_id:
        raise HTTPException(status_code=403, detail="Service token does not authorize this company")
    return identity


def require_authenticated_identity(
    authorization: str | None = None,
    *,
    legacy_user_id: str | None = None,
) -> dict[str, Any]:
    """Require a verified Supabase user JWT; service identities cannot impersonate users."""
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

    return verify_bearer_token(token, secret_env="SUPABASE_JWT_SECRET")


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
        raise HTTPException(status_code=401, detail="Verified user identity is required")

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
    authorization: str | None = Header(default=None, alias="Authorization"),
    legacy_user_id: str | None = Header(default=None, alias="X-User-Id"),
    company_id_header: str | None = Header(default=None, alias="X-Company-Id"),
):
    """Generate or refresh Ramp for a company and role."""
    try:
        identity = require_authenticated_identity(authorization, legacy_user_id=legacy_user_id)
        company_id = require_company_id(company_id_header or payload.get("company_id"), "company_id")
        require_company_membership(identity["user_id"], company_id)
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
    authorization: str | None = Header(default=None, alias="Authorization"),
    legacy_user_id: str | None = Header(default=None, alias="X-User-Id"),
    company_header: str | None = Header(default=None, alias="X-Company-Id"),
):
    """Fetch active Ramp and hydrate caller progress when requested."""
    effective_company_id = require_company_id(company_header or company_id, "company_id")
    try:
        identity = require_authenticated_identity(authorization, legacy_user_id=legacy_user_id)
        require_company_membership(identity["user_id"], effective_company_id)
        plan = ramp_generator.get_active(effective_company_id, role, identity["user_id"])
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


@app.post("/internal/playbooks/generate")
async def generate_internal_playbook(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    """Generate a Slack playbook for the tenant bound into an internal service token."""
    try:
        company_id = require_company_id(payload.get("company_id"), "company_id")
        require_company_scoped_service_identity(authorization, company_id)
        role = payload.get("role", "software-engineer")
        employee_name = payload.get("employee_name", "")
        playbook = generator.generate(role=role, employee_name=employee_name, company_id=company_id)
        return JSONResponse({"success": True, "role": role, "playbook": playbook})
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Internal Slack playbook generation failed")
        raise HTTPException(status_code=500, detail="Failed to generate playbook") from exc


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

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api

USER_SECRET = "user-token-test-secret-at-least-32-bytes"
SERVICE_SECRET = "service-token-test-secret-at-least-32-bytes"
USER_ISSUER = "https://kms-test.supabase.co/auth/v1"
USER_AUDIENCE = "authenticated"


def make_token(
    secret=USER_SECRET,
    *,
    issuer=USER_ISSUER,
    audience=USER_AUDIENCE,
    role="authenticated",
    expires_at=None,
    include_exp=True,
    include_iat=True,
    include_audience=True,
    algorithm="HS256",
):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "user-123",
        "iss": issuer,
        "role": role,
    }
    if include_iat:
        claims["iat"] = int(now.timestamp())
    if include_audience:
        claims["aud"] = audience
    if include_exp:
        claims["exp"] = int((expires_at or now + timedelta(minutes=5)).timestamp())
    return jwt.encode(claims, secret, algorithm=algorithm)


class FakeResponse:
    def __init__(self, rows):
        self.data = rows


class FakeTable:
    def __init__(self, rows):
        self.rows = list(rows)
        self.filters = {}

    def select(self, *args, **kwargs):
        return self

    def eq(self, field, value):
        self.filters[field] = value
        return self

    def execute(self):
        rows = list(self.rows)
        for field, value in self.filters.items():
            rows = [row for row in rows if row.get(field) == value]
        return FakeResponse(rows)


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "company_members"
        return FakeTable(self.rows)


def test_require_authenticated_identity_accepts_verified_token(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", USER_SECRET)
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", USER_ISSUER)
    token = make_token()
    identity = api.require_authenticated_identity(f"Bearer {token}")
    assert identity["user_id"] == "user-123"
    assert identity["source"] == "supabase_user"


def test_require_authenticated_identity_rejects_forged_user_header(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        api.require_authenticated_identity(None, legacy_user_id="forged-user")
    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "token",
    [
        make_token(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)),
        make_token(include_exp=False),
        make_token(include_iat=False),
        make_token(include_audience=False),
        make_token(issuer="https://attacker.invalid/auth/v1"),
        make_token(audience="service_role"),
        make_token(role="service"),
    ],
)
def test_require_authenticated_identity_rejects_expired_or_wrong_scope_tokens(monkeypatch, token):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", USER_SECRET)
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", USER_ISSUER)
    with pytest.raises(HTTPException) as exc:
        api.require_authenticated_identity(f"Bearer {token}")
    assert exc.value.status_code == 401


def test_require_authenticated_identity_rejects_wrong_signing_algorithm(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", USER_SECRET)
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", USER_ISSUER)
    token = make_token(secret="a" * 64, algorithm="HS384")
    with pytest.raises(HTTPException) as exc:
        api.require_authenticated_identity(f"Bearer {token}")
    assert exc.value.status_code == 401


def test_user_route_rejects_a_valid_internal_service_token(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", USER_SECRET)
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", USER_ISSUER)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", SERVICE_SECRET)
    monkeypatch.setenv("INTERNAL_SERVICE_ISSUER", "kms-internal")
    monkeypatch.setenv("INTERNAL_SERVICE_AUDIENCE", "kms-nlp")
    service_token = make_token(
        SERVICE_SECRET,
        issuer="kms-internal",
        audience="kms-nlp",
        role="service",
    )
    service_identity = api.verify_internal_service_token(service_token)
    assert service_identity["source"] == "internal_service"

    response = TestClient(api.app).get(
        "/ramp-plans?company_id=company-123",
        headers={"Authorization": f"Bearer {service_token}"},
    )
    assert response.status_code == 401


def test_api_route_rejects_forged_identity_header(monkeypatch):
    response = TestClient(api.app).get(
        "/ramp-plans?company_id=company-123",
        headers={"X-User-Id": "user-123"},
    )
    assert response.status_code == 401


def test_service_token_rejects_wrong_audience(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", SERVICE_SECRET)
    monkeypatch.setenv("INTERNAL_SERVICE_ISSUER", "kms-internal")
    monkeypatch.setenv("INTERNAL_SERVICE_AUDIENCE", "kms-nlp")
    token = make_token(
        SERVICE_SECRET,
        issuer="kms-internal",
        audience="other-service",
        role="service",
    )
    with pytest.raises(HTTPException) as exc:
        api.verify_internal_service_token(token)
    assert exc.value.status_code == 401


def test_require_company_membership_rejects_default(monkeypatch):
    monkeypatch.setattr(api, "supabase", FakeSupabase([]))
    with pytest.raises(HTTPException) as exc:
        api.require_company_membership("user-1", "default")
    assert exc.value.status_code == 400


def test_require_company_membership_requires_user_id(monkeypatch):
    monkeypatch.setattr(api, "supabase", FakeSupabase([]))
    with pytest.raises(HTTPException) as exc:
        api.require_company_membership(None, "company-123")
    assert exc.value.status_code == 401


def test_require_company_membership_rejects_cross_tenant_lookup(monkeypatch):
    fake_rows = [{"company_id": "company-456", "user_id": "user-1", "role": "member"}]
    monkeypatch.setattr(api, "supabase", FakeSupabase(fake_rows))
    with pytest.raises(HTTPException) as exc:
        api.require_company_membership("user-1", "company-123")
    assert exc.value.status_code == 403


def test_require_company_membership_rejects_non_member(monkeypatch):
    monkeypatch.setattr(api, "supabase", FakeSupabase([]))
    with pytest.raises(HTTPException) as exc:
        api.require_company_membership("user-2", "company-123")
    assert exc.value.status_code == 403


def test_require_company_membership_accepts_member(monkeypatch):
    fake_rows = [{"company_id": "company-123", "user_id": "user-1", "role": "member"}]
    monkeypatch.setattr(api, "supabase", FakeSupabase(fake_rows))
    membership = api.require_company_membership("user-1", "company-123")
    assert membership["company_id"] == "company-123"
    assert membership["role"] == "member"


def test_require_company_membership_requires_admin_for_admin_routes(monkeypatch):
    fake_rows = [{"company_id": "company-123", "user_id": "user-1", "role": "member"}]
    monkeypatch.setattr(api, "supabase", FakeSupabase(fake_rows))
    with pytest.raises(HTTPException) as exc:
        api.require_company_membership("user-1", "company-123", require_role="admin")
    assert exc.value.status_code == 403

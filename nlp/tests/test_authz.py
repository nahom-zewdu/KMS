from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
import logging

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError

import api

SERVICE_SECRET = "service-token-test-secret-at-least-32-bytes"
USER_ISSUER = "https://kms-test.supabase.co/auth/v1"
USER_URL = "https://kms-test.supabase.co"
USER_AUDIENCE = "authenticated"
USER_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())


def make_user_token(
    *,
    private_key=USER_PRIVATE_KEY,
    issuer=USER_ISSUER,
    audience=USER_AUDIENCE,
    role="authenticated",
    expires_at=None,
    include_exp=True,
    include_iat=True,
    include_audience=True,
    subject="user-123",
):
    now = datetime.now(timezone.utc)
    claims = {"sub": subject, "iss": issuer, "role": role}
    if include_iat:
        claims["iat"] = int(now.timestamp())
    if include_audience:
        claims["aud"] = audience
    if include_exp:
        claims["exp"] = int((expires_at or now + timedelta(minutes=5)).timestamp())
    return jwt.encode(
        claims,
        private_key,
        algorithm="ES256",
        headers={"kid": "test-key"},
    )


def make_service_token(
    *,
    secret=SERVICE_SECRET,
    issuer="kms-internal",
    audience="kms-nlp",
    role="service",
    subject="kms-api",
    company_id=None,
):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": subject,
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "role": role,
    }
    if company_id is not None:
        claims["company_id"] = company_id
    return jwt.encode(claims, secret, algorithm="HS256")


class FakeJWKClient:
    def __init__(self, public_key=None, error=None):
        self.public_key = public_key or USER_PRIVATE_KEY.public_key()
        self.error = error
        self.tokens = []

    def get_signing_key_from_jwt(self, token):
        self.tokens.append(token)
        if self.error:
            raise self.error
        return SimpleNamespace(key=self.public_key)


class FakeResponse:
    def __init__(self, rows):
        self.data = rows


class FakeTable:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = list(rows)
        self.filters: dict[str, Any] = {}

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


def configure_user_jwks(monkeypatch, *, public_key=None, error=None):
    monkeypatch.setenv("SUPABASE_URL", USER_URL)
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", USER_ISSUER)
    monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", USER_AUDIENCE)
    monkeypatch.delenv("SUPABASE_JWKS_URL", raising=False)
    client = FakeJWKClient(public_key=public_key, error=error)
    requested_urls = []

    def get_client(url):
        requested_urls.append(url)
        return client

    monkeypatch.setattr(api, "get_supabase_jwks_client", get_client)
    return client, requested_urls


def test_missing_authorization_header_is_rejected():
    with pytest.raises(HTTPException) as exc:
        api.require_authenticated_identity()
    assert exc.value.status_code == 401


@pytest.mark.parametrize("authorization", ["Basic abc", "Bearer", "Bearer a b", ""])
def test_malformed_bearer_header_is_rejected(authorization, caplog):
    caplog.set_level(logging.INFO, logger="kms.auth")
    with pytest.raises(HTTPException) as exc:
        api.require_authenticated_identity(authorization)
    assert exc.value.status_code == 401
    expected_reason = (
        "missing_authorization_header"
        if not authorization
        else "malformed_authorization_header"
    )
    assert expected_reason in caplog.text


def test_valid_es256_supabase_token_uses_default_project_jwks(monkeypatch):
    client, requested_urls = configure_user_jwks(monkeypatch)
    token = make_user_token()

    identity = api.require_authenticated_identity(f"Bearer {token}")

    assert identity["user_id"] == "user-123"
    assert identity["source"] == "supabase_user"
    assert client.tokens == [token]
    assert requested_urls == [f"{USER_URL}/auth/v1/.well-known/jwks.json"]


def test_invalid_es256_signature_is_rejected(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="kms.auth")
    configure_user_jwks(monkeypatch)
    token = make_user_token(private_key=OTHER_PRIVATE_KEY)

    with pytest.raises(HTTPException) as exc:
        api.require_authenticated_identity(f"Bearer {token}")

    assert exc.value.status_code == 401
    assert "invalid_signature" in caplog.text
    assert token not in caplog.text


@pytest.mark.parametrize(
    ("token", "failure_reason"),
    [
        (
            make_user_token(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)),
            "expired",
        ),
        (make_user_token(issuer="https://attacker.invalid/auth/v1"), "wrong_issuer"),
        (make_user_token(audience="service_role"), "wrong_audience"),
    ],
)
def test_expired_wrong_issuer_and_wrong_audience_tokens_are_rejected(
    monkeypatch, caplog, token, failure_reason
):
    caplog.set_level(logging.INFO, logger="kms.auth")
    configure_user_jwks(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        api.require_authenticated_identity(f"Bearer {token}")

    assert exc.value.status_code == 401
    assert failure_reason in caplog.text


@pytest.mark.parametrize(
    "token",
    [
        make_user_token(include_exp=False),
        make_user_token(include_iat=False),
        make_user_token(include_audience=False),
        make_user_token(role="service"),
        make_user_token(subject=""),
    ],
)
def test_required_user_claims_are_enforced(monkeypatch, token):
    configure_user_jwks(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        api.require_authenticated_identity(f"Bearer {token}")

    assert exc.value.status_code == 401


def test_missing_supabase_url_fails_as_configuration_error(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)

    with pytest.raises(HTTPException) as exc:
        api.verify_bearer_token("not-a-real-token")

    assert exc.value.status_code == 503


def test_invalid_jwks_url_fails_as_configuration_error(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", USER_URL)
    monkeypatch.setenv("SUPABASE_JWKS_URL", "not-a-url")

    with pytest.raises(HTTPException) as exc:
        api.verify_bearer_token("not-a-real-token")

    assert exc.value.status_code == 503


def test_jwks_connection_failure_is_unavailable_not_unauthorized(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="kms.auth")
    configure_user_jwks(
        monkeypatch,
        error=PyJWKClientConnectionError("test connection failure"),
    )

    with pytest.raises(HTTPException) as exc:
        api.verify_bearer_token("test-token")

    assert exc.value.status_code == 503
    assert "jwks_unavailable" in caplog.text
    assert "test-token" not in caplog.text


def test_internal_service_token_is_separate_from_user_auth(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", SERVICE_SECRET)
    monkeypatch.setenv("INTERNAL_SERVICE_ISSUER", "kms-internal")
    monkeypatch.setenv("INTERNAL_SERVICE_AUDIENCE", "kms-nlp")
    configure_user_jwks(monkeypatch)
    service_token = make_service_token()

    assert api.verify_internal_service_token(service_token)["source"] == "internal_service"
    response = TestClient(api.app).get(
        "/ramp-plans?company_id=company-a",
        headers={"Authorization": f"Bearer {service_token}"},
    )
    assert response.status_code == 401


def test_internal_service_token_rejects_wrong_audience(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="kms.auth")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", SERVICE_SECRET)
    monkeypatch.setenv("INTERNAL_SERVICE_ISSUER", "kms-internal")
    monkeypatch.setenv("INTERNAL_SERVICE_AUDIENCE", "kms-nlp")
    token = make_service_token(audience="other-service")

    with pytest.raises(HTTPException) as exc:
        api.verify_internal_service_token(token)

    assert exc.value.status_code == 401
    assert "internal_service_wrong_audience" in caplog.text
    assert token not in caplog.text


def test_internal_service_token_requires_nonempty_subject(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="kms.auth")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", SERVICE_SECRET)
    monkeypatch.setenv("INTERNAL_SERVICE_ISSUER", "kms-internal")
    monkeypatch.setenv("INTERNAL_SERVICE_AUDIENCE", "kms-nlp")
    token = make_service_token(subject=" ")

    with pytest.raises(HTTPException) as exc:
        api.verify_internal_service_token(token)

    assert exc.value.status_code == 401
    assert "missing_internal_service_subject" in caplog.text
    assert token not in caplog.text


def test_internal_playbook_requires_company_scoped_service_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", SERVICE_SECRET)
    monkeypatch.setenv("INTERNAL_SERVICE_ISSUER", "kms-internal")
    monkeypatch.setenv("INTERNAL_SERVICE_AUDIENCE", "kms-nlp")
    generated = {}

    class FakeGenerator:
        def generate(self, *, role, employee_name, company_id):
            generated.update(role=role, employee_name=employee_name, company_id=company_id)
            return {"company_id": company_id}

    monkeypatch.setattr(api, "generator", FakeGenerator())
    token = make_service_token(company_id="company-a")
    client = TestClient(api.app)

    response = client.post(
        "/internal/playbooks/generate",
        json={"role": "backend-engineer", "company_id": "company-a"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert generated == {
        "role": "backend-engineer",
        "employee_name": "",
        "company_id": "company-a",
    }

    cross_company = client.post(
        "/internal/playbooks/generate",
        json={"role": "backend-engineer", "company_id": "company-b"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cross_company.status_code == 403
    assert generated["company_id"] == "company-a"


def test_ramp_plan_requires_company_membership(monkeypatch):
    configure_user_jwks(monkeypatch)
    monkeypatch.setattr(
        api,
        "supabase",
        FakeSupabase([{"company_id": "company-a", "user_id": "user-123", "role": "member"}]),
    )
    calls = []

    class FakeRampPlanner:
        def get_active(self, company_id, role, user_id):
            calls.append((company_id, role, user_id))
            return {"company_id": company_id, "role": role}

    monkeypatch.setattr(api, "ramp_generator", FakeRampPlanner())
    token = make_user_token()
    response = TestClient(api.app).get(
        "/ramp-plans?company_id=company-a&role=backend-engineer",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert calls == [("company-a", "backend-engineer", "user-123")]


def test_ramp_plan_rejects_nonmember_company(monkeypatch):
    configure_user_jwks(monkeypatch)
    monkeypatch.setattr(
        api,
        "supabase",
        FakeSupabase([{"company_id": "company-b", "user_id": "user-123", "role": "member"}]),
    )
    calls = []

    class FakeRampPlanner:
        def get_active(self, company_id, role, user_id):
            calls.append((company_id, role, user_id))
            return {"company_id": company_id}

    monkeypatch.setattr(api, "ramp_generator", FakeRampPlanner())
    response = TestClient(api.app).get(
        "/ramp-plans?company_id=company-a&role=backend-engineer",
        headers={"Authorization": f"Bearer {make_user_token()}"},
    )

    assert response.status_code == 403
    assert calls == []


def test_api_route_rejects_forged_identity_header():
    response = TestClient(api.app).get(
        "/ramp-plans?company_id=company-a",
        headers={"X-User-Id": "user-123"},
    )
    assert response.status_code == 401


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
    fake_rows = [{"company_id": "company-b", "user_id": "user-1", "role": "member"}]
    monkeypatch.setattr(api, "supabase", FakeSupabase(fake_rows))
    with pytest.raises(HTTPException) as exc:
        api.require_company_membership("user-1", "company-a")
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

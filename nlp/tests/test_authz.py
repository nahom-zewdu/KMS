import jwt
import pytest
from fastapi import HTTPException

import api


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
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "super-secret")
    token = jwt.encode({"sub": "user-123", "role": "authenticated"}, "super-secret", algorithm="HS256")
    identity = api.require_authenticated_identity(f"Bearer {token}")
    assert identity["user_id"] == "user-123"


def test_require_authenticated_identity_rejects_forged_user_header(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "super-secret")
    with pytest.raises(HTTPException) as exc:
        api.require_authenticated_identity(None, legacy_user_id="forged-user")
    assert exc.value.status_code == 401


def test_require_authenticated_identity_rejects_invalid_bearer_token(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "super-secret")
    with pytest.raises(HTTPException) as exc:
        api.require_authenticated_identity("Bearer invalid.token.value")
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

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api


class FakeResponse:
    def __init__(self, rows):
        self.data = rows


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def execute(self):
        return FakeResponse(self.rows)


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "company_members"
        return FakeTable(self.rows)


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

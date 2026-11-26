from types import SimpleNamespace

import pytest

from query_engine.repository_scope import TrustedRepositoryScopeResolver


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.limit_value = None
        self.not_ = self

    def select(self, *_args):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def is_(self, field, value):
        self.filters.append((field, None if value == "null" else value))
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        rows = [
            row for row in self.rows
            if all(row.get(field) == value for field, value in self.filters)
        ]
        return SimpleNamespace(data=rows[:self.limit_value])


class _Supabase:
    def __init__(self, rows):
        self.rows = rows
        self.last_query = None

    def table(self, name):
        assert name == "repositories"
        self.last_query = _Query(self.rows)
        return self.last_query


def _repo(repo_id, company="company-a", snapshot="snapshot-1"):
    return {
        "id": repo_id,
        "company_id": company,
        "full_name": f"acme/{repo_id}",
        "active_snapshot_id": snapshot,
    }


def test_resolves_the_only_active_repository_for_company():
    db = _Supabase([_repo("repo-1"), _repo("repo-old", snapshot=None)])
    result = TrustedRepositoryScopeResolver(db).resolve("company-a")

    assert result.resolved
    assert result.repository_id == "repo-1"
    assert result.full_name == "acme/repo-1"
    assert result.reason is None
    assert ("company_id", "company-a") in db.last_query.filters
    assert ("active_snapshot_id", None) in db.last_query.filters
    assert db.last_query.limit_value == 2


def test_does_not_choose_when_company_has_multiple_active_repositories():
    db = _Supabase([_repo("repo-1"), _repo("repo-2")])
    result = TrustedRepositoryScopeResolver(db).resolve("company-a")

    assert not result.resolved
    assert result.repository_id is None
    assert result.reason == "multiple_active_repositories"


def test_explicit_repository_is_still_verified_against_company_and_snapshot():
    db = _Supabase([_repo("repo-1")])
    result = TrustedRepositoryScopeResolver(db).resolve("company-a", "repo-1")

    assert result.resolved
    assert ("company_id", "company-a") in db.last_query.filters
    assert ("id", "repo-1") in db.last_query.filters
    assert ("active_snapshot_id", None) not in db.last_query.filters


@pytest.mark.parametrize("company_id", ["", "default", "  DEFAULT  "])
def test_rejects_missing_or_placeholder_company_scope(company_id):
    resolver = TrustedRepositoryScopeResolver(_Supabase([]))
    with pytest.raises(ValueError, match="company_id"):
        resolver.resolve(company_id)


def test_returns_no_active_repository_when_inventory_is_empty():
    result = TrustedRepositoryScopeResolver(_Supabase([])).resolve("company-a")
    assert result.reason == "no_active_repository"


def test_requested_repository_must_be_owned_by_the_authenticated_company():
    db = _Supabase([_repo("repo-1", company="company-b")])
    result = TrustedRepositoryScopeResolver(db).resolve("company-a", "repo-1")

    assert not result.resolved
    assert result.reason == "repository_not_found_for_company"

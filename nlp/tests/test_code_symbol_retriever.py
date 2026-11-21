"""Tests for active-snapshot and tenant-scoped symbol navigation."""

from types import SimpleNamespace

import pytest

from codebase.symbol_retriever import CodeSymbolRetriever


class Query:
    def __init__(self, table, rows, calls):
        self.table = table
        self.rows = rows
        self.calls = calls

    def select(self, value):
        self.calls.append((self.table, "select", value))
        return self

    def eq(self, key, value):
        self.calls.append((self.table, "eq", key, value))
        return self

    def ilike(self, key, value):
        self.calls.append((self.table, "ilike", key, value))
        return self

    def order(self, key):
        self.calls.append((self.table, "order", key))
        return self

    def limit(self, value):
        self.calls.append((self.table, "limit", value))
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows.get(self.table, []))


class Database:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def table(self, name):
        return Query(name, self.rows, self.calls)


def test_file_navigation_uses_company_and_active_snapshot_filters():
    rows = {
        "repositories": [{"active_snapshot_id": "snapshot-current"}],
        "code_symbols": [{"qualified_name": "Worker.run", "start_byte": 12}],
    }
    database = Database(rows)
    retriever = CodeSymbolRetriever(database)

    result = retriever.list_file_symbols(
        company_id="company-a",
        repository_id="repo-a",
        file_path="src/worker.py",
    )

    assert result == rows["code_symbols"]
    filters = [call for call in database.calls if call[0] == "code_symbols" and call[1] == "eq"]
    assert ("code_symbols", "eq", "company_id", "company-a") in filters
    assert ("code_symbols", "eq", "repository_id", "repo-a") in filters
    assert ("code_symbols", "eq", "snapshot_id", "snapshot-current") in filters
    repository_filters = [
        call for call in database.calls if call[0] == "repositories" and call[1] == "eq"
    ]
    assert ("repositories", "eq", "company_id", "company-a") in repository_filters


def test_missing_or_cross_tenant_repository_returns_no_symbols():
    database = Database({"repositories": [], "code_symbols": [{"name": "must-not-leak"}]})
    retriever = CodeSymbolRetriever(database)

    assert retriever.find_qualified_name(
        company_id="company-a",
        repository_id="not-owned-by-company-a",
        qualified_name="Worker.run",
    ) == []
    assert not any(call[0] == "code_symbols" for call in database.calls)


def test_search_escapes_like_wildcards_and_keeps_tenant_scope():
    database = Database({
        "repositories": [{"active_snapshot_id": "snapshot-a"}],
        "code_symbols": [],
    })
    retriever = CodeSymbolRetriever(database)

    retriever.search_names(
        company_id="company-a",
        repository_id="repo-a",
        term="Worker_%\\",
    )

    assert ("code_symbols", "ilike", "qualified_name", "%Worker\\_\\%\\\\%") in database.calls


@pytest.mark.parametrize(
    "company_id,repository_id",
    [("", "repo-a"), ("default", "repo-a"), ("company-a", "")],
)
def test_invalid_scope_is_rejected_before_database_access(company_id, repository_id):
    database = Database({})
    retriever = CodeSymbolRetriever(database)

    with pytest.raises(ValueError):
        retriever.list_file_symbols(
            company_id=company_id,
            repository_id=repository_id,
            file_path="src/main.py",
        )

    assert database.calls == []

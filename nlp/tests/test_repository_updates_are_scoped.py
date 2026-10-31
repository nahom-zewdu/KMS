import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

from codebase.analyzer import CodebaseAnalyzer
from codebase.baseline import CodebaseBaselineSync


class RecordingQuery:
    def __init__(self, database, table):
        self.database = database
        self.table_name = table
        self.operation = "select"
        self.filters = []

    def select(self, *_args, **_kwargs):
        self.operation = "select"
        return self

    def update(self, *_args, **_kwargs):
        self.operation = "update"
        return self

    def upsert(self, *_args, **_kwargs):
        self.operation = "upsert"
        return self

    def insert(self, *_args, **_kwargs):
        self.operation = "insert"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        self.database.calls.append((self.table_name, self.operation, list(self.filters)))
        if self.table_name == "repositories" and self.operation == "select":
            return SimpleNamespace(data=[{"id": "repo-id"}])
        return SimpleNamespace(data=[])


class RecordingSupabase:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return RecordingQuery(self, name)


def _assert_repository_update_is_tenant_scoped(database):
    updates = [
        filters
        for table, operation, filters in database.calls
        if table == "repositories" and operation == "update"
    ]
    assert len(updates) == 1
    assert ("id", "repo-id") in updates[0]
    assert ("company_id", "company-a") in updates[0]


def test_incremental_repository_update_filters_by_company():
    database = RecordingSupabase()
    analyzer = CodebaseAnalyzer(database)

    asyncio.run(
        analyzer._upsert_file(
            "src/service.py",
            "org/repo",
            "delivery",
            {"head_commit": {"id": "sha"}},
            "company-a",
        )
    )

    _assert_repository_update_is_tenant_scoped(database)


def test_baseline_repository_update_filters_by_company():
    database = RecordingSupabase()
    repository = SimpleNamespace(
        full_name="org/repo",
        description="description",
        language="Python",
        default_branch="main",
        get_commits=lambda: [],
        get_contents=lambda _path: [],
    )
    sync = CodebaseBaselineSync.__new__(CodebaseBaselineSync)
    sync.supabase = database
    sync.gh = SimpleNamespace(get_repo=lambda _name: repository)
    sync.relationship_indexer = SimpleNamespace(index_repository=lambda *_args: 0)

    assert sync.sync_repository("org/repo", "company-a")
    _assert_repository_update_is_tenant_scoped(database)

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

    def update(self, values, *_args, **_kwargs):
        self.database.updates.append((self.table_name, dict(values)))
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
        self.updates = []
        self.rpc_calls = []

    def table(self, name):
        return RecordingQuery(self, name)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=0))


def _assert_repository_update_is_tenant_scoped(database):
    updates = [
        filters
        for table, operation, filters in database.calls
        if table == "repositories" and operation == "update"
    ]
    assert updates
    assert all(("company_id", "company-a") in filters for filters in updates)
    assert any(("id", "repo-id") in filters for filters in updates)


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
        get_branch=lambda _branch: SimpleNamespace(commit=SimpleNamespace(sha="a" * 40)),
        get_contents=lambda _path, ref=None: [],
    )
    sync = CodebaseBaselineSync.__new__(CodebaseBaselineSync)
    sync.supabase = database
    sync.gh = SimpleNamespace(get_repo=lambda _name: repository)
    sync.relationship_indexer = SimpleNamespace(index_repository=lambda *_args, **_kwargs: 0)

    assert sync.sync_repository("org/repo", "company-a")
    _assert_repository_update_is_tenant_scoped(database)
    assert any(
        table == "repositories"
        and operation == "update"
        and ("full_name", "org/repo") in filters
        and ("company_id", "company-a") in filters
        for table, operation, filters in database.calls
    )
    assert any(
        table == "repositories"
        and values.get("baseline_status") == "ready"
        and values.get("last_synced_at")
        and values.get("baseline_revision") == "a" * 40
        for table, values in database.updates
    )



def test_failed_directory_traversal_never_runs_destructive_reconciliation():
    from github import GithubException

    database = RecordingSupabase()
    restricted_directory = SimpleNamespace(type="dir", path="restricted")
    repository = SimpleNamespace(
        full_name="org/repo",
        description="description",
        language="Python",
        default_branch="main",
        get_commits=lambda: [],
        get_branch=lambda _branch: SimpleNamespace(commit=SimpleNamespace(sha="a" * 40)),
        get_contents=lambda path, ref=None: (
            [restricted_directory]
            if path == ""
            else (_ for _ in ()).throw(
                GithubException(403, {"message": "Forbidden"}, {})
            )
        ),
    )
    sync = CodebaseBaselineSync.__new__(CodebaseBaselineSync)
    sync.supabase = database
    sync.gh = SimpleNamespace(get_repo=lambda _name: repository)
    sync.relationship_indexer = SimpleNamespace(index_repository=lambda *_args, **_kwargs: 0)

    assert not sync.sync_repository("org/repo", "company-a")
    assert database.rpc_calls == []
    assert any(
        table == "repositories" and values.get("baseline_status") == "failed"
        for table, values in database.updates
    )

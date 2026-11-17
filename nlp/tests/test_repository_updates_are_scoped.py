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
        result = {
            "claim_repository_baseline": "claimed",
            "renew_repository_baseline_lease": True,
            "create_repository_snapshot": "snapshot-id",
            "publish_repository_snapshot": True,
            "fail_repository_snapshot": True,
            "fail_repository_baseline": True,
        }.get(name, False)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=result))


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
        and ("id", "repo-id") in filters
        and ("company_id", "company-a") in filters
        for table, operation, filters in database.calls
    )
    snapshot_creation = next(
        params for name, params in database.rpc_calls
        if name == "create_repository_snapshot"
    )
    assert snapshot_creation["p_repository_id"] == "repo-id"
    assert snapshot_creation["p_company_id"] == "company-a"
    assert snapshot_creation["p_source_revision"] == "a" * 40

    publication = next(
        params for name, params in database.rpc_calls
        if name == "publish_repository_snapshot"
    )
    assert publication["p_snapshot_id"] == "snapshot-id"
    assert publication["p_file_count"] == 0
    assert publication["p_module_count"] == 0



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
    rpc_names = [name for name, _params in database.rpc_calls]
    assert "claim_repository_baseline" in rpc_names
    assert "create_repository_snapshot" in rpc_names
    assert "fail_repository_snapshot" in rpc_names
    assert "fail_repository_baseline" not in rpc_names
    assert "reconcile_repository_files" not in rpc_names
    assert "complete_repository_baseline" not in rpc_names
    assert not any(
        table == "repositories" and values.get("last_synced_at")
        for table, values in database.updates
    )

def test_staged_author_metadata_does_not_mutate_shared_file_entity():
    class CaptureQuery:
        def __init__(self, table):
            self.table = table
        def upsert(self, values, **_kwargs):
            self.table.payloads.append(values)
            return self
        def execute(self):
            return SimpleNamespace(data=[])

    class CaptureDatabase:
        def __init__(self):
            self.payloads = []
        def table(self, _name):
            query = CaptureQuery(self)
            query.table = self
            return query

    database = CaptureDatabase()
    sync = CodebaseBaselineSync.__new__(CodebaseBaselineSync)
    sync.supabase = database

    sync._index_file(
        SimpleNamespace(path="src/service.py", sha="blob-sha"),
        "repository-entity",
        "repository-id",
        "org/repo",
        "company-a",
        last_author="alice",
        snapshot_id="snapshot-id",
        source_revision="commit-sha",
    )

    file_entity = database.payloads[0]
    assert file_entity["type"] == "FILE"
    assert file_entity["metadata"]["file_path"] == "src/service.py"
    assert "last_author" not in file_entity["metadata"]

    file_row = next(
        payload for payload in database.payloads
        if payload.get("snapshot_id") == "snapshot-id"
    )
    assert file_row["last_author"] == "alice"
    assert file_row["last_commit_sha"] == "commit-sha"
    assert file_row["metadata"]["blob_sha"] == "blob-sha"



def test_baseline_passes_revision_pinned_source_to_symbol_indexer():
    class Query:
        def __init__(self, database):
            self.database = database

        def upsert(self, values, **_kwargs):
            self.database.payloads.append(values)
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    class Database:
        def __init__(self):
            self.payloads = []

        def table(self, _name):
            return Query(self)

    class SymbolIndexer:
        max_source_bytes = 1_000_000

        def __init__(self):
            self.calls = []

        def index_file(self, **kwargs):
            self.calls.append(kwargs)
            return {"status": "indexed", "symbols_persisted": 2, "source_bytes": 30}

    database = Database()
    sync = CodebaseBaselineSync.__new__(CodebaseBaselineSync)
    sync.supabase = database
    sync.symbol_indexer = SymbolIndexer()
    source = b"class Worker:\\n    pass\\n"

    metrics = sync._index_file(
        SimpleNamespace(
            path="src/worker.py",
            sha="blob-sha",
            size=len(source),
            decoded_content=source,
        ),
        "repository-entity",
        "repository-id",
        "org/repo",
        "company-a",
        snapshot_id="snapshot-id",
        source_revision="commit-sha",
    )

    assert sync.symbol_indexer.calls == [{
        "repository_id": "repository-id",
        "snapshot_id": "snapshot-id",
        "company_id": "company-a",
        "file_path": "src/worker.py",
        "source": "class Worker:\\n    pass\\n",
        "source_revision": "commit-sha",
        "language": "Python",
    }]
    assert metrics["files_indexed"] == 1
    assert metrics["symbols_persisted"] == 2

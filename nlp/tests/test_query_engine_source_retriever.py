from types import SimpleNamespace
from unittest.mock import Mock, patch

from query_engine.source_retriever import retrieve_source_chunks


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def in_(self, key, values):
        self.filters[key] = set(values)
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        rows = self.rows
        for key, value in self.filters.items():
            if isinstance(value, set):
                rows = [row for row in rows if row.get(key) in value]
            else:
                rows = [row for row in rows if row.get(key) == value]
        return SimpleNamespace(data=rows)


class Supabase:
    def __init__(self):
        self.tables = {
            "repositories": [{
                "id": "repo-1",
                "company_id": "company-a",
                "full_name": "acme/service",
                "default_branch": "main",
                "baseline_revision": "abc123",
            }],
            "codebase_files": [{
                "repository_id": "repo-1",
                "file_path": "api/handlers/routes.go",
                "language": "Go",
                "module_path": "api/handlers",
                "last_author": "alice",
            }],
        }

    def table(self, name):
        return Query(self.tables.get(name, []))


def test_source_retrieval_fetches_only_indexed_company_file(monkeypatch):
    monkeypatch.setenv("GITHUB_API_TOKEN", "test-token")
    contents = SimpleNamespace(decoded_content=b"package handlers\\nfunc RegisterRoutes() {}")
    github_repo = Mock()
    github_repo.get_contents.return_value = contents
    github_client = Mock()
    github_client.get_repo.return_value = github_repo

    with patch("query_engine.source_retriever.Github", return_value=github_client):
        chunks = retrieve_source_chunks(
            Supabase(),
            "company-a",
            "Can you tell me about those files?",
            '{"kind":"ramp_step","active_step":{"target":{"repo":"acme/service","files":[{"path":"api/handlers/routes.go","repository_id":"repo-1"}]}}}',
            conversation_history=[],
        )

    assert len(chunks) == 1
    assert chunks[0]["file_path"] == "api/handlers/routes.go"
    assert "func RegisterRoutes" in chunks[0]["content"]
    github_client.get_repo.assert_called_once_with("acme/service")
    github_repo.get_contents.assert_called_once_with("api/handlers/routes.go", ref="abc123")


def test_source_retrieval_never_fetches_unindexed_path(monkeypatch):
    monkeypatch.setenv("GITHUB_API_TOKEN", "test-token")
    github_client = Mock()
    with patch("query_engine.source_retriever.Github", return_value=github_client):
        chunks = retrieve_source_chunks(
            Supabase(),
            "company-a",
            "Explain api/handlers/secrets.go",
            '{"kind":"ramp_step","active_step":{"target":{"files":[{"path":"api/handlers/secrets.go"}]}}}',
        )

    assert chunks == []
    github_client.get_repo.assert_not_called()

def test_source_retrieval_fails_closed_when_supabase_returns_mock_response(monkeypatch):
    monkeypatch.setenv("GITHUB_API_TOKEN", "test-token")
    supabase = Mock()
    with patch("query_engine.source_retriever.Github") as github:
        chunks = retrieve_source_chunks(
            supabase,
            "company-a",
            "Explain api/handlers/secrets.go",
            '{"kind":"ramp_step","active_step":{"target":{"files":[{"path":"api/handlers/secrets.go"}]}}}',
        )

    assert chunks == []
    github.assert_not_called()


def test_source_retrieval_skips_github_mock_content(monkeypatch):
    monkeypatch.setenv("GITHUB_API_TOKEN", "test-token")
    github_repo = Mock()
    github_repo.get_contents.return_value = Mock()
    github_client = Mock()
    github_client.get_repo.return_value = github_repo

    with patch("query_engine.source_retriever.Github", return_value=github_client):
        chunks = retrieve_source_chunks(
            Supabase(),
            "company-a",
            "Explain the handlers",
            '{"kind":"ramp_step","active_step":{"target":{"files":[{"path":"api/handlers/routes.go","repository_id":"repo-1"}]}}}',
        )

    assert chunks == []
    github_repo.get_contents.assert_called_once_with("api/handlers/routes.go", ref="abc123")


def test_source_retrieval_keeps_legacy_files_in_mixed_snapshot_company(monkeypatch):
    monkeypatch.setenv("GITHUB_API_TOKEN", "test-token")
    supabase = Supabase()
    supabase.tables["repositories"] = [
        {
            "id": "repo-snapshot",
            "company_id": "company-a",
            "full_name": "acme/snapshot",
            "default_branch": "main",
            "baseline_revision": "revision-1",
            "active_snapshot_id": "snapshot-1",
            "baseline_status": "ready",
        },
        {
            "id": "repo-legacy",
            "company_id": "company-a",
            "full_name": "acme/legacy",
            "default_branch": "main",
            "baseline_revision": "legacy-revision",
            "active_snapshot_id": None,
            "baseline_status": "ready",
        },
    ]
    supabase.tables["codebase_files"] = [
        {
            "repository_id": "repo-snapshot",
            "file_path": "api/current.go",
            "language": "Go",
            "snapshot_id": "snapshot-1",
        },
        {
            "repository_id": "repo-snapshot",
            "file_path": "api/old.go",
            "language": "Go",
            "snapshot_id": "failed-snapshot",
        },
        {
            "repository_id": "repo-legacy",
            "file_path": "legacy/handler.go",
            "language": "Go",
            "snapshot_id": None,
        },
    ]
    contents = SimpleNamespace(decoded_content=b"package handlers\\nfunc Handle() {}")
    github_repos = {}
    def get_repo(name):
        github_repos.setdefault(name, Mock())
        github_repos[name].get_contents.return_value = contents
        return github_repos[name]
    github_client = Mock()
    github_client.get_repo.side_effect = get_repo

    context = '{"kind":"ramp_step","active_step":{"target":{"files":['
    context += '{"path":"api/current.go","repository_id":"repo-snapshot"},'
    context += '{"path":"legacy/handler.go","repository_id":"repo-legacy"}]}}}'

    with patch("query_engine.source_retriever.Github", return_value=github_client):
        chunks = retrieve_source_chunks(
            supabase, "company-a", "Can you explain those files?", context
        )

    assert {chunk["file_path"] for chunk in chunks} == {
        "api/current.go", "legacy/handler.go"
    }
    assert any("Repository: acme/legacy" in chunk["content"] for chunk in chunks)
    github_repos["acme/legacy"].get_contents.assert_called_once_with(
        "legacy/handler.go", ref="legacy-revision"
    )

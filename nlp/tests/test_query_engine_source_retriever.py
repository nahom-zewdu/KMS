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
    github_repo.get_contents.assert_called_once_with("api/handlers/routes.go", ref="main")


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

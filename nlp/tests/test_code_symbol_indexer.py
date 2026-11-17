"""Tests for bounded, snapshot-scoped symbol persistence."""

from types import SimpleNamespace

from codebase.symbol_indexer import CodeSymbolIndexer


class Query:
    def __init__(self, calls):
        self.calls = calls

    def upsert(self, rows, **kwargs):
        self.calls.append((rows, kwargs))
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class Database:
    def __init__(self):
        self.calls = []

    def table(self, name):
        assert name == "code_symbols"
        return Query(self.calls)


def test_index_file_persists_revision_pinned_declarations_in_batches():
    database = Database()
    indexer = CodeSymbolIndexer(database, batch_size=1)
    result = indexer.index_file(
        repository_id="repo-1",
        snapshot_id="snapshot-1",
        company_id="company-a",
        file_path="src/worker.py",
        source="class Worker:\n    def run(self):\n        return 1\n",
        source_revision="a" * 40,
        language="Python",
    )

    assert result["status"] == "indexed"
    assert result["symbols_persisted"] == 2
    assert len(database.calls) == 2
    rows = [call[0][0] for call in database.calls]
    assert {row["kind"] for row in rows} == {"class", "method"}
    assert all(row["repository_id"] == "repo-1" for row in rows)
    assert all(row["snapshot_id"] == "snapshot-1" for row in rows)
    assert all(row["company_id"] == "company-a" for row in rows)
    assert all(row["source_revision"] == "a" * 40 for row in rows)
    assert all(call[1] == {"on_conflict": "snapshot_id,symbol_id"} for call in database.calls)


def test_index_file_rejects_unsupported_languages_without_database_writes():
    database = Database()
    indexer = CodeSymbolIndexer(database)

    result = indexer.index_file(
        repository_id="repo-1",
        snapshot_id="snapshot-1",
        company_id="company-a",
        file_path="README.md",
        source="# docs",
        source_revision="a" * 40,
    )

    assert result["status"] == "unsupported"
    assert result["symbols_persisted"] == 0
    assert database.calls == []


def test_index_file_reports_oversized_sources_without_parsing_or_writing():
    database = Database()
    indexer = CodeSymbolIndexer(database, max_source_bytes=8)

    result = indexer.index_file(
        repository_id="repo-1",
        snapshot_id="snapshot-1",
        company_id="company-a",
        file_path="src/worker.py",
        source="class Worker: pass",
        source_revision="a" * 40,
    )

    assert result["status"] == "oversized"
    assert result["source_bytes"] > 8
    assert database.calls == []


def test_index_files_returns_explicit_coverage_and_parse_error_counts():
    database = Database()
    indexer = CodeSymbolIndexer(database)
    metrics = indexer.index_files(
        [
            {"path": "src/a.py", "content": "def ok():\n    return 1\n"},
            {"path": "src/b.py", "content": "def broken(:\n"},
            {"path": "README.md", "content": "# docs"},
        ],
        repository_id="repo-1",
        snapshot_id="snapshot-1",
        company_id="company-a",
        source_revision="a" * 40,
    )

    assert metrics["files_seen"] == 3
    assert metrics["files_indexed"] == 2
    assert metrics["files_with_syntax_errors"] == 1
    assert metrics["files_unsupported"] == 1
    assert metrics["symbols_persisted"] >= 1

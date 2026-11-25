"""Integration contract tests for durable source chunk ingestion."""

from types import SimpleNamespace
from unittest.mock import Mock

from codebase.baseline import CodebaseBaselineSync


class SourceChunkIndexer:
    def __init__(self):
        self.calls = []

    def index_file(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "indexed", "chunks_persisted": 3, "source_bytes": len(kwargs["source"].encode())}


def make_sync():
    sync = CodebaseBaselineSync.__new__(CodebaseBaselineSync)
    sync.supabase = Mock()
    sync.symbol_indexer = None
    sync.source_chunk_indexer = SourceChunkIndexer()
    return sync


def test_baseline_persists_decoded_source_at_pinned_snapshot_revision():
    sync = make_sync()
    source = "def charge():\n    return 'paid'\n"
    gh_file = SimpleNamespace(
        path="src/billing.py",
        sha="blob-sha",
        size=len(source.encode()),
        decoded_content=source.encode("utf-8"),
    )

    metrics = sync._index_file(
        gh_file,
        repo_entity_id="repo-entity",
        physical_repo_id="repo-id",
        repo_full_name="org/repo",
        company_id="company-a",
        snapshot_id="snapshot-a",
        source_revision="commit-a",
    )

    assert len(sync.source_chunk_indexer.calls) == 1
    assert sync.source_chunk_indexer.calls[0] == {
        "repository_id": "repo-id",
        "snapshot_id": "snapshot-a",
        "company_id": "company-a",
        "file_path": "src/billing.py",
        "source": source,
        "source_revision": "commit-a",
    }
    assert metrics["source_files_seen"] == 1
    assert metrics["source_files_indexed"] == 1
    assert metrics["source_files_rejected"] == 0
    assert metrics["source_chunks_persisted"] == 3


def test_baseline_marks_oversized_source_as_chunk_coverage_gap():
    sync = make_sync()
    source = "x" * 1_000_001
    gh_file = SimpleNamespace(
        path="src/billing.py",
        sha="blob-sha",
        size=len(source.encode()),
        decoded_content=source.encode("utf-8"),
    )

    metrics = sync._index_file(
        gh_file,
        repo_entity_id="repo-entity",
        physical_repo_id="repo-id",
        repo_full_name="org/repo",
        company_id="company-a",
        snapshot_id="snapshot-a",
        source_revision="commit-a",
    )

    assert sync.source_chunk_indexer.calls == []
    assert metrics["source_files_seen"] == 1
    assert metrics["source_files_indexed"] == 0
    assert metrics["source_files_rejected"] == 1
    assert metrics["source_chunks_persisted"] == 0

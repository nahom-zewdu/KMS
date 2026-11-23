"""Tests for deterministic source chunking and snapshot persistence."""
from types import SimpleNamespace

import pytest

from codebase.source_chunker import SourceChunker, SourceChunkingError
from codebase.source_chunk_indexer import SourceChunkIndexer


def test_chunker_is_deterministic_bounded_and_overlapping_with_utf8_offsets():
    source = "def alpha():\n    return 'é'\n\ndef beta():\n    return 2\n"
    chunker = SourceChunker(max_chunk_bytes=32, max_lines=3, overlap_lines=1)
    kwargs = dict(
        company_id="company-a", repository_id="repo-a", snapshot_id="snap-a",
        source_revision="a" * 40, file_path="src/service.py",
    )
    first = chunker.chunk(source, **kwargs)
    second = chunker.chunk(source, **kwargs)

    assert first == second
    assert len(first) > 1
    assert all(len(item.content.encode("utf-8")) <= 32 for item in first)
    assert all(item.end_byte - item.start_byte == len(item.content.encode("utf-8")) for item in first)
    assert all(item.chunker_version == "line-window-v1" for item in first)
    assert all(len(item.content_hash) == 64 for item in first)
    assert all(item.source_content_hash == first[0].source_content_hash for item in first)
    assert first[0].start_line == 1
    assert first[1].start_line <= first[0].end_line


def test_chunker_empty_source_returns_no_chunks_and_rejects_unsafe_paths():
    chunker = SourceChunker()
    kwargs = dict(
        company_id="company-a", repository_id="repo-a", snapshot_id="snap-a",
        source_revision="rev-a",
    )
    assert chunker.chunk("", file_path="src/empty.py", **kwargs) == []
    with pytest.raises(ValueError):
        chunker.chunk("x", file_path="../secret.py", **kwargs)


def test_chunker_rejects_oversized_source_and_single_oversized_line():
    with pytest.raises(SourceChunkingError):
        SourceChunker(max_source_bytes=3).chunk(
            "long", company_id="c", repository_id="r", snapshot_id="s",
            source_revision="rev", file_path="a.py",
        )
    with pytest.raises(SourceChunkingError):
        SourceChunker(max_chunk_bytes=3).chunk(
            "long\n", company_id="c", repository_id="r", snapshot_id="s",
            source_revision="rev", file_path="a.py",
        )


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
        assert name == "source_code_chunks"
        return Query(self.calls)


def test_indexer_persists_revision_scoped_chunks_idempotently_in_batches():
    db = Database()
    indexer = SourceChunkIndexer(
        db, chunker=SourceChunker(max_chunk_bytes=24, max_lines=2, overlap_lines=0),
        batch_size=1,
    )
    result = indexer.index_file(
        repository_id="repo-a", snapshot_id="snap-a", company_id="company-a",
        file_path="src/main.py", source="def one():\n    return 1\ndef two():\n    return 2\n",
        source_revision="a" * 40,
    )
    assert result["status"] == "indexed"
    assert result["chunks_persisted"] >= 2
    assert len(db.calls) == result["chunks_persisted"]
    rows = [batch[0] for batch, _ in db.calls]
    assert all(row["snapshot_id"] == "snap-a" for row in rows)
    assert all(row["source_revision"] == "a" * 40 for row in rows)
    assert all(call[1] == {"on_conflict": "snapshot_id,chunk_id"} for call in db.calls)


def test_indexer_reports_invalid_and_oversized_files_without_writes():
    db = Database()
    indexer = SourceChunkIndexer(db, chunker=SourceChunker(max_source_bytes=3))
    result = indexer.index_file(
        repository_id="r", snapshot_id="s", company_id="c", file_path="a.py",
        source="long", source_revision="rev",
    )
    assert result["status"] == "oversized"
    assert db.calls == []

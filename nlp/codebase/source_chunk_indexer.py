"""Bounded persistence for deterministic source chunks."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from codebase.source_chunker import SourceChunker


DEFAULT_BATCH_SIZE = 100


class SourceChunkIndexer:
    """Chunk and persist source files into one building immutable snapshot."""

    def __init__(
        self,
        supabase: Any,
        *,
        chunker: SourceChunker | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.supabase = supabase
        self.chunker = chunker or SourceChunker()
        self.batch_size = batch_size

    def index_file(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
        company_id: str,
        file_path: str,
        source: str,
        source_revision: str,
    ) -> dict[str, Any]:
        """Persist one file's chunks idempotently, preserving exact source ranges."""
        try:
            chunks = self.chunker.chunk(
                source,
                company_id=company_id,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                source_revision=source_revision,
                file_path=file_path,
            )
        except ValueError as exc:
            status = "oversized" if "max_" in str(exc) or "exceeds" in str(exc) else "invalid"
            return {"status": status, "chunks_persisted": 0, "error": str(exc)}

        rows = [
            {
                "repository_id": repository_id,
                "snapshot_id": snapshot_id,
                "company_id": company_id,
                "chunk_id": chunk.chunk_id,
                "file_path": chunk.file_path,
                "content": chunk.content,
                "content_hash": chunk.content_hash,
                "source_content_hash": chunk.source_content_hash,
                "source_revision": source_revision,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "start_byte": chunk.start_byte,
                "end_byte": chunk.end_byte,
                "chunk_index": chunk.chunk_index,
                "chunker_version": chunk.chunker_version,
            }
            for chunk in chunks
        ]
        for offset in range(0, len(rows), self.batch_size):
            self.supabase.table("source_code_chunks").upsert(
                rows[offset:offset + self.batch_size],
                on_conflict="snapshot_id,chunk_id",
            ).execute()
        return {
            "status": "indexed",
            "chunks_persisted": len(rows),
            "source_bytes": len(source.encode("utf-8")),
        }

    def index_files(
        self,
        files: Iterable[dict[str, str]],
        *,
        repository_id: str,
        snapshot_id: str,
        company_id: str,
        source_revision: str,
    ) -> dict[str, int]:
        """Index a deterministic file inventory and report explicit coverage."""
        metrics = {
            "files_seen": 0,
            "files_indexed": 0,
            "files_empty": 0,
            "files_rejected": 0,
            "chunks_persisted": 0,
        }
        for item in sorted(files, key=lambda value: value.get("path", "")):
            metrics["files_seen"] += 1
            result = self.index_file(
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                company_id=company_id,
                file_path=item.get("path", ""),
                source=item.get("content", ""),
                source_revision=source_revision,
            )
            if result["status"] == "indexed":
                metrics["files_indexed"] += 1
                metrics["chunks_persisted"] += result["chunks_persisted"]
                if result["chunks_persisted"] == 0:
                    metrics["files_empty"] += 1
            else:
                metrics["files_rejected"] += 1
        return metrics

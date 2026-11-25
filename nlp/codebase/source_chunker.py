"""Deterministic, bounded line-oriented chunks for immutable source snapshots.

Chunks retain exact UTF-8 byte and one-based line ranges. This module does
not fetch source files or perform database access.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


DEFAULT_CHUNKER_VERSION = "line-window-v1"


class SourceChunkingError(ValueError):
    """Raised when a source file cannot be represented within chunk limits."""


@dataclass(frozen=True, slots=True)
class SourceChunk:
    """One deterministic source range with content and provenance hashes."""

    chunk_id: str
    file_path: str
    content: str
    content_hash: str
    source_content_hash: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    chunk_index: int
    chunker_version: str


class SourceChunker:
    """Split UTF-8 source into bounded overlapping line windows."""

    def __init__(
        self,
        *,
        max_source_bytes: int = 1_000_000,
        max_chunk_bytes: int = 6_000,
        max_lines: int = 80,
        overlap_lines: int = 10,
        chunker_version: str = DEFAULT_CHUNKER_VERSION,
    ) -> None:
        if min(max_source_bytes, max_chunk_bytes, max_lines) < 1:
            raise ValueError("source, chunk, and line limits must be positive")
        if overlap_lines < 0 or overlap_lines >= max_lines:
            raise ValueError("overlap_lines must be between zero and max_lines - 1")
        if not chunker_version or not chunker_version.strip():
            raise ValueError("chunker_version is required")
        self.max_source_bytes = max_source_bytes
        self.max_chunk_bytes = max_chunk_bytes
        self.max_lines = max_lines
        self.overlap_lines = overlap_lines
        self.chunker_version = chunker_version

    def chunk(
        self,
        source: str,
        *,
        company_id: str,
        repository_id: str,
        snapshot_id: str,
        source_revision: str,
        file_path: str,
    ) -> list[SourceChunk]:
        """Return stable chunks for one exact file revision and snapshot."""
        for name, value in {
            "company_id": company_id,
            "repository_id": repository_id,
            "snapshot_id": snapshot_id,
            "source_revision": source_revision,
            "file_path": file_path,
        }.items():
            if not value or not value.strip():
                raise ValueError(f"{name} is required")
        if file_path.startswith("/") or "\\" in file_path or any(
            part in {"", ".", ".."} for part in file_path.split("/")
        ):
            raise ValueError("file_path must be a canonical relative POSIX path")

        source_bytes = source.encode("utf-8")
        if len(source_bytes) > self.max_source_bytes:
            raise SourceChunkingError("source file exceeds max_source_bytes")
        if not source_bytes:
            return []

        lines = source.splitlines(keepends=True)
        if not lines:
            lines = [source]
        encoded_lines = [line.encode("utf-8") for line in lines]
        for line_bytes in encoded_lines:
            if len(line_bytes) > self.max_chunk_bytes:
                raise SourceChunkingError("a source line exceeds max_chunk_bytes")

        offsets = [0]
        for line_bytes in encoded_lines:
            offsets.append(offsets[-1] + len(line_bytes))

        source_hash = hashlib.sha256(source_bytes).hexdigest()
        chunks: list[SourceChunk] = []
        start = 0
        while start < len(lines):
            end = start
            size = 0
            while end < len(lines) and end - start < self.max_lines:
                next_size = len(encoded_lines[end])
                if end > start and size + next_size > self.max_chunk_bytes:
                    break
                size += next_size
                end += 1

            content_bytes = b"".join(encoded_lines[start:end])
            content_hash = hashlib.sha256(content_bytes).hexdigest()
            start_byte, end_byte = offsets[start], offsets[end]
            identity = {
                "company_id": company_id,
                "repository_id": repository_id,
                "snapshot_id": snapshot_id,
                "source_revision": source_revision,
                "file_path": file_path,
                "start_byte": start_byte,
                "end_byte": end_byte,
                "content_hash": content_hash,
                "chunker_version": self.chunker_version,
            }
            chunk_id = hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            chunks.append(SourceChunk(
                chunk_id=chunk_id,
                file_path=file_path,
                content=content_bytes.decode("utf-8"),
                content_hash=content_hash,
                source_content_hash=source_hash,
                start_line=start + 1,
                end_line=end,
                start_byte=start_byte,
                end_byte=end_byte,
                chunk_index=len(chunks),
                chunker_version=self.chunker_version,
            ))
            if end == len(lines):
                break
            start = max(start + 1, end - self.overlap_lines)

        return chunks

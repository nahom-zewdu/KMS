"""Snapshot-scoped persistence for syntax-aware code declarations.

This module deliberately indexes declarations only. Semantic references and
call relationships are separate evidence producers and must not be inferred
from syntax trees here.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from codebase.symbols import CodeSymbolExtractor, SymbolExtraction

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_SOURCE_BYTES = 1_000_000


class CodeSymbolIndexer:
    """Extract and batch-persist declarations for one immutable source snapshot."""

    def __init__(
        self,
        supabase: Any,
        *,
        extractor: CodeSymbolExtractor | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    ) -> None:
        if batch_size < 1 or max_source_bytes < 1:
            raise ValueError("batch_size and max_source_bytes must be positive")
        self.supabase = supabase
        self.extractor = extractor or CodeSymbolExtractor()
        self.batch_size = batch_size
        self.max_source_bytes = max_source_bytes

    def index_file(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
        company_id: str,
        file_path: str,
        source: str,
        source_revision: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Extract one bounded source file and persist its declarations idempotently."""
        source_bytes = source.encode("utf-8")
        if len(source_bytes) > self.max_source_bytes:
            return self._result("oversized", 0, len(source_bytes))

        extraction = self.extractor.extract_file(
            repository_id=repository_id,
            file_path=file_path,
            source=source,
            source_revision=source_revision,
            language=language,
        )
        if extraction is None:
            return self._result("unsupported", 0, len(source_bytes))

        rows = [
            self._row(symbol, snapshot_id=snapshot_id, company_id=company_id)
            for symbol in extraction.symbols
        ]
        written = self._upsert_rows(rows)
        status = "syntax_error" if extraction.has_syntax_errors else "indexed"
        return self._result(status, written, len(source_bytes))

    def index_files(
        self,
        files: Iterable[dict[str, str]],
        *,
        repository_id: str,
        snapshot_id: str,
        company_id: str,
        source_revision: str,
    ) -> dict[str, Any]:
        """Index a deterministic inventory while returning explicit coverage metrics."""
        metrics: dict[str, Any] = {
            "files_seen": 0,
            "files_indexed": 0,
            "files_with_syntax_errors": 0,
            "files_unsupported": 0,
            "files_oversized": 0,
            "symbols_persisted": 0,
            "source_bytes_skipped": 0,
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
                language=item.get("language"),
            )
            if result["status"] == "indexed":
                metrics["files_indexed"] += 1
            elif result["status"] == "syntax_error":
                metrics["files_with_syntax_errors"] += 1
                metrics["files_indexed"] += 1
            elif result["status"] == "oversized":
                metrics["files_oversized"] += 1
                metrics["source_bytes_skipped"] += result["source_bytes"]
            else:
                metrics["files_unsupported"] += 1
            metrics["symbols_persisted"] += result["symbols_persisted"]
        return metrics

    def _upsert_rows(self, rows: list[dict[str, Any]]) -> int:
        """Write bounded idempotent batches; empty declaration sets need no DB call."""
        written = 0
        for offset in range(0, len(rows), self.batch_size):
            batch = rows[offset:offset + self.batch_size]
            response = self.supabase.table("code_symbols").upsert(
                batch,
                on_conflict="snapshot_id,symbol_id",
            ).execute()
            # Supabase/PostgREST may omit representation unless requested. The
            # input batch is the deterministic count validated at publication.
            written += len(batch)
        return written

    @staticmethod
    def _row(symbol, *, snapshot_id: str, company_id: str) -> dict[str, Any]:
        """Add tenant and snapshot ownership to an extractor-owned declaration."""
        return {
            **symbol.to_dict(),
            "snapshot_id": snapshot_id,
            "company_id": company_id,
        }

    @staticmethod
    def _result(status: str, symbols_persisted: int, source_bytes: int) -> dict[str, Any]:
        """Return a uniform per-file coverage record for snapshot validation."""
        return {
            "status": status,
            "symbols_persisted": symbols_persisted,
            "source_bytes": source_bytes,
        }

"""Snapshot-scoped persistence for semantic SCIP occurrences.

SCIP occurrences are compiler/indexer evidence. They are intentionally stored
separately from syntax-derived declarations in :mod:`codebase.symbol_indexer`.
"""

from __future__ import annotations

from typing import Any

from codebase.scip_indexer import ScipIndex


DEFAULT_BATCH_SIZE = 500
DEFAULT_MAX_OCCURRENCES = 1_000_000


class ScipOccurrenceIndexer:
    """Persist normalized SCIP occurrences into one immutable snapshot."""

    def __init__(
        self,
        supabase: Any,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_occurrences: int = DEFAULT_MAX_OCCURRENCES,
    ) -> None:
        if batch_size < 1 or max_occurrences < 1:
            raise ValueError("batch_size and max_occurrences must be positive")
        self.supabase = supabase
        self.batch_size = batch_size
        self.max_occurrences = max_occurrences

    def persist(
        self,
        index: ScipIndex,
        *,
        repository_id: str,
        snapshot_id: str,
        company_id: str,
        source_revision: str,
    ) -> dict[str, int]:
        """Upsert bounded batches after checking the requested revision and scope."""
        if not repository_id or not repository_id.strip():
            raise ValueError("repository_id is required")
        if not snapshot_id or not snapshot_id.strip():
            raise ValueError("snapshot_id is required")
        if not company_id or not company_id.strip() or company_id.strip().lower() == "default":
            raise ValueError("a real company_id is required")
        if not source_revision or not source_revision.strip():
            raise ValueError("source_revision is required")
        if len(index.occurrences) > self.max_occurrences:
            raise ValueError("SCIP occurrence count exceeds the persistence limit")

        rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for occurrence in index.occurrences:
            if occurrence.source_revision != source_revision:
                raise ValueError(
                    "SCIP occurrence source revision does not match the target snapshot"
                )
            if occurrence.occurrence_id in seen_ids:
                raise ValueError("SCIP index contains duplicate occurrence identities")
            seen_ids.add(occurrence.occurrence_id)
            rows.append({
                "repository_id": repository_id,
                "snapshot_id": snapshot_id,
                "company_id": company_id,
                **occurrence.to_dict(),
            })

        if not rows:
            return {
                "occurrences_seen": 0,
                "occurrences_persisted": 0,
                "definitions": 0,
                "references": 0,
                "other_occurrences": 0,
                "files_with_occurrences": 0,
            }

        for offset in range(0, len(rows), self.batch_size):
            batch = rows[offset:offset + self.batch_size]
            self.supabase.table("code_symbol_occurrences").upsert(
                batch,
                on_conflict="snapshot_id,occurrence_id",
            ).execute()

        # Refresh from the database rather than this batch's input count: multiple
        # language-specific SCIP jobs may contribute to the same snapshot.
        self.supabase.rpc(
            "refresh_snapshot_occurrence_validation",
            {"p_snapshot_id": snapshot_id, "p_company_id": company_id},
        ).execute()

        return {
            "occurrences_seen": len(rows),
            "occurrences_persisted": len(rows),
            "definitions": sum(row["role"] == "definition" for row in rows),
            "references": sum(row["role"] == "reference" for row in rows),
            "other_occurrences": sum(row["role"] == "occurrence" for row in rows),
            "files_with_occurrences": len({row["file_path"] for row in rows}),
        }

"""Tenant-scoped semantic symbol navigation over active repository snapshots."""

from __future__ import annotations

from typing import Any


class ScipOccurrenceRetriever:
    """Resolve SCIP definitions and references only from the active snapshot."""

    def __init__(self, supabase: Any, *, max_results: int = 500) -> None:
        if max_results < 1 or max_results > 2000:
            raise ValueError("max_results must be between 1 and 2000")
        self.supabase = supabase
        self.max_results = max_results

    def find_symbol(
        self, *, company_id: str, repository_id: str, symbol: str
    ) -> list[dict[str, Any]]:
        """Return all indexed definitions/references for one exact SCIP symbol."""
        snapshot_id = self._active_snapshot(company_id, repository_id)
        if snapshot_id is None:
            return []
        return self._query(
            company_id=company_id,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            symbol=symbol,
        )

    def find_definitions(
        self, *, company_id: str, repository_id: str, symbol: str
    ) -> list[dict[str, Any]]:
        """Return definition occurrences for an exact SCIP symbol."""
        snapshot_id = self._active_snapshot(company_id, repository_id)
        if snapshot_id is None:
            return []
        return self._query(
            company_id=company_id,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            symbol=symbol,
            role="definition",
        )

    def find_references(
        self, *, company_id: str, repository_id: str, symbol: str
    ) -> list[dict[str, Any]]:
        """Return reference occurrences for an exact SCIP symbol."""
        snapshot_id = self._active_snapshot(company_id, repository_id)
        if snapshot_id is None:
            return []
        return self._query(
            company_id=company_id,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            symbol=symbol,
            roles=("reference", "occurrence"),
        )

    def list_file_occurrences(
        self, *, company_id: str, repository_id: str, file_path: str
    ) -> list[dict[str, Any]]:
        """Return semantic occurrences in source order for one active-snapshot file."""
        self._validate_scope(company_id, repository_id)
        if not file_path or not file_path.strip():
            raise ValueError("file_path is required")
        snapshot_id = self._active_snapshot(company_id, repository_id)
        if snapshot_id is None:
            return []
        query = self._base_query(company_id, repository_id, snapshot_id)
        response = (
            query.eq("file_path", file_path.strip())
            .order("start_byte")
            .limit(self.max_results)
            .execute()
        )
        return response.data or []

    def _query(
        self,
        *,
        company_id: str,
        repository_id: str,
        snapshot_id: str,
        symbol: str,
        role: str | None = None,
        roles: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_scope(company_id, repository_id)
        if not symbol or not symbol.strip():
            raise ValueError("symbol is required")
        query = self._base_query(company_id, repository_id, snapshot_id).eq(
            "symbol", symbol.strip()
        )
        if role is not None:
            query = query.eq("role", role)
        if roles is not None:
            query = query.in_("role", list(roles))
        response = (
            query.order("file_path")
            .order("start_byte")
            .limit(self.max_results)
            .execute()
        )
        return response.data or []

    def _base_query(self, company_id: str, repository_id: str, snapshot_id: str):
        """Apply all ownership predicates before querying semantic occurrences."""
        return (
            self.supabase.table("code_symbol_occurrences")
            .select("*")
            .eq("company_id", company_id)
            .eq("repository_id", repository_id)
            .eq("snapshot_id", snapshot_id)
        )

    def _active_snapshot(self, company_id: str, repository_id: str) -> str | None:
        """Resolve the active pointer using both tenant and physical repository IDs."""
        self._validate_scope(company_id, repository_id)
        response = (
            self.supabase.table("repositories")
            .select("active_snapshot_id")
            .eq("id", repository_id)
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0].get("active_snapshot_id") if rows else None

    @staticmethod
    def _validate_scope(company_id: str, repository_id: str) -> None:
        """Reject absent or placeholder tenant scope before issuing database queries."""
        if not company_id or not company_id.strip() or company_id.strip().lower() == "default":
            raise ValueError("a real company_id is required")
        if not repository_id or not repository_id.strip():
            raise ValueError("repository_id is required")

"""Tenant-scoped symbol navigation over the active repository snapshot."""

from __future__ import annotations

from typing import Any


class CodeSymbolRetriever:
    """Resolve declarations only from a repository's currently published snapshot."""

    def __init__(self, supabase: Any, *, max_results: int = 100) -> None:
        if max_results < 1 or max_results > 500:
            raise ValueError("max_results must be between 1 and 500")
        self.supabase = supabase
        self.max_results = max_results

    def find_qualified_name(
        self, *, company_id: str, repository_id: str, qualified_name: str
    ) -> list[dict[str, Any]]:
        """Return exact qualified-name matches from the active snapshot."""
        self._validate_scope(company_id, repository_id)
        if not qualified_name or not qualified_name.strip():
            raise ValueError("qualified_name is required")
        snapshot_id = self._active_snapshot(company_id, repository_id)
        if snapshot_id is None:
            return []
        response = (
            self.supabase.table("code_symbols")
            .select("*")
            .eq("company_id", company_id)
            .eq("repository_id", repository_id)
            .eq("snapshot_id", snapshot_id)
            .eq("qualified_name", qualified_name.strip())
            .order("start_byte")
            .limit(self.max_results)
            .execute()
        )
        return response.data or []

    def list_file_symbols(
        self, *, company_id: str, repository_id: str, file_path: str
    ) -> list[dict[str, Any]]:
        """Return declarations in source order for one active-snapshot file."""
        self._validate_scope(company_id, repository_id)
        if not file_path or not file_path.strip():
            raise ValueError("file_path is required")
        snapshot_id = self._active_snapshot(company_id, repository_id)
        if snapshot_id is None:
            return []
        response = (
            self.supabase.table("code_symbols")
            .select("*")
            .eq("company_id", company_id)
            .eq("repository_id", repository_id)
            .eq("snapshot_id", snapshot_id)
            .eq("file_path", file_path.strip())
            .order("start_byte")
            .limit(self.max_results)
            .execute()
        )
        return response.data or []

    def search_names(
        self, *, company_id: str, repository_id: str, term: str
    ) -> list[dict[str, Any]]:
        """Search declaration names within one active snapshot and tenant."""
        self._validate_scope(company_id, repository_id)
        normalized = (term or "").strip()
        if not normalized:
            raise ValueError("term is required")
        snapshot_id = self._active_snapshot(company_id, repository_id)
        if snapshot_id is None:
            return []
        escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        response = (
            self.supabase.table("code_symbols")
            .select("*")
            .eq("company_id", company_id)
            .eq("repository_id", repository_id)
            .eq("snapshot_id", snapshot_id)
            .ilike("qualified_name", f"%{escaped}%")
            .order("file_path")
            .order("start_byte")
            .limit(self.max_results)
            .execute()
        )
        return response.data or []

    def _active_snapshot(self, company_id: str, repository_id: str) -> str | None:
        """Resolve the active pointer using both tenant and physical repository IDs."""
        response = (
            self.supabase.table("repositories")
            .select("active_snapshot_id")
            .eq("id", repository_id)
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        return rows[0].get("active_snapshot_id")

    @staticmethod
    def _validate_scope(company_id: str, repository_id: str) -> None:
        """Reject absent or placeholder tenant scope before issuing database queries."""
        if not company_id or not company_id.strip() or company_id.strip().lower() == "default":
            raise ValueError("a real company_id is required")
        if not repository_id or not repository_id.strip():
            raise ValueError("repository_id is required")

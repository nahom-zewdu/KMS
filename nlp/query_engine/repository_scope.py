"""Trusted company-to-repository scope resolution for planned queries.

A repository ID from a request is only a selector. It becomes trusted only after
it is resolved against the authenticated company in the repositories table and
confirmed to have a published snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RepositoryScopeResolution:
    """One verified active repository, or an explicit reason resolution failed."""

    repository_id: str | None
    full_name: str | None
    reason: str | None

    @property
    def resolved(self) -> bool:
        """Whether exactly one company-owned active repository was verified."""
        return self.repository_id is not None and self.full_name is not None and self.reason is None


class TrustedRepositoryScopeResolver:
    """Resolve one active repository without trusting caller-supplied ownership."""

    def __init__(self, supabase: Any) -> None:
        self.supabase = supabase

    def resolve(
        self,
        company_id: str,
        repository_id: str | None = None,
    ) -> RepositoryScopeResolution:
        """Resolve a requested repository or the sole active repository for a company.

        The company ID must come from the authenticated job boundary. A supplied
        repository ID is never accepted by itself: both IDs are applied as database
        predicates, and the returned row is checked again before it is trusted.
        Without an explicit selector, the query is bounded to two active rows so
        multiple repositories are detected rather than silently choosing one.
        """
        company = (company_id or "").strip()
        if not company or company.casefold() == "default":
            raise ValueError("a real company_id is required")

        requested_repository = (repository_id or "").strip() or None
        query = (
            self.supabase.table("repositories")
            .select("id,company_id,full_name,active_snapshot_id")
            .eq("company_id", company)
        )
        if requested_repository:
            query = query.eq("id", requested_repository)
        else:
            query = query.not_.is_("active_snapshot_id", "null")

        rows = getattr(query.limit(2).execute(), "data", None) or []
        valid_rows = [
            row for row in rows
            if isinstance(row, dict)
            and str(row.get("company_id") or "") == company
            and str(row.get("id") or "").strip()
            and str(row.get("full_name") or "").strip()
            and row.get("active_snapshot_id") is not None
        ]

        if not valid_rows:
            return RepositoryScopeResolution(
                None, None,
                "repository_not_found_for_company" if requested_repository
                else "no_active_repository",
            )
        if len(valid_rows) != 1:
            return RepositoryScopeResolution(None, None, "multiple_active_repositories")

        row = valid_rows[0]
        resolved_id = str(row["id"]).strip()
        if requested_repository and resolved_id != requested_repository:
            return RepositoryScopeResolution(None, None, "repository_scope_mismatch")

        return RepositoryScopeResolution(
            repository_id=resolved_id,
            full_name=str(row["full_name"]).strip(),
            reason=None,
        )

"""Company-scoped evidence extraction for Ramp intelligence.

The extractor owns facts. It does not decide what an engineer should learn.
Ramp candidates consume the normalized evidence produced here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from supabase import Client

from .models import Evidence, ImplementationSurface


class RampEvidenceStore:
    """Read the existing KMS knowledge model for one company."""

    def __init__(self, supabase: Client):
        self.supabase = supabase

    def implementation_surfaces(self, company_id: str) -> List[ImplementationSurface]:
        """Return indexed files for a company as normalized implementation surfaces."""
        if not company_id:
            return []
        try:
            response = (
                self.supabase.table("codebase_files")
                .select(
                    "id, repository_id, file_path, module_path, language, file_name, "
                    "last_author, last_commit_sha, importance_score, metadata"
                )
                .eq("company_id", company_id)
                .limit(5000)
                .execute()
            )
        except Exception:
            return []

        result: List[ImplementationSurface] = []
        for row in getattr(response, "data", []) or []:
            path = str(row.get("file_path") or "").strip()
            if not path:
                continue
            result.append(
                ImplementationSurface(
                    ref=str(row.get("id") or f"{row.get('repository_id')}:{path}"),
                    path=path,
                    repository_id=row.get("repository_id"),
                    module_path=row.get("module_path"),
                    language=row.get("language"),
                    importance=float(row.get("importance_score") or 0.0),
                    last_author=row.get("last_author"),
                    last_commit_sha=row.get("last_commit_sha"),
                    metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
                )
            )
        return sorted(result, key=lambda item: (-item.importance, item.path))

    def module_records(self, company_id: str) -> List[Dict[str, Any]]:
        """Return company-scoped module records without interpreting their meaning."""
        if not company_id:
            return []
        try:
            response = (
                self.supabase.table("codebase_modules")
                .select(
                    "id, repository_id, module_path, module_name, inferred_type, "
                    "description, importance_score, metadata"
                )
                .eq("company_id", company_id)
                .limit(1000)
                .execute()
            )
            return [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]
        except Exception:
            return []

    def ownership(self, company_id: str) -> List[Dict[str, Any]]:
        """Return ownership edges available in the existing knowledge graph."""
        if not company_id:
            return []
        try:
            response = (
                self.supabase.table("edges")
                .select("source_id, target_id, type, metadata, confidence")
                .eq("company_id", company_id)
                .eq("type", "OWNS")
                .limit(5000)
                .execute()
            )
            return [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]
        except Exception:
            return []

    def github_history(self, company_id: str) -> List[Dict[str, Any]]:
        """Return recent GitHub-derived raw knowledge for corroboration."""
        if not company_id:
            return []
        try:
            response = (
                self.supabase.table("raw_data")
                .select("record_id, event_id, source, content, created_at")
                .eq("company_id", company_id)
                .eq("source", "github")
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            )
            return [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]
        except Exception:
            return []

    def evidence_for_surface(self, surface: ImplementationSurface) -> Evidence:
        """Convert one indexed implementation surface into a traceable evidence item."""
        return Evidence(
            ref=surface.path,
            source="codebase_files",
            kind="implementation_surface",
            strength="direct",
            detail="Company-scoped codebase index record.",
            repository_id=surface.repository_id,
            module_path=surface.module_path,
            metadata={
                "importance_score": surface.importance,
                "language": surface.language,
                "last_author": surface.last_author,
                "last_commit_sha": surface.last_commit_sha,
            },
        )

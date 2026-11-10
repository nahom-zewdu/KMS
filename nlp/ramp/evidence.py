"""Company-scoped evidence extraction for Ramp intelligence.

The extractor owns facts. It does not decide what an engineer should learn.
Ramp candidates consume the normalized evidence produced here.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from supabase import Client

from .models import Evidence, ImplementationSurface


class RampEvidenceRetrievalError(RuntimeError):
    """A database read failed while collecting evidence for Ramp generation."""

    def __init__(self, source: str, operation: str, error_type: str):
        self.source = source
        self.operation = operation
        self.error_type = error_type
        super().__init__(
            f"Ramp evidence retrieval failed: source={source}, operation={operation}"
        )


class RampEvidenceStore:
    """Read the existing KMS knowledge model for one company."""

    def __init__(self, supabase: Client):
        self.supabase = supabase

    def implementation_surfaces(self, company_id: str) -> List[ImplementationSurface]:
        """Return indexed files for a company as normalized implementation surfaces."""
        self._require_company_id(company_id)
        repository_ids = self._repository_ids(company_id)
        if not repository_ids:
            return []
        response = self._retrieve(
            "codebase_files",
            "list implementation surfaces",
            lambda: (
                self.supabase.table("codebase_files")
                .select(
                    "id, repository_id, file_path, module_path, language, file_name, "
                    "last_author, last_commit_sha, importance_score, metadata"
                )
                .in_("repository_id", repository_ids)
                .limit(5000)
                .execute()
            ),
        )

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
        self._require_company_id(company_id)
        repository_ids = self._repository_ids(company_id)
        if not repository_ids:
            return []
        response = self._retrieve(
            "codebase_modules",
            "list module records",
            lambda: (
                self.supabase.table("codebase_modules")
                .select(
                    "id, repository_id, module_path, module_name, inferred_type, "
                    "description, importance_score, metadata"
                )
                .in_("repository_id", repository_ids)
                .limit(1000)
                .execute()
            ),
        )
        return [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]

    def _repository_ids(self, company_id: str) -> List[str]:
        response = self._retrieve(
            "repositories",
            "list company repositories",
            lambda: (
                self.supabase.table("repositories")
                .select("id")
                .eq("company_id", company_id)
                .execute()
            ),
        )
        return [row["id"] for row in (getattr(response, "data", []) or []) if row.get("id")]

    def ownership(self, company_id: str) -> List[Dict[str, Any]]:
        """Return ownership edges available in the existing knowledge graph."""
        self._require_company_id(company_id)
        response = self._retrieve(
            "edges",
            "list ownership relationships",
            lambda: (
                self.supabase.table("edges")
                .select("source_id, target_id, type, metadata, confidence")
                .eq("company_id", company_id)
                .eq("type", "OWNS")
                .limit(5000)
                .execute()
            ),
        )
        return [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]

    def implementation_relationships(self, company_id: str) -> List[Evidence]:
        """Return graph relationships whose endpoints resolve to FILE entities.

        PART_OF and OWNS are intentionally excluded: they establish containment
        or ownership, not behavioral control/data flow between implementation surfaces.
        """
        self._require_company_id(company_id)
        entities = self._retrieve(
            "entities",
            "list file entities",
            lambda: (
                self.supabase.table("entities")
                .select("id, metadata")
                .eq("company_id", company_id)
                .eq("type", "FILE")
                .limit(10000)
                .execute()
            ),
        )
        edges = self._retrieve(
            "edges",
            "list implementation relationships",
            lambda: (
                self.supabase.table("edges")
                .select("id, source_id, target_id, type, confidence")
                .eq("company_id", company_id)
                .limit(20000)
                .execute()
            ),
        )

        file_paths: Dict[str, str] = {}
        for row in getattr(entities, "data", []) or []:
            if not isinstance(row, dict):
                continue
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            path = str(metadata.get("file_path") or "").strip()
            if path and row.get("id"):
                file_paths[str(row["id"])] = path

        result: List[Evidence] = []
        for edge in getattr(edges, "data", []) or []:
            if not isinstance(edge, dict):
                continue
            relation_type = str(edge.get("type") or "").upper()
            source_path = file_paths.get(str(edge.get("source_id") or ""))
            target_path = file_paths.get(str(edge.get("target_id") or ""))
            if relation_type in {"PART_OF", "OWNS"} or not source_path or not target_path:
                continue
            try:
                confidence = float(edge.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            strength = "direct" if confidence >= 0.8 else "derived" if confidence >= 0.6 else "inferred"
            result.append(
                Evidence(
                    ref=f"edge:{edge.get('id')}",
                    source="edges",
                    kind="implementation_relation",
                    strength=strength,
                    detail=f"{source_path} --{relation_type}--> {target_path}",
                    metadata={
                        "source_ref": source_path,
                        "target_ref": target_path,
                        "relation_type": relation_type,
                        "confidence": confidence,
                    },
                )
            )
        return result

    def github_history(self, company_id: str) -> List[Dict[str, Any]]:
        """Return recent GitHub-derived raw knowledge for corroboration."""
        self._require_company_id(company_id)
        response = self._retrieve(
            "raw_data",
            "list GitHub history",
            lambda: (
                self.supabase.table("raw_data")
                .select("record_id, event_id, source, content, created_at")
                .eq("company_id", company_id)
                .eq("source", "github")
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            ),
        )
        return [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]

    @staticmethod
    def _require_company_id(company_id: str) -> None:
        if not company_id or not company_id.strip() or company_id.strip().lower() == "default":
            raise ValueError("A real company_id is required for Ramp evidence")

    @staticmethod
    def _retrieve(source: str, operation: str, request: Callable[[], Any]) -> Any:
        try:
            return request()
        except Exception as exc:
            raise RampEvidenceRetrievalError(
                source=source,
                operation=operation,
                error_type=type(exc).__name__,
            ) from None

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

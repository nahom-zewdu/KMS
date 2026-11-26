"""Conservative resolution from source-language names to exact SCIP symbols.

This module is deliberately a pure orchestration layer over existing scoped
retrievers. It never manufactures SCIP identifiers or performs database writes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from codebase.scip_occurrence_retriever import ScipOccurrenceRetriever
from codebase.symbol_retriever import CodeSymbolRetriever

from .query_plan import (
    QueryIntent,
    QueryPlan,
    ResolvedScipSymbol,
    SymbolResolutionMethod,
)


class _DeclarationReader(Protocol):
    def find_qualified_name(
        self, *, company_id: str, repository_id: str, qualified_name: str
    ) -> list[dict[str, Any]]: ...

    def search_names(
        self, *, company_id: str, repository_id: str, term: str
    ) -> list[dict[str, Any]]: ...


class _OccurrenceReader(Protocol):
    def list_file_occurrences(
        self, *, company_id: str, repository_id: str, file_path: str
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class SymbolResolutionResult:
    """A resolved plan, or a stable reason explaining why resolution abstained."""

    plan: QueryPlan | None
    reason: str | None

    @property
    def resolved(self) -> bool:
        """Whether an exact SCIP symbol was attached to the returned plan."""
        return self.plan is not None and self.plan.resolved_symbol is not None


class ConservativeScipSymbolResolver:
    """Resolve one explicit source declaration to one exact active-snapshot SCIP symbol."""

    def __init__(
        self,
        declarations: _DeclarationReader | CodeSymbolRetriever,
        occurrences: _OccurrenceReader | ScipOccurrenceRetriever,
    ) -> None:
        self.declarations = declarations
        self.occurrences = occurrences

    def resolve(self, plan: QueryPlan) -> SymbolResolutionResult:
        """Return a copied plan with exact SCIP provenance, or an explicit abstention."""
        if not isinstance(plan, QueryPlan):
            raise ValueError("plan must be a QueryPlan")
        if plan.intent is not QueryIntent.CALL_SITE_NAVIGATION:
            return SymbolResolutionResult(None, "not_call_site_query")
        if plan.disposition.value != "ready":
            return SymbolResolutionResult(None, "plan_not_ready")

        company_id = plan.scope.company_id
        repository_id = plan.scope.repository_id
        if not repository_id:
            return SymbolResolutionResult(None, "repository_scope_required")

        if plan.qualified_names:
            names = self._unique(plan.qualified_names)
            method = SymbolResolutionMethod.EXACT_QUALIFIED_NAME
        else:
            names = self._unique(plan.identifiers)
            method = SymbolResolutionMethod.EXACT_IDENTIFIER

        if not names:
            return SymbolResolutionResult(None, "no_explicit_symbol_candidate")
        if len(names) != 1:
            return SymbolResolutionResult(None, "multiple_symbol_candidates")

        source_value = names[0]
        if method is SymbolResolutionMethod.EXACT_QUALIFIED_NAME:
            rows = self.declarations.find_qualified_name(
                company_id=company_id,
                repository_id=repository_id,
                qualified_name=source_value,
            )
            exact_rows = [
                row for row in rows
                if row.get("qualified_name") == source_value
            ]
        else:
            rows = self.declarations.search_names(
                company_id=company_id,
                repository_id=repository_id,
                term=source_value,
            )
            exact_rows = [
                row for row in rows
                if row.get("name") == source_value
                or row.get("qualified_name") == source_value
            ]

        declarations = self._unique_rows(exact_rows)
        if not declarations:
            return SymbolResolutionResult(None, "declaration_not_found")
        if len(declarations) != 1:
            return SymbolResolutionResult(None, "ambiguous_declaration")

        declaration = declarations[0]
        file_path = declaration.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            return SymbolResolutionResult(None, "source_range_mismatch")

        occurrences = self.occurrences.list_file_occurrences(
            company_id=company_id,
            repository_id=repository_id,
            file_path=file_path,
        )
        if not occurrences:
            return SymbolResolutionResult(None, "definition_occurrence_not_found")

        matching_definitions = [
            occurrence for occurrence in occurrences
            if occurrence.get("role") == "definition"
            and occurrence.get("file_path") == file_path
            and self._same_source_range(declaration, occurrence)
            and occurrence.get("snapshot_id") == declaration.get("snapshot_id")
        ]
        symbols = self._unique(
            occurrence.get("symbol", "")
            for occurrence in matching_definitions
            if isinstance(occurrence.get("symbol"), str)
        )
        if not symbols:
            return SymbolResolutionResult(None, "definition_occurrence_not_found")
        if len(symbols) != 1:
            return SymbolResolutionResult(None, "ambiguous_scip_definition")

        resolved = ResolvedScipSymbol(
            symbol=symbols[0],
            method=method,
            source_value=source_value,
        )
        return SymbolResolutionResult(
            replace(plan, resolved_symbol=resolved),
            None,
        )

    @staticmethod
    def _same_source_range(
        declaration: dict[str, Any], occurrence: dict[str, Any]
    ) -> bool:
        """Require exact file-relative byte and line ranges, not approximate overlap."""
        fields = ("start_byte", "end_byte", "start_line", "end_line")
        return all(
            declaration.get(field) is not None
            and occurrence.get(field) is not None
            and declaration.get(field) == occurrence.get(field)
            for field in fields
        )

    @staticmethod
    def _unique(values) -> tuple[str, ...]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if isinstance(value, str):
                normalized = value.strip()
                key = normalized.casefold()
                if normalized and key not in seen:
                    seen.add(key)
                    result.append(normalized)
        return tuple(result)

    @classmethod
    def _unique_rows(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse duplicate copies of the same persisted declaration row."""
        unique: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in rows:
            key = (
                row.get("id"),
                row.get("symbol_id"),
                row.get("snapshot_id"),
                row.get("file_path"),
                row.get("start_byte"),
                row.get("end_byte"),
            )
            unique.setdefault(key, row)
        return list(unique.values())

"""Bounded, plan-driven evidence gathering over existing KRT-03 retrievers.

This layer performs no classification, symbol guessing, synthesis, or database
writes. It forwards trusted scope to existing retrievers and validates returned
provenance before exposing evidence to later query stages.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from codebase.scip_occurrence_retriever import ScipOccurrenceRetriever
from codebase.source_chunk_retriever import SourceChunkRetriever
from codebase.symbol_retriever import CodeSymbolRetriever

from .evidence import EvidenceCandidate
from .query_plan import PlanDisposition, QueryIntent, QueryPlan


MAX_EVIDENCE_RESULTS = 20
MAX_EVIDENCE_CONTENT_CHARS = 12_000


class _SourceReader(Protocol):
    def retrieve(self, *, company_id: str, repository_id: str, terms: list[str]) -> list[EvidenceCandidate]: ...


class _SymbolReader(Protocol):
    def find_qualified_name(self, *, company_id: str, repository_id: str, qualified_name: str) -> list[dict[str, Any]]: ...
    def search_names(self, *, company_id: str, repository_id: str, term: str) -> list[dict[str, Any]]: ...
    def list_file_symbols(self, *, company_id: str, repository_id: str, file_path: str) -> list[dict[str, Any]]: ...


class _OccurrenceReader(Protocol):
    def find_references(self, *, company_id: str, repository_id: str, symbol: str) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class EvidenceGatheringResult:
    """Evidence returned for one plan, or an explicit reason no retrieval ran."""

    plan: QueryPlan
    evidence: tuple[EvidenceCandidate, ...] = ()
    reason: str | None = None

    @property
    def gathered(self) -> bool:
        """Whether at least one validated evidence item was returned."""
        return bool(self.evidence)


class BoundedEvidenceGatherer:
    """Route ready plans to a single existing retriever with strict output bounds."""

    def __init__(
        self,
        *,
        source_chunks: _SourceReader | SourceChunkRetriever,
        symbols: _SymbolReader | CodeSymbolRetriever,
        occurrences: _OccurrenceReader | ScipOccurrenceRetriever,
        max_results: int = 8,
        max_content_chars: int = MAX_EVIDENCE_CONTENT_CHARS,
    ) -> None:
        if not 1 <= max_results <= MAX_EVIDENCE_RESULTS:
            raise ValueError(f"max_results must be between 1 and {MAX_EVIDENCE_RESULTS}")
        if not 1 <= max_content_chars <= MAX_EVIDENCE_CONTENT_CHARS:
            raise ValueError("max_content_chars is outside the supported bound")
        self.source_chunks = source_chunks
        self.symbols = symbols
        self.occurrences = occurrences
        self.max_results = max_results
        self.max_content_chars = max_content_chars

    def gather(self, plan: QueryPlan) -> EvidenceGatheringResult:
        """Gather evidence only for supported, ready plans with repository scope."""
        if not isinstance(plan, QueryPlan):
            raise ValueError("plan must be a QueryPlan")
        if plan.disposition is not PlanDisposition.READY:
            return EvidenceGatheringResult(plan, reason="plan_not_ready")
        if plan.intent in {
            QueryIntent.COURTESY, QueryIntent.FOLLOW_UP,
            QueryIntent.CLARIFICATION, QueryIntent.UNSUPPORTED,
        }:
            return EvidenceGatheringResult(plan, reason="intent_does_not_retrieve")
        if plan.intent is QueryIntent.STRUCTURED_FACT:
            return EvidenceGatheringResult(plan, reason="structured_retrieval_not_supported")
        if plan.constraints.time_from is not None or plan.constraints.time_to is not None:
            return EvidenceGatheringResult(plan, reason="time_constraints_not_supported")
        repository_id = plan.scope.repository_id
        if not repository_id:
            return EvidenceGatheringResult(plan, reason="repository_scope_required")

        if plan.intent is QueryIntent.PASSAGE_RETRIEVAL:
            return self._passages(plan, repository_id)
        if plan.intent is QueryIntent.DECLARATION_DISCOVERY:
            return self._declarations(plan, repository_id)
        if plan.intent is QueryIntent.CALL_SITE_NAVIGATION:
            return self._call_sites(plan, repository_id)
        return EvidenceGatheringResult(plan, reason="intent_not_supported")

    def _passages(self, plan: QueryPlan, repository_id: str) -> EvidenceGatheringResult:
        if not plan.terms:
            return EvidenceGatheringResult(plan, reason="retrieval_terms_required")
        rows = self.source_chunks.retrieve(
            company_id=plan.scope.company_id,
            repository_id=repository_id,
            terms=list(plan.terms[:20]),
        )
        evidence = [
            item for item in rows
            if isinstance(item, EvidenceCandidate)
            and item.company_id == plan.scope.company_id
            and item.repository_id == repository_id
            and item.evidence_type == "code_chunk"
            and self._revision_matches(plan, item.source_revision)
        ]
        return self._result(plan, evidence, "no_matching_evidence")

    def _declarations(self, plan: QueryPlan, repository_id: str) -> EvidenceGatheringResult:
        kwargs = {"company_id": plan.scope.company_id, "repository_id": repository_id}
        if len(plan.file_paths) > 1:
            return EvidenceGatheringResult(plan, reason="multiple_file_paths_require_clarification")
        if plan.file_paths:
            rows = self.symbols.list_file_symbols(**kwargs, file_path=plan.file_paths[0])
        elif plan.qualified_names:
            if len(plan.qualified_names) != 1:
                return EvidenceGatheringResult(plan, reason="multiple_symbol_candidates")
            name = plan.qualified_names[0]
            rows = self.symbols.find_qualified_name(**kwargs, qualified_name=name)
            rows = [row for row in rows if row.get("qualified_name") == name]
        elif plan.identifiers:
            if len(plan.identifiers) != 1:
                return EvidenceGatheringResult(plan, reason="multiple_symbol_candidates")
            name = plan.identifiers[0]
            rows = self.symbols.search_names(**kwargs, term=name)
            rows = [row for row in rows if row.get("name") == name or row.get("qualified_name") == name]
        else:
            return EvidenceGatheringResult(plan, reason="declaration_target_required")

        # A bare identifier can match declarations in several files. Returning
        # all matches as ordinary evidence invites synthesis to choose one without
        # a user-provided disambiguator. Collapse duplicate persisted copies, then
        # fail closed when more than one distinct declaration remains.
        unique_rows: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in rows:
            identity = (
                row.get("symbol_id") or row.get("id"),
                row.get("snapshot_id"),
                row.get("file_path"),
                row.get("start_byte"),
                row.get("end_byte"),
                row.get("qualified_name"),
            )
            unique_rows.setdefault(identity, row)
        rows = list(unique_rows.values())
        if len(rows) > 1:
            return EvidenceGatheringResult(plan, reason="ambiguous_declaration")

        evidence = []
        for row in rows:
            candidate = self._symbol_candidate(plan, repository_id, row, len(evidence) + 1)
            if candidate is not None:
                evidence.append(candidate)
                if len(evidence) >= self.max_results:
                    break
        return self._result(plan, evidence, "declaration_not_found")

    def _call_sites(self, plan: QueryPlan, repository_id: str) -> EvidenceGatheringResult:
        resolved = plan.resolved_symbol
        if resolved is None:
            return EvidenceGatheringResult(plan, reason="resolved_symbol_required")
        rows = self.occurrences.find_references(
            company_id=plan.scope.company_id,
            repository_id=repository_id,
            symbol=resolved.symbol,
        )
        evidence = []
        for row in rows:
            if row.get("role") not in {"reference", "occurrence"}:
                continue
            candidate = self._occurrence_candidate(plan, repository_id, row, len(evidence) + 1)
            if candidate is not None:
                evidence.append(candidate)
                if len(evidence) >= self.max_results:
                    break
        return self._result(plan, evidence, "call_sites_not_found")

    def _symbol_candidate(
        self, plan: QueryPlan, repository_id: str, row: dict[str, Any], rank: int
    ) -> EvidenceCandidate | None:
        required = ("snapshot_id", "source_revision", "file_path", "content_hash",
                    "start_line", "end_line", "start_byte", "end_byte")
        if any(row.get(key) is None for key in required):
            return None
        if not self._row_scope_matches(plan, repository_id, row):
            return None
        if not self._revision_matches(plan, row.get("source_revision")):
            return None
        if plan.file_paths and row.get("file_path") != plan.file_paths[0]:
            return None
        name = str(row.get("qualified_name") or row.get("name") or "")
        if not name:
            return None
        content = f"{row.get('kind', 'symbol')} {name}"[:self.max_content_chars]
        return EvidenceCandidate(
            company_id=plan.scope.company_id, evidence_type="symbol",
            source="code-symbols", record_id=str(row.get("symbol_id") or name),
            content=content, retriever="code-symbol-retriever", rank=rank,
            repository_id=repository_id, snapshot_id=str(row["snapshot_id"]),
            source_revision=str(row["source_revision"]), file_path=str(row["file_path"]),
            content_hash=str(row["content_hash"]), start_line=int(row["start_line"]),
            end_line=int(row["end_line"]), start_byte=int(row["start_byte"]),
            end_byte=int(row["end_byte"]),
        )

    def _occurrence_candidate(
        self, plan: QueryPlan, repository_id: str, row: dict[str, Any], rank: int
    ) -> EvidenceCandidate | None:
        required = ("snapshot_id", "source_revision", "file_path", "content_hash",
                    "start_line", "end_line", "start_byte", "end_byte", "symbol")
        if any(row.get(key) is None for key in required):
            return None
        if not self._row_scope_matches(plan, repository_id, row):
            return None
        if not self._revision_matches(plan, row.get("source_revision")):
            return None
        symbol = str(row["symbol"])
        content = f"SCIP {row['role']}: {symbol} at {row['file_path']}"[:self.max_content_chars]
        return EvidenceCandidate(
            company_id=plan.scope.company_id, evidence_type="occurrence",
            source="scip-occurrences", record_id=str(row.get("occurrence_id") or symbol),
            content=content, retriever="scip-occurrence-retriever", rank=rank,
            repository_id=repository_id, snapshot_id=str(row["snapshot_id"]),
            source_revision=str(row["source_revision"]), file_path=str(row["file_path"]),
            content_hash=str(row["content_hash"]), start_line=int(row["start_line"]),
            end_line=int(row["end_line"]), start_byte=int(row["start_byte"]),
            end_byte=int(row["end_byte"]),
            metadata={"role": row["role"], "symbol": symbol},
        )

    @staticmethod
    def _row_scope_matches(
        plan: QueryPlan, repository_id: str, row: dict[str, Any]
    ) -> bool:
        """Require returned database rows to agree with the trusted plan scope."""
        return (
            row.get("company_id") == plan.scope.company_id
            and row.get("repository_id") == repository_id
        )

    @staticmethod
    def _revision_matches(plan: QueryPlan, revision: Any) -> bool:
        expected = plan.constraints.source_revision
        return expected is None or revision == expected

    def _result(
        self, plan: QueryPlan, candidates: list[EvidenceCandidate], empty_reason: str
    ) -> EvidenceGatheringResult:
        bounded = tuple(
            replace(item, content=item.content[:self.max_content_chars])
            for item in candidates[:self.max_results]
        )
        return EvidenceGatheringResult(plan, bounded, None if bounded else empty_reason)

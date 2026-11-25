"""Deterministic task-aware routing across code retrieval backends.

The router does not infer user intent or blend incomparable retriever scores.
Call-site navigation accepts an exact SCIP symbol resolved by an upstream
planner; lexical passage retrieval is the explicit fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from codebase.scip_occurrence_retriever import ScipOccurrenceRetriever
from codebase.source_chunk_retriever import SourceChunkRetriever
from .code_lexical import CodeLexicalRetriever
from .evidence import EvidenceCandidate


class RetrievalTask(str, Enum):
    """Supported retrieval intents supplied explicitly by the caller."""

    DECLARATION_DISCOVERY = "declaration_discovery"
    CALL_SITE_NAVIGATION = "call_site_navigation"
    PASSAGE_RETRIEVAL = "passage_retrieval"


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    """Bounded retrieval input with trusted tenant/repository scope."""

    task: RetrievalTask
    company_id: str
    repository_id: str
    terms: tuple[str, ...] = ()
    file_paths: tuple[str, ...] = ()
    qualified_names: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    scip_symbol: str | None = None

    def __post_init__(self) -> None:
        if not self.company_id or not self.company_id.strip() or self.company_id.strip().lower() == "default":
            raise ValueError("a real company_id is required")
        if not self.repository_id or not self.repository_id.strip():
            raise ValueError("repository_id is required")
        if not isinstance(self.task, RetrievalTask):
            raise ValueError("task must be a RetrievalTask")


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Candidates and transparent routing metadata; no cross-retriever scoring."""

    task: RetrievalTask
    strategy: str
    candidates: tuple[EvidenceCandidate, ...]
    fallback_reason: str | None = None


class TaskAwareRetrievalRouter:
    """Route explicit retrieval tasks without automatic intent classification."""

    def __init__(
        self,
        *,
        declarations: CodeLexicalRetriever,
        occurrences: ScipOccurrenceRetriever,
        passages: SourceChunkRetriever,
    ) -> None:
        self.declarations = declarations
        self.occurrences = occurrences
        self.passages = passages

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Execute exactly one task-specific strategy and preserve its ranking."""
        scope = {
            "company_id": request.company_id,
            "repository_id": request.repository_id,
        }

        if request.task is RetrievalTask.DECLARATION_DISCOVERY:
            candidates = self.declarations.retrieve(
                **scope,
                file_paths=request.file_paths,
                qualified_names=request.qualified_names,
                identifiers=request.identifiers or request.terms,
            )
            return RetrievalResult(
                task=request.task,
                strategy="code-symbol-lexical",
                candidates=tuple(candidates),
            )

        if request.task is RetrievalTask.PASSAGE_RETRIEVAL:
            candidates = self.passages.retrieve(**scope, terms=list(request.terms))
            return RetrievalResult(
                task=request.task,
                strategy="source-chunk-lexical",
                candidates=tuple(candidates),
            )

        # SCIP symbols are opaque compiler identifiers. Never guess one from
        # natural-language terms or silently treat a textual match as semantic.
        symbol = (request.scip_symbol or "").strip()
        if symbol:
            rows = self.occurrences.find_references(**scope, symbol=symbol)
            if rows:
                candidates = tuple(
                    self._occurrence_candidate(
                        row,
                        company_id=request.company_id,
                        repository_id=request.repository_id,
                        rank=index,
                    )
                    for index, row in enumerate(rows, start=1)
                )
                return RetrievalResult(
                    task=request.task,
                    strategy="scip-references",
                    candidates=candidates,
                )
            fallback_reason = "no_active_snapshot_references_for_exact_scip_symbol"
        else:
            fallback_reason = "exact_scip_symbol_not_provided"

        fallback = self.passages.retrieve(**scope, terms=list(request.terms))
        return RetrievalResult(
            task=request.task,
            strategy="source-chunk-lexical-fallback",
            candidates=tuple(fallback),
            fallback_reason=fallback_reason,
        )

    @staticmethod
    def _occurrence_candidate(
        row: dict,
        *,
        company_id: str,
        repository_id: str,
        rank: int,
    ) -> EvidenceCandidate:
        """Adapt a persisted SCIP occurrence without fabricating source text."""
        return EvidenceCandidate(
            company_id=company_id,
            evidence_type="occurrence",
            source="scip",
            record_id=str(row["occurrence_id"]),
            content=str(row["symbol"]),
            retriever="scip-occurrence",
            rank=rank,
            repository_id=repository_id,
            snapshot_id=str(row["snapshot_id"]),
            source_revision=str(row["source_revision"]),
            file_path=str(row["file_path"]),
            content_hash=str(row["content_hash"]),
            start_line=int(row["start_line"]),
            end_line=int(row["end_line"]),
            start_byte=int(row["start_byte"]),
            end_byte=int(row["end_byte"]),
            metadata={
                "symbol": row["symbol"],
                "role": row["role"],
                "symbol_roles": row.get("symbol_roles"),
                "indexer_name": row.get("indexer_name"),
                "indexer_version": row.get("indexer_version"),
                "protocol_version": row.get("protocol_version"),
            },
        )

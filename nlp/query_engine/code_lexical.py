"""Lexical lookup over declarations in one active repository snapshot."""

from __future__ import annotations

from typing import Any, Iterable

from .evidence import EvidenceCandidate
from codebase.symbol_retriever import CodeSymbolRetriever


class CodeLexicalRetriever:
    """Resolve exact paths and identifier terms to snapshot-pinned declarations.

    This first lexical slice deliberately searches declarations only. It does
    not pretend that file metadata is source text or replace the future chunk
    full-text index.
    """

    def __init__(self, supabase: Any, *, top_k: int = 30) -> None:
        if top_k < 1 or top_k > 100:
            raise ValueError("top_k must be between 1 and 100")
        self.symbols = CodeSymbolRetriever(supabase, max_results=top_k)
        self.top_k = top_k

    def retrieve(
        self,
        *,
        company_id: str,
        repository_id: str,
        file_paths: Iterable[str] = (),
        qualified_names: Iterable[str] = (),
        identifiers: Iterable[str] = (),
    ) -> list[EvidenceCandidate]:
        """Return ranked declaration candidates for explicit lexical signals."""
        paths = self._normalize_terms(file_paths, limit=10)
        qualified = self._normalize_terms(qualified_names, limit=20)
        names = self._normalize_terms(identifiers, limit=20)

        matches: list[tuple[dict[str, Any], str]] = []
        for name in qualified:
            matches.extend(
                (row, "qualified_name")
                for row in self.symbols.find_qualified_name(
                    company_id=company_id,
                    repository_id=repository_id,
                    qualified_name=name,
                )
            )
        for path in paths:
            matches.extend(
                (row, "file_path")
                for row in self.symbols.list_file_symbols(
                    company_id=company_id,
                    repository_id=repository_id,
                    file_path=path,
                )
            )
        for term in names:
            matches.extend(
                (row, "identifier")
                for row in self.symbols.search_names(
                    company_id=company_id,
                    repository_id=repository_id,
                    term=term,
                )
            )

        candidates: list[EvidenceCandidate] = []
        positions: dict[str, int] = {}
        for row, match_mode in matches:
            candidate = self._candidate(
                row,
                company_id=company_id,
                repository_id=repository_id,
                rank=len(candidates) + 1,
                match_mode=match_mode,
            )
            existing_rank = positions.get(candidate.evidence_id)
            if existing_rank is not None:
                # The first matching strategy determines order; retain all
                # matching modes for transparent debugging.
                existing = candidates[existing_rank]
                modes = list(existing.metadata.get("match_modes", []))
                if match_mode not in modes:
                    modes.append(match_mode)
                    candidates[existing_rank] = EvidenceCandidate(
                        **{
                            **existing.to_dict(),
                            "evidence_id": None,
                            "metadata": {**existing.metadata, "match_modes": modes},
                        }
                    )
                continue

            positions[candidate.evidence_id] = len(candidates)
            candidates.append(candidate)
            if len(candidates) >= self.top_k:
                break

        return [
            EvidenceCandidate(
                **{
                    **candidate.to_dict(),
                    "evidence_id": None,
                    "rank": index,
                }
            )
            for index, candidate in enumerate(candidates, start=1)
        ]

    @staticmethod
    def _normalize_terms(values: Iterable[str], *, limit: int) -> list[str]:
        """Drop blank values, trim whitespace, and preserve first-seen order."""
        normalized: list[str] = []
        for value in values:
            term = str(value or "").strip()
            if term and term not in normalized:
                normalized.append(term)
            if len(normalized) >= limit:
                break
        return normalized

    @staticmethod
    def _candidate(
        row: dict[str, Any],
        *,
        company_id: str,
        repository_id: str,
        rank: int,
        match_mode: str,
    ) -> EvidenceCandidate:
        """Convert a declaration row without losing its source provenance."""
        file_path = str(row.get("file_path") or "")
        qualified_name = str(row.get("qualified_name") or "")
        kind = str(row.get("kind") or "symbol")
        symbol_id = str(row.get("symbol_id") or row.get("id") or "")
        content = f"{qualified_name} ({kind}) in {file_path}"
        return EvidenceCandidate(
            company_id=company_id,
            evidence_type="symbol",
            source="tree-sitter",
            record_id=symbol_id,
            content=content,
            retriever="code-symbol-lexical",
            rank=rank,
            repository_id=repository_id,
            snapshot_id=str(row.get("snapshot_id") or ""),
            source_revision=str(row.get("source_revision") or ""),
            file_path=file_path,
            content_hash=str(row.get("content_hash") or ""),
            start_line=row.get("start_line"),
            end_line=row.get("end_line"),
            start_byte=row.get("start_byte"),
            end_byte=row.get("end_byte"),
            metadata={
                "name": row.get("name"),
                "qualified_name": qualified_name,
                "kind": kind,
                "language": row.get("language"),
                "extractor_version": row.get("extractor_version"),
                "symbol_id": symbol_id,
                "match_modes": [match_mode],
            },
        )

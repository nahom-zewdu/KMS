"""Lexical discovery of declaration candidates from active-snapshot source evidence.

Candidates are suggestions only. This module never manufactures SCIP symbols,
relaxes source-range checks, or authorizes synthesis from a lexical score alone.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol

from .evidence import EvidenceCandidate
from .query_plan import QueryIntent, QueryPlan


class _ChunkReader(Protocol):
    def retrieve(
        self, *, company_id: str, repository_id: str, terms: list[str]
    ) -> list[EvidenceCandidate]: ...


class _SymbolReader(Protocol):
    def list_file_symbols(
        self, *, company_id: str, repository_id: str, file_path: str
    ) -> list[dict[str, Any]]: ...


_GENERIC_TERMS = {
    "an", "and", "are", "before", "by", "call", "calls", "code", "does",
    "find", "function", "implemented", "implementation", "is", "method",
    "operation", "operations", "the", "to", "where", "which",
}
_IDENTIFIER_SPLIT = re.compile(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,80}")
_MAX_QUERY_TERMS = 12


@dataclass(frozen=True, slots=True)
class SymbolCandidate:
    """One declaration nominated by lexical evidence, not yet SCIP-resolved."""

    declaration: dict[str, Any]
    score: int
    matched_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateDiscoveryResult:
    """Ranked candidates and an explicit selection/abstention outcome."""

    candidates: tuple[SymbolCandidate, ...] = ()
    selected: SymbolCandidate | None = None
    reason: str | None = None

    @property
    def discovered(self) -> bool:
        return self.selected is not None


class DescriptiveSymbolCandidateRetriever:
    """Rank declarations using scoped source chunks and exact declaration ranges."""

    def __init__(
        self,
        *,
        source_chunks: _ChunkReader,
        symbols: _SymbolReader,
        max_files: int = 20,
        max_candidates: int = 30,
        minimum_score: int = 4,
        minimum_margin: int = 1,
    ) -> None:
        if not 1 <= max_files <= 50:
            raise ValueError("max_files must be between 1 and 50")
        if not 1 <= max_candidates <= 100:
            raise ValueError("max_candidates must be between 1 and 100")
        if minimum_score < 1 or minimum_margin < 1:
            raise ValueError("candidate thresholds must be positive")
        self.source_chunks = source_chunks
        self.symbols = symbols
        self.max_files = max_files
        self.max_candidates = max_candidates
        self.minimum_score = minimum_score
        self.minimum_margin = minimum_margin

    def discover(self, plan: QueryPlan) -> CandidateDiscoveryResult:
        """Find one sufficiently supported declaration or abstain conservatively."""
        if not isinstance(plan, QueryPlan):
            raise ValueError("plan must be a QueryPlan")
        if plan.intent not in {
            QueryIntent.DECLARATION_DISCOVERY,
            QueryIntent.CALL_SITE_NAVIGATION,
        }:
            return CandidateDiscoveryResult(reason="intent_not_supported")
        repository_id = plan.scope.repository_id
        if not repository_id:
            return CandidateDiscoveryResult(reason="repository_scope_required")

        terms = self._query_terms(plan)
        if len(terms) < 2:
            return CandidateDiscoveryResult(reason="descriptive_terms_insufficient")

        chunks = self.source_chunks.retrieve(
            company_id=plan.scope.company_id,
            repository_id=repository_id,
            terms=self._retrieval_terms(terms),
        )
        scoped_chunks = [
            chunk for chunk in chunks
            if isinstance(chunk, EvidenceCandidate)
            and chunk.company_id == plan.scope.company_id
            and chunk.repository_id == repository_id
            and chunk.evidence_type == "code_chunk"
            and chunk.file_path
            and chunk.start_line > 0
            and chunk.end_line >= chunk.start_line
        ]
        chunks_by_file: dict[str, list[EvidenceCandidate]] = {}
        for chunk in scoped_chunks:
            chunks_by_file.setdefault(chunk.file_path, []).append(chunk)

        ranked: list[SymbolCandidate] = []
        for file_path in sorted(chunks_by_file)[: self.max_files]:
            rows = self.symbols.list_file_symbols(
                company_id=plan.scope.company_id,
                repository_id=repository_id,
                file_path=file_path,
            )
            file_chunks = chunks_by_file[file_path]
            for row in rows:
                if row.get("file_path") != file_path:
                    continue
                start_line = row.get("start_line")
                end_line = row.get("end_line")
                if not isinstance(start_line, int) or not isinstance(end_line, int):
                    continue
                if start_line < 1 or end_line < start_line:
                    continue

                local_chunks = [
                    chunk for chunk in file_chunks
                    if chunk.start_line <= end_line and chunk.end_line >= start_line
                ]
                if not local_chunks:
                    continue
                # Large containers overlap many chunks. Use only the chunk nearest
                # the declaration start so a class cannot inherit an entire file's
                # lexical score and eclipse its individual methods.
                local_chunks.sort(
                    key=lambda chunk: (
                        0 if chunk.start_line <= start_line <= chunk.end_line else 1,
                        abs(chunk.start_line - start_line),
                        chunk.start_line,
                    )
                )
                context = self._declaration_context(
                    row, local_chunks, start_line, end_line
                )
                candidate = self._score(row, terms, context)
                if candidate.score >= self.minimum_score:
                    ranked.append(candidate)

        ranked.sort(
            key=lambda item: (
                -item.score,
                str(item.declaration.get("file_path") or ""),
                int(item.declaration.get("start_byte") or 0),
                str(item.declaration.get("qualified_name") or ""),
            )
        )
        ranked = ranked[: self.max_candidates]
        if not ranked:
            return CandidateDiscoveryResult(reason="no_descriptive_symbol_candidate")

        if len(ranked) > 1 and ranked[0].score - ranked[1].score < self.minimum_margin:
            return CandidateDiscoveryResult(
                candidates=tuple(ranked),
                reason="ambiguous_descriptive_symbol_candidates",
            )
        return CandidateDiscoveryResult(
            candidates=tuple(ranked),
            selected=ranked[0],
        )

    @staticmethod
    def _declaration_context(
        declaration: dict[str, Any],
        chunks: list[EvidenceCandidate],
        start_line: int,
        end_line: int,
    ) -> str:
        """Extract only source lines belonging to this declaration.

        Class ranges often contain every method in a file. Restrict class
        context to its header and leading docstring so it cannot inherit the
        lexical score of unrelated nested declarations.
        """
        selected: list[str] = []
        kind = str(declaration.get("kind") or "").casefold()
        effective_end = min(end_line, start_line + 5) if kind == "class" else end_line
        for chunk in chunks:
            lines = chunk.content.splitlines()
            first = max(start_line, chunk.start_line)
            last = min(effective_end, chunk.end_line)
            if first > last:
                continue
            offset = first - chunk.start_line
            selected.extend(lines[offset: offset + (last - first + 1)])
        return "\\n".join(selected)

    @staticmethod
    def _query_terms(plan: QueryPlan) -> list[str]:
        terms = [
            term.casefold()
            for term in plan.terms
            if term and term.casefold() not in _GENERIC_TERMS
        ]
        return list(dict.fromkeys(terms))[:_MAX_QUERY_TERMS]

    @staticmethod
    def _retrieval_terms(terms: list[str]) -> list[str]:
        """Add bounded morphological forms for literal source-chunk lookup."""
        suffixes = (
            ("ization", "ize"), ("isation", "ise"),
            ("ation", "ate"), ("ment", ""),
            ("ing", ""), ("ed", ""), ("s", ""),
        )
        expanded = list(terms)
        for term in terms:
            for suffix, replacement in suffixes:
                if len(term) > len(suffix) + 3 and term.endswith(suffix):
                    stem = term[:-len(suffix)] + replacement
                    if len(stem) >= 4 and stem not in expanded:
                        expanded.append(stem)
                    break
        return expanded[: _MAX_QUERY_TERMS * 2]

    @classmethod
    def _score(
        cls,
        declaration: dict[str, Any],
        query_terms: list[str],
        context: str,
    ) -> SymbolCandidate:
        name_tokens = cls._tokens(
            " ".join(
                str(declaration.get(field) or "")
                for field in ("name", "qualified_name")
            )
        )
        context_tokens = cls._tokens(context)
        path_tokens = cls._tokens(str(declaration.get("file_path") or ""))
        matched: list[str] = []
        score = 0
        for term in query_terms:
            if cls._matches(term, name_tokens):
                matched.append(term)
                score += 5 if cls._action_like(term) else 2
            elif cls._matches(term, context_tokens):
                matched.append(term)
                score += 1
            elif cls._matches(term, path_tokens):
                matched.append(term)
                score += 1
        # Callable declarations are the useful default for operation-oriented
        # questions, while classes remain eligible when their names/context fit.
        if declaration.get("kind") in {"function", "method"}:
            score += 1
        return SymbolCandidate(
            declaration=declaration,
            score=score,
            matched_terms=tuple(matched),
        )

    @staticmethod
    def _tokens(value: str) -> set[str]:
        output: set[str] = set()
        for raw in _WORD.findall(value):
            pieces = raw.replace("_", " ").split()
            for piece in pieces:
                output.update(
                    token.casefold()
                    for token in _IDENTIFIER_SPLIT.findall(piece)
                    if len(token) > 1
                )
        return output

    @staticmethod
    def _matches(term: str, candidates: set[str]) -> bool:
        if term in candidates:
            return True
        # Conservative inflection tolerance: require a long shared prefix and
        # avoid fuzzy matching short domain terms such as "tax" or "sku".
        return any(
            min(len(term), len(candidate)) >= 5
            and term[:5] == candidate[:5]
            and (term.startswith(candidate) or candidate.startswith(term)
                 or min(len(term), len(candidate)) / max(len(term), len(candidate)) >= 0.60)
            for candidate in candidates
        )

    @staticmethod
    def _action_like(term: str) -> bool:
        return term.endswith(("ed", "ing", "ize", "ise", "ate", "ify"))

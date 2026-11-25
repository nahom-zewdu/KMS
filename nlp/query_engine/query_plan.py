"""Typed, dependency-light query planning contracts.

This module defines validated intent and scope objects only. It deliberately does
not classify natural-language queries, resolve symbols, retrieve evidence, or call
external services.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias


MAX_QUERY_LENGTH = 4_000
MAX_SCOPE_ID_LENGTH = 128
MAX_REVISION_LENGTH = 256
MAX_TERM_COUNT = 20
MAX_TERM_LENGTH = 200
MAX_PATH_COUNT = 50
MAX_PATH_LENGTH = 500
MAX_IDENTIFIER_COUNT = 50
MAX_IDENTIFIER_LENGTH = 256
MAX_CONVERSATION_REFS = 10
MAX_CONVERSATION_REF_LENGTH = 128


class QueryIntent(StrEnum):
    """The operation a planner may request downstream."""

    COURTESY = "courtesy"
    STRUCTURED_FACT = "structured_fact"
    DECLARATION_DISCOVERY = "declaration_discovery"
    CALL_SITE_NAVIGATION = "call_site_navigation"
    PASSAGE_RETRIEVAL = "passage_retrieval"
    FOLLOW_UP = "follow_up"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"


class PlanDisposition(StrEnum):
    """Whether a plan can proceed without further user input."""

    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    ABSTAIN = "abstain"


class SymbolResolutionMethod(StrEnum):
    """How an optional SCIP symbol was resolved."""

    EXACT_QUALIFIED_NAME = "exact_qualified_name"
    EXACT_IDENTIFIER = "exact_identifier"
    CONVERSATION_REFERENCE = "conversation_reference"


@dataclass(frozen=True, slots=True)
class QueryScope:
    """Trusted authorization scope supplied by the caller, never inferred."""

    company_id: str
    repository_id: str | None = None

    def __post_init__(self) -> None:
        _required_identifier(self.company_id, "company_id", MAX_SCOPE_ID_LENGTH)
        _optional_identifier(self.repository_id, "repository_id", MAX_SCOPE_ID_LENGTH)


@dataclass(frozen=True, slots=True)
class QueryConstraints:
    """Optional source revision and time bounds requested by the query."""

    source_revision: str | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None

    def __post_init__(self) -> None:
        _optional_text(self.source_revision, "source_revision", MAX_REVISION_LENGTH)
        if self.time_from is not None and not isinstance(self.time_from, datetime):
            raise ValueError("time_from must be a datetime")
        if self.time_to is not None and not isinstance(self.time_to, datetime):
            raise ValueError("time_to must be a datetime")
        if self.time_from and self.time_to:
            if (self.time_from.utcoffset() is None) != (self.time_to.utcoffset() is None):
                raise ValueError("time bounds must both be timezone-aware or both naive")
            if self.time_from > self.time_to:
                raise ValueError("time_from must not be later than time_to")


@dataclass(frozen=True, slots=True)
class ResolvedScipSymbol:
    """A resolved symbol plus the explicit basis for that resolution."""

    symbol: str
    method: SymbolResolutionMethod
    source_value: str

    def __post_init__(self) -> None:
        if not isinstance(self.method, SymbolResolutionMethod):
            raise ValueError("method must be a SymbolResolutionMethod")
        _required_text(self.symbol, "symbol", MAX_IDENTIFIER_LENGTH)
        _required_text(self.source_value, "source_value", MAX_IDENTIFIER_LENGTH)


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """Immutable plan contract; values are bounded before downstream use."""

    query: str
    intent: QueryIntent
    scope: QueryScope
    disposition: PlanDisposition = PlanDisposition.READY
    constraints: QueryConstraints = QueryConstraints()
    terms: tuple[str, ...] = ()
    file_paths: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    qualified_names: tuple[str, ...] = ()
    resolved_symbol: ResolvedScipSymbol | None = None
    conversation_refs: tuple[str, ...] = ()
    ambiguity_reason: str | None = None
    abstention_reason: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.query, "query", MAX_QUERY_LENGTH)
        if not isinstance(self.intent, QueryIntent):
            raise ValueError("intent must be a QueryIntent")
        if not isinstance(self.disposition, PlanDisposition):
            raise ValueError("disposition must be a PlanDisposition")
        if not isinstance(self.scope, QueryScope):
            raise ValueError("scope must be a QueryScope")
        if not isinstance(self.constraints, QueryConstraints):
            raise ValueError("constraints must be QueryConstraints")

        _bounded_values(self.terms, "terms", MAX_TERM_COUNT, MAX_TERM_LENGTH)
        _bounded_values(self.file_paths, "file_paths", MAX_PATH_COUNT, MAX_PATH_LENGTH)
        _bounded_values(
            self.identifiers, "identifiers", MAX_IDENTIFIER_COUNT, MAX_IDENTIFIER_LENGTH
        )
        _bounded_values(
            self.qualified_names,
            "qualified_names",
            MAX_IDENTIFIER_COUNT,
            MAX_IDENTIFIER_LENGTH,
        )
        _bounded_values(
            self.conversation_refs,
            "conversation_refs",
            MAX_CONVERSATION_REFS,
            MAX_CONVERSATION_REF_LENGTH,
        )

        if self.resolved_symbol is not None and not isinstance(
            self.resolved_symbol, ResolvedScipSymbol
        ):
            raise ValueError("resolved_symbol must be ResolvedScipSymbol")

        _optional_text(self.ambiguity_reason, "ambiguity_reason", 500)
        _optional_text(self.abstention_reason, "abstention_reason", 500)

        if self.disposition is PlanDisposition.NEEDS_CLARIFICATION:
            if not self.ambiguity_reason:
                raise ValueError("clarification plans require ambiguity_reason")
            if self.abstention_reason:
                raise ValueError("clarification plans cannot set abstention_reason")
        elif self.ambiguity_reason:
            raise ValueError("ambiguity_reason requires needs_clarification disposition")

        if self.disposition is PlanDisposition.ABSTAIN and not self.abstention_reason:
            raise ValueError("abstaining plans require abstention_reason")
        if self.disposition is not PlanDisposition.ABSTAIN and self.abstention_reason:
            raise ValueError("abstention_reason requires abstain disposition")

        if self.intent is QueryIntent.CLARIFICATION:
            if self.disposition is not PlanDisposition.NEEDS_CLARIFICATION:
                raise ValueError("clarification intent requires needs_clarification")
        if self.intent is QueryIntent.UNSUPPORTED:
            if self.disposition is not PlanDisposition.ABSTAIN:
                raise ValueError("unsupported intent requires abstain disposition")
        if self.resolved_symbol and self.intent is not QueryIntent.CALL_SITE_NAVIGATION:
            raise ValueError("resolved SCIP symbols are only valid for call-site navigation")


def _required_text(value: object, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")


def _optional_text(value: object, field: str, maximum: int) -> None:
    if value is not None:
        _required_text(value, field, maximum)


def _required_identifier(value: object, field: str, maximum: int) -> None:
    _required_text(value, field, maximum)
    if str(value).strip().lower() in {"default", "null", "none", "unknown"}:
        raise ValueError(f"{field} cannot use a placeholder value")


def _optional_identifier(value: object, field: str, maximum: int) -> None:
    if value is not None:
        _required_identifier(value, field, maximum)


def _bounded_values(
    values: tuple[str, ...], field: str, max_count: int, max_length: int
) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{field} must be a tuple")
    if len(values) > max_count:
        raise ValueError(f"{field} exceeds {max_count} values")
    for value in values:
        _required_text(value, field, max_length)


QueryPlanValue: TypeAlias = QueryPlan

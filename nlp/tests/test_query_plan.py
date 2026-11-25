"""Tests for the dependency-light typed query-plan contract."""
from datetime import datetime, timezone

import pytest

from query_engine.query_plan import (
    PlanDisposition,
    QueryConstraints,
    QueryIntent,
    QueryPlan,
    QueryScope,
    ResolvedScipSymbol,
    SymbolResolutionMethod,
)


def _plan(**overrides):
    values = {
        "query": "Where is invoice total calculated?",
        "intent": QueryIntent.DECLARATION_DISCOVERY,
        "scope": QueryScope(company_id="company-1", repository_id="repo-1"),
    }
    values.update(overrides)
    return QueryPlan(**values)


@pytest.mark.parametrize(
    "intent",
    [
        QueryIntent.COURTESY,
        QueryIntent.STRUCTURED_FACT,
        QueryIntent.DECLARATION_DISCOVERY,
        QueryIntent.CALL_SITE_NAVIGATION,
        QueryIntent.PASSAGE_RETRIEVAL,
        QueryIntent.FOLLOW_UP,
    ],
)
def test_ready_plan_accepts_supported_intents(intent):
    assert _plan(intent=intent).disposition is PlanDisposition.READY


def test_scope_requires_trusted_company_and_rejects_placeholders():
    for value in ("", "default", "unknown", "NULL"):
        with pytest.raises(ValueError):
            QueryScope(company_id=value)
    assert QueryScope(company_id="company-1", repository_id=None)


def test_scope_rejects_oversized_identifiers():
    with pytest.raises(ValueError, match="company_id"):
        QueryScope(company_id="c" * 129)


def test_plan_rejects_untyped_intent_and_disposition():
    with pytest.raises(ValueError, match="QueryIntent"):
        _plan(intent="guess")
    with pytest.raises(ValueError, match="PlanDisposition"):
        _plan(disposition="ready")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("terms", ("x" * 201,)),
        ("file_paths", ("x" * 501,)),
        ("identifiers", ("x" * 257,)),
        ("qualified_names", ("x" * 257,)),
        ("conversation_refs", ("x" * 129,)),
    ],
)
def test_plan_rejects_oversized_extracted_values(field, value):
    with pytest.raises(ValueError):
        _plan(**{field: value})


@pytest.mark.parametrize(
    ("field", "value", "limit"),
    [
        ("terms", tuple(f"t{i}" for i in range(21)), 20),
        ("file_paths", tuple(f"p{i}" for i in range(51)), 50),
        ("identifiers", tuple(f"i{i}" for i in range(51)), 50),
        ("qualified_names", tuple(f"q{i}" for i in range(51)), 50),
        ("conversation_refs", tuple(f"r{i}" for i in range(11)), 10),
    ],
)
def test_plan_rejects_too_many_extracted_values(field, value, limit):
    with pytest.raises(ValueError, match=str(limit)):
        _plan(**{field: value})


def test_plan_rejects_mutable_collections():
    with pytest.raises(ValueError, match="tuple"):
        _plan(terms=["invoice"])


def test_constraints_validate_revision_and_time_window():
    with pytest.raises(ValueError):
        QueryConstraints(source_revision="r" * 257)
    with pytest.raises(ValueError, match="time_from"):
        QueryConstraints(
            time_from=datetime(2026, 1, 2, tzinfo=timezone.utc),
            time_to=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    valid = QueryConstraints(
        source_revision="abc123",
        time_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        time_to=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert valid.source_revision == "abc123"


def test_clarification_requires_explicit_ambiguity_and_preserves_it():
    plan = _plan(
        intent=QueryIntent.CLARIFICATION,
        disposition=PlanDisposition.NEEDS_CLARIFICATION,
        ambiguity_reason="Two repositories contain the requested symbol.",
    )
    assert plan.ambiguity_reason.startswith("Two repositories")
    with pytest.raises(ValueError, match="ambiguity_reason"):
        _plan(
            intent=QueryIntent.CLARIFICATION,
            disposition=PlanDisposition.NEEDS_CLARIFICATION,
        )


def test_abstention_requires_explicit_reason():
    plan = _plan(
        intent=QueryIntent.UNSUPPORTED,
        disposition=PlanDisposition.ABSTAIN,
        abstention_reason="unsupported_query",
    )
    assert plan.abstention_reason == "unsupported_query"
    with pytest.raises(ValueError, match="abstention_reason"):
        _plan(intent=QueryIntent.UNSUPPORTED, disposition=PlanDisposition.ABSTAIN)


def test_resolved_symbol_preserves_resolution_provenance():
    symbol = ResolvedScipSymbol(
        symbol="scip-python python pkg Invoice.total().",
        method=SymbolResolutionMethod.EXACT_QUALIFIED_NAME,
        source_value="Invoice.total",
    )
    plan = _plan(
        intent=QueryIntent.CALL_SITE_NAVIGATION,
        resolved_symbol=symbol,
    )
    assert plan.resolved_symbol == symbol
    assert plan.resolved_symbol.method is SymbolResolutionMethod.EXACT_QUALIFIED_NAME


def test_resolved_symbol_is_rejected_for_non_call_site_intent():
    symbol = ResolvedScipSymbol(
        symbol="scip-symbol",
        method=SymbolResolutionMethod.EXACT_IDENTIFIER,
        source_value="calculate",
    )
    with pytest.raises(ValueError, match="call-site"):
        _plan(resolved_symbol=symbol)


def test_follow_up_can_retain_conversation_references_without_forcing_resolution():
    plan = _plan(
        intent=QueryIntent.FOLLOW_UP,
        conversation_refs=("turn-12-evidence-3",),
    )
    assert plan.conversation_refs == ("turn-12-evidence-3",)
    assert plan.resolved_symbol is None

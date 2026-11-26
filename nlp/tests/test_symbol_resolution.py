"""Tests for exact, provenance-checked SCIP symbol resolution."""
from query_engine.query_plan import (
    PlanDisposition,
    QueryIntent,
    QueryPlan,
    QueryScope,
    SymbolResolutionMethod,
)
from query_engine.symbol_resolution import ConservativeScipSymbolResolver


SCOPE = QueryScope(company_id="company-1", repository_id="repo-1")


def _plan(
    *,
    intent=QueryIntent.CALL_SITE_NAVIGATION,
    disposition=PlanDisposition.READY,
    identifiers=("calculate_tax",),
    qualified_names=(),
):
    ambiguity = "ambiguous" if disposition is PlanDisposition.NEEDS_CLARIFICATION else None
    abstention = "unsupported" if disposition is PlanDisposition.ABSTAIN else None
    return QueryPlan(
        query="Where is calculate_tax called?",
        intent=intent,
        scope=SCOPE,
        disposition=disposition,
        identifiers=identifiers,
        qualified_names=qualified_names,
        ambiguity_reason=ambiguity,
        abstention_reason=abstention,
    )


def _declaration(**overrides):
    row = {
        "id": "decl-1",
        "symbol_id": "symbol-row-1",
        "qualified_name": "billing.calculate_tax",
        "name": "calculate_tax",
        "file_path": "billing/invoice.py",
        "snapshot_id": "snapshot-1",
        "start_byte": 10,
        "end_byte": 45,
        "start_line": 2,
        "end_line": 2,
    }
    return {**row, **overrides}


def _occurrence(**overrides):
    row = {
        "occurrence_id": "occ-1",
        "symbol": "scip-python python billing  billing/invoice.py/calculate_tax.",
        "role": "definition",
        "file_path": "billing/invoice.py",
        "snapshot_id": "snapshot-1",
        "start_byte": 10,
        "end_byte": 45,
        "start_line": 2,
        "end_line": 2,
    }
    return {**row, **overrides}


class FakeDeclarations:
    def __init__(self, qualified=(), names=()):
        self.qualified = list(qualified)
        self.names = list(names)
        self.calls = []

    def find_qualified_name(self, **kwargs):
        self.calls.append(("qualified", kwargs))
        return self.qualified

    def search_names(self, **kwargs):
        self.calls.append(("name", kwargs))
        return self.names


class FakeOccurrences:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    def list_file_occurrences(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


def _resolver(declarations=None, occurrences=None):
    return ConservativeScipSymbolResolver(
        declarations or FakeDeclarations(),
        occurrences or FakeOccurrences(),
    )


def test_resolves_exact_qualified_name_and_preserves_trusted_scope():
    declarations = FakeDeclarations(qualified=[_declaration()])
    occurrences = FakeOccurrences([_occurrence()])
    result = _resolver(declarations, occurrences).resolve(
        _plan(identifiers=("calculate_tax",), qualified_names=("billing.calculate_tax",))
    )
    assert result.resolved
    assert result.reason is None
    assert result.plan.scope is SCOPE
    assert result.plan.resolved_symbol.symbol == _occurrence()["symbol"]
    assert result.plan.resolved_symbol.method is SymbolResolutionMethod.EXACT_QUALIFIED_NAME
    assert result.plan.resolved_symbol.source_value == "billing.calculate_tax"
    assert declarations.calls == [(
        "qualified",
        {
            "company_id": "company-1",
            "repository_id": "repo-1",
            "qualified_name": "billing.calculate_tax",
        },
    )]


def test_resolves_exact_identifier_after_filtering_substring_matches():
    declarations = FakeDeclarations(names=[
        _declaration(name="calculate_tax_extra", qualified_name="billing.calculate_tax_extra"),
        _declaration(),
    ])
    occurrences = FakeOccurrences([_occurrence()])
    result = _resolver(declarations, occurrences).resolve(_plan())
    assert result.resolved
    assert result.plan.resolved_symbol.method is SymbolResolutionMethod.EXACT_IDENTIFIER
    assert len(declarations.calls) == 1
    assert declarations.calls[0][0] == "name"


def test_qualified_name_takes_precedence_over_identifier_candidates():
    declarations = FakeDeclarations(qualified=[_declaration()])
    occurrences = FakeOccurrences([_occurrence()])
    plan = _plan(
        identifiers=("calculate_tax", "another_identifier"),
        qualified_names=("billing.calculate_tax",),
    )
    result = _resolver(declarations, occurrences).resolve(plan)
    assert result.resolved
    assert result.plan.resolved_symbol.source_value == "billing.calculate_tax"


def test_multiple_explicit_candidate_names_are_ambiguous():
    declarations = FakeDeclarations()
    result = _resolver(declarations).resolve(
        _plan(identifiers=("calculate_tax", "calculate_total"))
    )
    assert result.reason == "multiple_symbol_candidates"
    assert declarations.calls == []


def test_no_explicit_candidate_is_rejected():
    result = _resolver().resolve(_plan(identifiers=()))
    assert result.reason == "no_explicit_symbol_candidate"


def test_missing_repository_scope_is_rejected_before_retriever_calls():
    plan = QueryPlan(
        query="Where is calculate_tax called?",
        intent=QueryIntent.CALL_SITE_NAVIGATION,
        scope=QueryScope(company_id="company-1"),
        identifiers=("calculate_tax",),
    )
    declarations = FakeDeclarations()
    result = _resolver(declarations).resolve(plan)
    assert result.reason == "repository_scope_required"
    assert declarations.calls == []


def test_non_call_site_plan_is_not_resolved():
    declarations = FakeDeclarations()
    result = _resolver(declarations).resolve(
        _plan(intent=QueryIntent.PASSAGE_RETRIEVAL)
    )
    assert result.reason == "not_call_site_query"
    assert declarations.calls == []


def test_non_ready_plan_is_not_resolved():
    declarations = FakeDeclarations()
    result = _resolver(declarations).resolve(
        _plan(disposition=PlanDisposition.NEEDS_CLARIFICATION)
    )
    assert result.reason == "plan_not_ready"
    assert declarations.calls == []


def test_missing_declaration_is_reported():
    result = _resolver(FakeDeclarations(names=[])).resolve(_plan())
    assert result.reason == "declaration_not_found"


def test_duplicate_declarations_are_ambiguous():
    rows = [
        _declaration(file_path="billing/a.py"),
        _declaration(id="decl-2", file_path="billing/b.py"),
    ]
    result = _resolver(FakeDeclarations(names=rows)).resolve(_plan())
    assert result.reason == "ambiguous_declaration"


def test_missing_scip_definition_is_reported():
    occurrences = FakeOccurrences([_occurrence(role="reference")])
    result = _resolver(FakeDeclarations(names=[_declaration()]), occurrences).resolve(_plan())
    assert result.reason == "definition_occurrence_not_found"


def test_mismatched_source_range_is_not_accepted():
    occurrences = FakeOccurrences([_occurrence(start_byte=11)])
    result = _resolver(FakeDeclarations(names=[_declaration()]), occurrences).resolve(_plan())
    assert result.reason == "definition_occurrence_not_found"


def test_snapshot_mismatch_is_not_accepted():
    occurrences = FakeOccurrences([_occurrence(snapshot_id="snapshot-old")])
    result = _resolver(FakeDeclarations(names=[_declaration()]), occurrences).resolve(_plan())
    assert result.reason == "definition_occurrence_not_found"


def test_multiple_distinct_scip_symbols_for_same_definition_are_ambiguous():
    occurrences = FakeOccurrences([
        _occurrence(),
        _occurrence(occurrence_id="occ-2", symbol="different-scip-symbol"),
    ])
    result = _resolver(FakeDeclarations(names=[_declaration()]), occurrences).resolve(_plan())
    assert result.reason == "ambiguous_scip_definition"


def test_resolver_does_not_mutate_original_plan():
    plan = _plan()
    result = _resolver(
        FakeDeclarations(names=[_declaration()]),
        FakeOccurrences([_occurrence()]),
    ).resolve(plan)
    assert result.resolved
    assert plan.resolved_symbol is None

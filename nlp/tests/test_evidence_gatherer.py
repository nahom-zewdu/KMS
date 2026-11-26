"""Tests for bounded, plan-driven evidence gathering."""
from query_engine.evidence import EvidenceCandidate
from query_engine.evidence_gatherer import BoundedEvidenceGatherer
from query_engine.query_plan import (
    PlanDisposition, QueryConstraints, QueryIntent, QueryPlan, QueryScope,
    ResolvedScipSymbol, SymbolResolutionMethod,
)


SCOPE = QueryScope(company_id="company-a", repository_id="repo-a")


def _plan(intent, **kwargs):
    return QueryPlan(
        query="explain calculate_tax in billing/invoice.py",
        intent=intent,
        scope=kwargs.pop("scope", SCOPE),
        **kwargs,
    )


def _candidate(**overrides):
    values = dict(
        company_id="company-a", evidence_type="code_chunk",
        source="source-code-chunks", record_id="chunk-1", content="calculate_tax",
        retriever="source-chunk-lexical", rank=1, repository_id="repo-a",
        snapshot_id="snapshot-current", source_revision="rev-a",
        file_path="billing/invoice.py", content_hash="a" * 64,
        start_line=1, end_line=2, start_byte=0, end_byte=20,
    )
    values.update(overrides)
    return EvidenceCandidate(**values)


class Source:
    def __init__(self, rows=()):
        self.rows, self.calls = list(rows), []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


class Symbols:
    def __init__(self, rows=()):
        self.rows, self.calls = list(rows), []

    def find_qualified_name(self, **kwargs):
        self.calls.append(("qualified", kwargs))
        return self.rows

    def search_names(self, **kwargs):
        self.calls.append(("search", kwargs))
        return self.rows

    def list_file_symbols(self, **kwargs):
        self.calls.append(("file", kwargs))
        return self.rows


class Occurrences:
    def __init__(self, rows=()):
        self.rows, self.calls = list(rows), []

    def find_references(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


def _gatherer(source=None, symbols=None, occurrences=None, **kwargs):
    return BoundedEvidenceGatherer(
        source_chunks=source or Source(),
        symbols=symbols or Symbols(),
        occurrences=occurrences or Occurrences(),
        **kwargs,
    )


def _symbol_row(**overrides):
    row = {
        "company_id": "company-a", "repository_id": "repo-a",
        "symbol_id": "symbol-1", "name": "calculate_tax",
        "qualified_name": "billing.calculate_tax", "kind": "function",
        "snapshot_id": "snapshot-current", "source_revision": "rev-a",
        "file_path": "billing/invoice.py", "content_hash": "b" * 64,
        "start_line": 3, "end_line": 5, "start_byte": 20, "end_byte": 90,
    }
    return {**row, **overrides}


def _occurrence_row(**overrides):
    row = {
        "company_id": "company-a", "repository_id": "repo-a",
        "occurrence_id": "occ-1", "symbol": "scip-python billing.calculate_tax",
        "role": "reference", "snapshot_id": "snapshot-current",
        "source_revision": "rev-a", "file_path": "billing/routes.py",
        "content_hash": "c" * 64, "start_line": 8, "end_line": 8,
        "start_byte": 100, "end_byte": 120,
    }
    return {**row, **overrides}


def test_passage_retrieval_forwards_trusted_scope_and_bounded_terms():
    source = Source([_candidate()])
    result = _gatherer(source=source).gather(
        _plan(QueryIntent.PASSAGE_RETRIEVAL, terms=("calculate_tax", "billing"))
    )
    assert result.gathered
    assert result.evidence == (_candidate(),)
    assert source.calls == [{
        "company_id": "company-a", "repository_id": "repo-a",
        "terms": ["calculate_tax", "billing"],
    }]


def test_passage_retrieval_rejects_cross_scope_and_wrong_revision_candidates():
    source = Source([
        _candidate(company_id="company-b"),
        _candidate(repository_id="repo-b"),
        _candidate(source_revision="rev-old"),
    ])
    plan = _plan(
        QueryIntent.PASSAGE_RETRIEVAL, terms=("calculate_tax",),
        constraints=QueryConstraints(source_revision="rev-a"),
    )
    result = _gatherer(source=source).gather(plan)
    assert result.evidence == ()
    assert result.reason == "no_matching_evidence"


def test_declaration_discovery_uses_exact_qualified_name_and_provenance():
    symbols = Symbols([_symbol_row()])
    result = _gatherer(symbols=symbols).gather(
        _plan(QueryIntent.DECLARATION_DISCOVERY, qualified_names=("billing.calculate_tax",))
    )
    assert result.gathered
    assert result.evidence[0].evidence_type == "symbol"
    assert result.evidence[0].file_path == "billing/invoice.py"
    assert symbols.calls == [("qualified", {
        "company_id": "company-a", "repository_id": "repo-a",
        "qualified_name": "billing.calculate_tax",
    })]


def test_declaration_discovery_filters_non_exact_name_and_revision():
    symbols = Symbols([
        _symbol_row(qualified_name="billing.calculate_tax_extra"),
        _symbol_row(symbol_id="symbol-old", source_revision="rev-old"),
    ])
    result = _gatherer(symbols=symbols).gather(
        _plan(
            QueryIntent.DECLARATION_DISCOVERY,
            identifiers=("calculate_tax",),
            constraints=QueryConstraints(source_revision="rev-a"),
        )
    )
    assert result.evidence == ()
    assert result.reason == "declaration_not_found"


def test_declaration_discovery_supports_single_explicit_file_path():
    symbols = Symbols([_symbol_row()])
    result = _gatherer(symbols=symbols).gather(
        _plan(QueryIntent.DECLARATION_DISCOVERY, file_paths=("billing/invoice.py",))
    )
    assert result.gathered
    assert symbols.calls[0][0] == "file"


def test_call_site_navigation_requires_resolved_symbol_and_returns_references_only():
    occurrences = Occurrences([
        _occurrence_row(role="definition"),
        _occurrence_row(occurrence_id="occ-2", role="reference"),
    ])
    plan = _plan(
        QueryIntent.CALL_SITE_NAVIGATION,
        resolved_symbol=ResolvedScipSymbol(
            symbol="scip-python billing.calculate_tax",
            method=SymbolResolutionMethod.EXACT_QUALIFIED_NAME,
            source_value="billing.calculate_tax",
        ),
    )
    result = _gatherer(occurrences=occurrences).gather(plan)
    assert len(result.evidence) == 1
    assert result.evidence[0].record_id == "occ-2"
    assert occurrences.calls == [{
        "company_id": "company-a", "repository_id": "repo-a",
        "symbol": "scip-python billing.calculate_tax",
    }]


def test_non_ready_and_non_retrieval_intents_do_not_call_retrievers():
    source, symbols, occurrences = Source(), Symbols(), Occurrences()
    gatherer = _gatherer(source=source, symbols=symbols, occurrences=occurrences)
    clarification = _plan(
        QueryIntent.CLARIFICATION,
        disposition=PlanDisposition.NEEDS_CLARIFICATION,
        ambiguity_reason="Which file?",
    )
    assert gatherer.gather(clarification).reason == "plan_not_ready"
    assert gatherer.gather(_plan(QueryIntent.COURTESY)).reason == "intent_does_not_retrieve"
    assert gatherer.gather(_plan(QueryIntent.STRUCTURED_FACT)).reason == "structured_retrieval_not_supported"
    assert source.calls == symbols.calls == occurrences.calls == []


def test_missing_repository_scope_and_unsupported_constraints_fail_closed():
    gatherer = _gatherer()
    no_repo = _plan(
        QueryIntent.PASSAGE_RETRIEVAL, scope=QueryScope(company_id="company-a"),
        terms=("calculate_tax",),
    )
    assert gatherer.gather(no_repo).reason == "repository_scope_required"
    time_bound = _plan(
        QueryIntent.PASSAGE_RETRIEVAL, terms=("calculate_tax",),
        constraints=QueryConstraints(time_from=__import__("datetime").datetime(2026, 1, 1)),
    )
    assert gatherer.gather(time_bound).reason == "time_constraints_not_supported"


def test_results_and_content_are_bounded():
    rows = [
        _candidate(record_id=f"chunk-{i}", content="x" * 100)
        for i in range(5)
    ]
    result = _gatherer(source=Source(rows), max_results=2, max_content_chars=10).gather(
        _plan(QueryIntent.PASSAGE_RETRIEVAL, terms=("x",))
    )
    assert len(result.evidence) == 2
    assert all(len(item.content) <= 10 for item in result.evidence)


def test_multiple_declaration_targets_abstain_instead_of_fanning_out():
    symbols = Symbols()
    result = _gatherer(symbols=symbols).gather(
        _plan(
            QueryIntent.DECLARATION_DISCOVERY,
            identifiers=("calculate_tax", "calculate_total"),
        )
    )
    assert result.reason == "multiple_symbol_candidates"
    assert symbols.calls == []



def test_declaration_discovery_does_not_fall_back_from_ambiguous_qualified_names():
    symbols = Symbols()
    result = _gatherer(symbols=symbols).gather(
        _plan(
            QueryIntent.DECLARATION_DISCOVERY,
            qualified_names=("billing.calculate_tax", "billing.calculate_total"),
            identifiers=("calculate_tax",),
        )
    )
    assert result.reason == "multiple_symbol_candidates"
    assert symbols.calls == []


def test_symbol_and_occurrence_rows_must_match_trusted_tenant_scope():
    symbols = Symbols([_symbol_row(company_id="company-b")])
    declaration_result = _gatherer(symbols=symbols).gather(
        _plan(QueryIntent.DECLARATION_DISCOVERY, qualified_names=("billing.calculate_tax",))
    )
    assert declaration_result.evidence == ()

    occurrences = Occurrences([_occurrence_row(repository_id="repo-b")])
    call_plan = _plan(
        QueryIntent.CALL_SITE_NAVIGATION,
        resolved_symbol=ResolvedScipSymbol(
            symbol="scip-python billing.calculate_tax",
            method=SymbolResolutionMethod.EXACT_QUALIFIED_NAME,
            source_value="billing.calculate_tax",
        ),
    )
    call_result = _gatherer(occurrences=occurrences).gather(call_plan)
    assert call_result.evidence == ()

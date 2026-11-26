"""Tests for conservative KRT-04 planned-query orchestration."""
from query_engine.evidence import EvidenceCandidate
from query_engine.planned_query import PlannedQueryExecutor
from query_engine.query_plan import (
    QueryIntent, QueryScope, ResolvedScipSymbol, SymbolResolutionMethod,
)
from query_engine.symbol_resolution import SymbolResolutionResult


SCOPE = QueryScope(company_id="company-a", repository_id="repo-a")


def _evidence():
    return EvidenceCandidate(
        company_id="company-a", evidence_type="code_chunk",
        source="source-code-chunks", record_id="chunk-1",
        content="def calculate_tax(): return 1",
        retriever="source-chunk-lexical", rank=1,
        repository_id="repo-a", snapshot_id="snapshot-a",
        source_revision="revision-a", file_path="billing/tax.py",
        content_hash="a" * 64, start_line=1, end_line=1,
        start_byte=0, end_byte=30,
    )


class Gatherer:
    def __init__(self, evidence=None, reason=None):
        self.evidence = tuple(evidence or ())
        self.reason = reason
        self.calls = []

    def gather(self, plan):
        self.calls.append(plan)
        from query_engine.evidence_gatherer import EvidenceGatheringResult
        return EvidenceGatheringResult(plan, self.evidence, self.reason)


class Resolver:
    def __init__(self, resolved=True):
        self.resolved = resolved
        self.calls = []

    def resolve(self, plan):
        self.calls.append(plan)
        if not self.resolved:
            return SymbolResolutionResult(None, "ambiguous_declaration")
        from dataclasses import replace
        return SymbolResolutionResult(
            replace(plan, resolved_symbol=ResolvedScipSymbol(
                symbol="scip-python billing.calculate_tax",
                method=SymbolResolutionMethod.EXACT_QUALIFIED_NAME,
                source_value="billing.calculate_tax",
            )),
            None,
        )


def test_passage_query_runs_full_pipeline_and_returns_validated_claims():
    evidence = _evidence()
    gatherer = Gatherer([evidence])
    resolver = Resolver()
    synth_calls = []

    def synthesize(question, candidates):
        synth_calls.append((question, candidates))
        return {
            "confidence": "high",
            "claims": [{
                "text": "calculate_tax returns 1.",
                "evidence_ids": [evidence.evidence_id],
            }],
        }

    executor = PlannedQueryExecutor(
        evidence_gatherer=gatherer,
        symbol_resolver=resolver,
        synthesizer=synthesize,
    )
    result = executor.execute("Explain calculate_tax in billing/tax.py", scope=SCOPE)

    assert result.completed
    assert result.plan.intent is QueryIntent.PASSAGE_RETRIEVAL
    assert result.answer["claims"][0]["evidence_ids"] == [evidence.evidence_id]
    assert len(result.answer["sources"]) == 1
    assert len(gatherer.calls) == 1
    assert resolver.calls == []
    assert len(synth_calls) == 1


def test_call_site_query_resolves_symbol_before_gathering():
    evidence = _evidence()
    gatherer = Gatherer([evidence])
    resolver = Resolver()
    executor = PlannedQueryExecutor(
        evidence_gatherer=gatherer,
        symbol_resolver=resolver,
        synthesizer=lambda *_: {
            "claims": [{"text": "A reference exists.", "evidence_ids": [evidence.evidence_id]}]
        },
    )

    result = executor.execute(
        "Where is calculate_tax called in billing/tax.py?", scope=SCOPE
    )
    assert result.completed
    assert len(resolver.calls) == 1
    assert gatherer.calls[0].resolved_symbol.symbol == "scip-python billing.calculate_tax"


def test_structured_and_follow_up_queries_are_deferred_without_retrieval():
    gatherer, resolver = Gatherer(), Resolver()
    executor = PlannedQueryExecutor(
        evidence_gatherer=gatherer, symbol_resolver=resolver,
        synthesizer=lambda *_: "",
    )

    structured = executor.execute("How many files are in this repository?", scope=SCOPE)
    follow_up = executor.execute(
        "Tell me more about it", scope=SCOPE,
        conversation_history=[{"role": "user", "content": "Explain the billing module."}],
        conversation_refs=["evidence-previous"],
    )

    assert structured.deferred and structured.reason == "legacy_structured_route"
    assert follow_up.deferred and follow_up.reason == "conversation_context_route"
    assert gatherer.calls == []
    assert resolver.calls == []


def test_unsupported_query_abstains_without_retrieval():
    gatherer, resolver = Gatherer(), Resolver()
    executor = PlannedQueryExecutor(
        evidence_gatherer=gatherer, symbol_resolver=resolver,
        synthesizer=lambda *_: "",
    )
    result = executor.execute("What is the meaning of life?", scope=SCOPE)
    assert result.completed
    assert result.answer["abstain_reason"] == "unsupported_query"
    assert gatherer.calls == []


def test_symbol_resolution_ambiguity_abstains_before_gathering():
    gatherer, resolver = Gatherer(), Resolver(resolved=False)
    executor = PlannedQueryExecutor(
        evidence_gatherer=gatherer, symbol_resolver=resolver,
        synthesizer=lambda *_: "",
    )
    result = executor.execute("Where is calculate_tax called?", scope=SCOPE)
    assert result.reason == "ambiguous_declaration"
    assert result.answer["abstain_reason"] == "ambiguous_declaration"
    assert gatherer.calls == []


def test_missing_evidence_abstains_without_calling_synthesizer():
    gatherer = Gatherer(reason="no_matching_evidence")
    synth_calls = []
    executor = PlannedQueryExecutor(
        evidence_gatherer=gatherer, symbol_resolver=Resolver(),
        synthesizer=lambda *args: synth_calls.append(args) or "",
    )
    result = executor.execute("Explain calculate_tax", scope=SCOPE)
    assert result.reason == "no_matching_evidence"
    assert synth_calls == []


def test_invalid_model_citation_is_rejected_at_orchestration_boundary():
    evidence = _evidence()
    executor = PlannedQueryExecutor(
        evidence_gatherer=Gatherer([evidence]),
        symbol_resolver=Resolver(),
        synthesizer=lambda *_: {
            "claims": [{"text": "Unsupported statement.", "evidence_ids": ["fake-id"]}]
        },
    )
    result = executor.execute("Explain calculate_tax", scope=SCOPE)
    assert result.answer["abstain_reason"] == "citation_not_in_retrieved_evidence"
    assert result.answer["sources"] == []



def test_stage_observer_reports_pipeline_timings_without_prompt_or_evidence():
    evidence = _evidence()
    observed = []
    executor = PlannedQueryExecutor(
        evidence_gatherer=Gatherer([evidence]),
        symbol_resolver=Resolver(),
        synthesizer=lambda *_: {
            "claims": [{"text": "Tax calculation is defined.", "evidence_ids": [evidence.evidence_id]}]
        },
    )

    result = executor.execute(
        "Explain calculate_tax in billing/tax.py",
        scope=SCOPE,
        stage_observer=lambda stage, duration: observed.append((stage, duration)),
    )

    assert result.completed
    assert [stage for stage, _ in observed] == [
        "classification", "evidence_gathering", "synthesis", "citation_validation"
    ]
    assert all(isinstance(duration, float) and duration >= 0 for _, duration in observed)


def test_stage_observer_failure_does_not_change_query_result():
    evidence = _evidence()
    executor = PlannedQueryExecutor(
        evidence_gatherer=Gatherer([evidence]),
        symbol_resolver=Resolver(),
        synthesizer=lambda *_: {
            "claims": [{"text": "Tax calculation is defined.", "evidence_ids": [evidence.evidence_id]}]
        },
    )

    result = executor.execute(
        "Explain calculate_tax in billing/tax.py",
        scope=SCOPE,
        stage_observer=lambda *_: (_ for _ in ()).throw(RuntimeError("metrics unavailable")),
    )

    assert result.completed
    assert result.answer["claims"][0]["text"] == "Tax calculation is defined."

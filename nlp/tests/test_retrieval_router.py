"""Contract tests for deterministic task-aware retrieval routing."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from query_engine.evidence import EvidenceCandidate
from query_engine.retrieval_router import (
    RetrievalRequest,
    RetrievalTask,
    TaskAwareRetrievalRouter,
)


def _candidate(*, retriever: str = "test") -> EvidenceCandidate:
    return EvidenceCandidate(
        company_id="company-1",
        evidence_type="code_chunk",
        source="test",
        record_id="chunk-1",
        content="source",
        retriever=retriever,
        rank=1,
        repository_id="repo-1",
        snapshot_id="snapshot-1",
        source_revision="revision-1",
        file_path="src/example.py",
        content_hash="abc123",
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=12,
    )


def _router():
    declarations = Mock()
    occurrences = Mock()
    passages = Mock()
    return TaskAwareRetrievalRouter(
        declarations=declarations,
        occurrences=occurrences,
        passages=passages,
    ), declarations, occurrences, passages


def test_declaration_task_routes_only_to_symbol_lexical():
    router, declarations, occurrences, passages = _router()
    expected = [_candidate(retriever="code-symbol-lexical")]
    declarations.retrieve.return_value = expected

    result = router.retrieve(RetrievalRequest(
        task=RetrievalTask.DECLARATION_DISCOVERY,
        company_id="company-1",
        repository_id="repo-1",
        identifiers=("Invoice.calculate_tax",),
    ))

    assert result.strategy == "code-symbol-lexical"
    assert result.candidates == tuple(expected)
    declarations.retrieve.assert_called_once_with(
        company_id="company-1",
        repository_id="repo-1",
        file_paths=(),
        qualified_names=(),
        identifiers=("Invoice.calculate_tax",),
    )
    occurrences.find_references.assert_not_called()
    passages.retrieve.assert_not_called()


def test_passage_task_routes_only_to_source_chunks():
    router, declarations, occurrences, passages = _router()
    expected = [_candidate(retriever="source-chunk-lexical")]
    passages.retrieve.return_value = expected

    result = router.retrieve(RetrievalRequest(
        task=RetrievalTask.PASSAGE_RETRIEVAL,
        company_id="company-1",
        repository_id="repo-1",
        terms=("invoice total",),
    ))

    assert result.strategy == "source-chunk-lexical"
    assert result.candidates == tuple(expected)
    passages.retrieve.assert_called_once_with(
        company_id="company-1",
        repository_id="repo-1",
        terms=["invoice total"],
    )
    declarations.retrieve.assert_not_called()
    occurrences.find_references.assert_not_called()


def test_call_site_uses_exact_scip_references_and_preserves_provenance():
    router, declarations, occurrences, passages = _router()
    occurrences.find_references.return_value = [{
        "occurrence_id": "occ-1",
        "snapshot_id": "snapshot-2",
        "source_revision": "revision-2",
        "file_path": "src/payment.py",
        "content_hash": "hash-2",
        "start_line": 8,
        "end_line": 8,
        "start_byte": 90,
        "end_byte": 104,
        "symbol": "scip-python python pkg Payment.authorize().",
        "role": "reference",
        "symbol_roles": 2,
        "indexer_name": "scip-python",
        "indexer_version": "1.2.3",
        "protocol_version": 1,
    }]

    result = router.retrieve(RetrievalRequest(
        task=RetrievalTask.CALL_SITE_NAVIGATION,
        company_id="company-1",
        repository_id="repo-1",
        scip_symbol="scip-python python pkg Payment.authorize().",
        terms=("authorize",),
    ))

    assert result.strategy == "scip-references"
    assert result.fallback_reason is None
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.evidence_type == "occurrence"
    assert candidate.record_id == "occ-1"
    assert candidate.snapshot_id == "snapshot-2"
    assert candidate.source_revision == "revision-2"
    assert candidate.metadata["role"] == "reference"
    occurrences.find_references.assert_called_once_with(
        company_id="company-1",
        repository_id="repo-1",
        symbol="scip-python python pkg Payment.authorize().",
    )
    passages.retrieve.assert_not_called()
    declarations.retrieve.assert_not_called()


@pytest.mark.parametrize(
    ("symbol", "rows", "reason"),
    [
        (None, [], "exact_scip_symbol_not_provided"),
        ("scip-symbol", [], "no_active_snapshot_references_for_exact_scip_symbol"),
    ],
)
def test_call_site_falls_back_to_lexical_passages(symbol, rows, reason):
    router, declarations, occurrences, passages = _router()
    occurrences.find_references.return_value = rows
    expected = [_candidate(retriever="source-chunk-lexical")]
    passages.retrieve.return_value = expected

    result = router.retrieve(RetrievalRequest(
        task=RetrievalTask.CALL_SITE_NAVIGATION,
        company_id="company-1",
        repository_id="repo-1",
        scip_symbol=symbol,
        terms=("authorize payment",),
    ))

    assert result.strategy == "source-chunk-lexical-fallback"
    assert result.fallback_reason == reason
    assert result.candidates == tuple(expected)
    passages.retrieve.assert_called_once_with(
        company_id="company-1",
        repository_id="repo-1",
        terms=["authorize payment"],
    )
    declarations.retrieve.assert_not_called()


@pytest.mark.parametrize(
    ("company_id", "repository_id"),
    [("", "repo-1"), ("default", "repo-1"), ("company-1", "")],
)
def test_request_rejects_missing_or_placeholder_scope(company_id, repository_id):
    with pytest.raises(ValueError):
        RetrievalRequest(
            task=RetrievalTask.PASSAGE_RETRIEVAL,
            company_id=company_id,
            repository_id=repository_id,
        )


def test_request_rejects_untyped_task():
    with pytest.raises(ValueError, match="RetrievalTask"):
        RetrievalRequest(
            task="guess_from_natural_language",  # type: ignore[arg-type]
            company_id="company-1",
            repository_id="repo-1",
        )

"""Tests for conservative descriptive declaration candidate discovery."""
from query_engine.evidence import EvidenceCandidate
from query_engine.query_plan import QueryIntent, QueryPlan, QueryScope
from query_engine.target_discovery import DescriptiveSymbolCandidateRetriever


def _chunk(file_path, content, start_line=1, end_line=30):
    return EvidenceCandidate(
        company_id="company-a",
        evidence_type="code_chunk",
        source="source-code-chunks",
        record_id=f"chunk-{file_path}",
        content=content,
        retriever="source-chunk-lexical",
        rank=1,
        repository_id="repo-a",
        snapshot_id="snapshot-a",
        source_revision="revision-a",
        file_path=file_path,
        content_hash="a" * 64,
        start_line=start_line,
        end_line=end_line,
        start_byte=0,
        end_byte=len(content.encode("utf-8")),
    )


class _Chunks:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return self.chunks


class _Symbols:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def list_file_symbols(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows.get(kwargs["file_path"], [])


def _row(name, qualified, path, start=1, end=12, kind="function"):
    return {
        "symbol_id": f"symbol-{qualified}",
        "name": name,
        "qualified_name": qualified,
        "file_path": path,
        "start_line": start,
        "end_line": end,
        "start_byte": 0,
        "end_byte": 100,
        "kind": kind,
    }


def _plan(query, terms, intent=QueryIntent.DECLARATION_DISCOVERY):
    return QueryPlan(
        query=query,
        intent=intent,
        scope=QueryScope(company_id="company-a", repository_id="repo-a"),
        terms=tuple(terms),
    )


def test_discovery_ranks_declaration_using_name_and_local_source_context():
    chunks = _Chunks([
        _chunk(
            "catalog/products.py",
            'class ProductCatalog:\n'
            '    """Provides availability and reservation operations."""\n'
            '    def find_available(self, sku):\n'
            '        """Check whether a product can be purchased."""\n'
            '        return sku in self.available_skus\n',
        )
    ])
    symbols = _Symbols({
        "catalog/products.py": [
            _row("ProductCatalog", "ProductCatalog", "catalog/products.py", 1, 5, "class"),
            _row("find_available", "ProductCatalog.find_available",
                 "catalog/products.py", 3, 5),
        ]
    })
    retriever = DescriptiveSymbolCandidateRetriever(
        source_chunks=chunks, symbols=symbols,
    )

    result = retriever.discover(_plan(
        "Where is product availability checked?",
        ["product", "availability", "checked"],
    ))

    assert result.discovered
    assert result.selected.declaration["name"] == "find_available"
    assert "availability" in result.selected.matched_terms
    assert chunks.calls == [{
        "company_id": "company-a",
        "repository_id": "repo-a",
        "terms": ["product", "availability", "checked"],
    }]
    assert symbols.calls == [{
        "company_id": "company-a",
        "repository_id": "repo-a",
        "file_path": "catalog/products.py",
    }]


def test_discovery_abstains_when_two_declarations_have_equal_support():
    source = (
        "def check_primary_availability(product):\n"
        "    return product.available\n\n"
        "def check_secondary_availability(product):\n"
        "    return product.available\n"
    )
    chunks = _Chunks([_chunk("catalog/availability.py", source, 1, 6)])
    symbols = _Symbols({
        "catalog/availability.py": [
            _row("check_primary_availability", "check_primary_availability",
                 "catalog/availability.py", 1, 2),
            _row("check_secondary_availability", "check_secondary_availability",
                 "catalog/availability.py", 4, 5),
        ]
    })
    retriever = DescriptiveSymbolCandidateRetriever(
        source_chunks=chunks, symbols=symbols,
    )

    result = retriever.discover(_plan(
        "Where is product availability checked?",
        ["product", "availability", "checked"],
    ))

    assert not result.discovered
    assert result.reason == "ambiguous_descriptive_symbol_candidates"
    assert len(result.candidates) == 2


def test_discovery_does_not_invent_candidates_when_source_has_no_match():
    chunks = _Chunks([
        _chunk("billing/payment.py", "def capture_payment(payment):\n    return payment\n")
    ])
    symbols = _Symbols({
        "billing/payment.py": [
            _row("capture_payment", "capture_payment", "billing/payment.py"),
        ]
    })
    retriever = DescriptiveSymbolCandidateRetriever(
        source_chunks=chunks, symbols=symbols,
    )

    result = retriever.discover(_plan(
        "Where is SKU normalization implemented?",
        ["SKU", "normalization", "implemented"],
    ))

    assert not result.discovered
    assert result.reason == "no_descriptive_symbol_candidate"


def test_discovery_rejects_evidence_from_another_tenant_or_repository():
    foreign = _chunk("catalog/products.py", "availability checked product")
    foreign = EvidenceCandidate(
        company_id="company-b",
        evidence_type="code_chunk",
        source=foreign.source,
        record_id=foreign.record_id,
        content=foreign.content,
        retriever=foreign.retriever,
        rank=foreign.rank,
        repository_id=foreign.repository_id,
        snapshot_id=foreign.snapshot_id,
        source_revision=foreign.source_revision,
        file_path=foreign.file_path,
        content_hash=foreign.content_hash,
        start_line=foreign.start_line,
        end_line=foreign.end_line,
        start_byte=foreign.start_byte,
        end_byte=foreign.end_byte,
    )
    chunks = _Chunks([foreign])
    symbols = _Symbols({})
    retriever = DescriptiveSymbolCandidateRetriever(
        source_chunks=chunks, symbols=symbols,
    )

    result = retriever.discover(_plan(
        "Where is product availability checked?",
        ["product", "availability", "checked"],
    ))

    assert not result.discovered
    assert result.reason == "no_descriptive_symbol_candidate"
    assert symbols.calls == []


def test_discovery_requires_supported_navigation_intent_and_repository_scope():
    chunks = _Chunks([])
    symbols = _Symbols({})
    retriever = DescriptiveSymbolCandidateRetriever(
        source_chunks=chunks, symbols=symbols,
    )

    unsupported = retriever.discover(_plan(
        "Explain availability", ["availability"], QueryIntent.PASSAGE_RETRIEVAL,
    ))
    no_scope = retriever.discover(QueryPlan(
        query="Where is availability checked?",
        intent=QueryIntent.DECLARATION_DISCOVERY,
        scope=QueryScope(company_id="company-a"),
        terms=("availability", "checked"),
    ))

    assert unsupported.reason == "intent_not_supported"
    assert no_scope.reason == "repository_scope_required"
    assert chunks.calls == []

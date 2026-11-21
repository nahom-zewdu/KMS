"""Tests for snapshot-scoped lexical declaration retrieval."""

from query_engine import code_lexical


def _row(
    symbol_id="symbol-a",
    qualified_name="PaymentService.charge",
    file_path="src/payments/service.py",
    start_byte=100,
):
    return {
        "symbol_id": symbol_id,
        "qualified_name": qualified_name,
        "name": qualified_name.split(".")[-1],
        "kind": "method",
        "language": "Python",
        "file_path": file_path,
        "snapshot_id": "snapshot-a",
        "source_revision": "revision-a",
        "content_hash": "a" * 64 if symbol_id == "symbol-a" else "b" * 64,
        "start_line": 10,
        "end_line": 12,
        "start_byte": start_byte,
        "end_byte": start_byte + 40,
        "extractor_version": "tree-sitter-v1",
    }


class FakeSymbols:
    def __init__(self, _supabase, *, max_results):
        self.max_results = max_results
        self.calls = []
        self.charge = _row()
        self.retry = _row(
            symbol_id="symbol-b",
            qualified_name="RetryPolicy.should_retry",
            file_path="src/payments/retry.py",
            start_byte=20,
        )

    def find_qualified_name(self, **kwargs):
        self.calls.append(("qualified", kwargs))
        return [self.charge] if kwargs["qualified_name"] == "PaymentService.charge" else []

    def list_file_symbols(self, **kwargs):
        self.calls.append(("path", kwargs))
        return [self.charge] if kwargs["file_path"] == "src/payments/service.py" else []

    def search_names(self, **kwargs):
        self.calls.append(("identifier", kwargs))
        return [self.charge, self.retry] if kwargs["term"] == "charge" else []


def test_lexical_retrieval_deduplicates_and_preserves_match_modes(monkeypatch):
    fake = FakeSymbols(None, max_results=10)
    monkeypatch.setattr(code_lexical, "CodeSymbolRetriever", lambda *_args, **_kwargs: fake)
    retriever = code_lexical.CodeLexicalRetriever(object(), top_k=10)

    candidates = retriever.retrieve(
        company_id="company-a",
        repository_id="repo-a",
        qualified_names=["PaymentService.charge"],
        file_paths=["src/payments/service.py"],
        identifiers=["charge"],
    )

    assert [candidate.record_id for candidate in candidates] == ["symbol-a", "symbol-b"]
    assert [candidate.rank for candidate in candidates] == [1, 2]
    assert candidates[0].metadata["match_modes"] == [
        "qualified_name", "file_path", "identifier"
    ]
    assert candidates[1].metadata["match_modes"] == ["identifier"]
    assert candidates[0].snapshot_id == "snapshot-a"
    assert candidates[0].source_revision == "revision-a"
    assert all(candidate.company_id == "company-a" for candidate in candidates)
    assert all(candidate.repository_id == "repo-a" for candidate in candidates)


def test_lexical_retrieval_uses_company_and_repository_scope(monkeypatch):
    fake = FakeSymbols(None, max_results=10)
    monkeypatch.setattr(code_lexical, "CodeSymbolRetriever", lambda *_args, **_kwargs: fake)
    retriever = code_lexical.CodeLexicalRetriever(object())

    retriever.retrieve(
        company_id="company-a",
        repository_id="repo-a",
        qualified_names=["PaymentService.charge"],
    )

    assert fake.calls == [
        (
            "qualified",
            {
                "company_id": "company-a",
                "repository_id": "repo-a",
                "qualified_name": "PaymentService.charge",
            },
        )
    ]


def test_lexical_retrieval_rejects_invalid_tenant_before_database_access(monkeypatch):
    fake = FakeSymbols(None, max_results=10)
    monkeypatch.setattr(code_lexical, "CodeSymbolRetriever", lambda *_args, **_kwargs: fake)
    retriever = code_lexical.CodeLexicalRetriever(object())

    try:
        retriever.retrieve(
            company_id="default",
            repository_id="repo-a",
            identifiers=["charge"],
        )
    except ValueError as exc:
        assert "company_id" in str(exc)
    else:
        raise AssertionError("invalid company scope was accepted")

    assert fake.calls == []

def test_lexical_retrieval_returns_no_candidates_without_search_terms(monkeypatch):
    fake = FakeSymbols(None, max_results=10)
    monkeypatch.setattr(code_lexical, "CodeSymbolRetriever", lambda *_args, **_kwargs: fake)
    retriever = code_lexical.CodeLexicalRetriever(object())

    assert retriever.retrieve(
        company_id="company-a",
        repository_id="repo-a",
    ) == []
    assert fake.calls == []

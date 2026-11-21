"""Tests for snapshot-scoped SCIP occurrence persistence and retrieval."""

import pytest

from codebase.scip_indexer import ScipIndex, ScipOccurrence
from codebase.scip_occurrence_indexer import ScipOccurrenceIndexer
from codebase.scip_occurrence_retriever import ScipOccurrenceRetriever


class FakeResponse:
    def __init__(self, data=None):
        self.data = data or []


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.filters = {}
        self.orders = []
        self.payload = None
        self.conflict = None
        self.limit_value = None

    def select(self, _columns):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, key):
        self.orders.append(key)
        return self

    def in_(self, key, values):
        self.filters[key] = values
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def upsert(self, payload, *, on_conflict):
        self.payload = payload
        self.conflict = on_conflict
        return self

    def execute(self):
        self.client.calls.append(self)
        if self.payload is not None:
            return FakeResponse(self.payload)
        return FakeResponse(self.client.responses.get(self.table_name, []))


class FakeSupabase:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, name, params):
        query = FakeQuery(self, name)
        query.payload = params
        return query


def _occurrence(identity: str, *, role="reference", revision="revision-a", path="src/a.py"):
    return ScipOccurrence(
        occurrence_id=identity * 64,
        file_path=path,
        symbol="scip-python python pkg/a.py/normalize().",
        role=role,
        symbol_roles=1 if role == "definition" else 8,
        start_line=1,
        end_line=1,
        start_byte=0,
        end_byte=9,
        content_hash="c" * 64,
        source_revision=revision,
        indexer_name="scip-python",
        indexer_version="0.6.8",
        protocol_version=1,
    )


def _index(*occurrences):
    return ScipIndex(
        indexer_name="scip-python",
        indexer_version="0.6.8",
        protocol_version=1,
        occurrences=tuple(occurrences),
    )


def test_persists_bounded_idempotent_batches_with_scope():
    client = FakeSupabase()
    indexer = ScipOccurrenceIndexer(client, batch_size=2)
    result = indexer.persist(
        _index(
            _occurrence("a", role="definition"),
            _occurrence("b", path="src/b.py"),
            _occurrence("c", path="src/c.py"),
        ),
        repository_id="repo-1",
        snapshot_id="snapshot-1",
        company_id="company-a",
        source_revision="revision-a",
    )

    upserts = [call for call in client.calls if call.table_name == "code_symbol_occurrences"]
    refreshes = [call for call in client.calls if call.table_name == "refresh_snapshot_occurrence_validation"]
    assert [len(call.payload) for call in upserts] == [2, 1]
    assert all(call.conflict == "snapshot_id,occurrence_id" for call in upserts)
    assert all(row["company_id"] == "company-a" for call in upserts for row in call.payload)
    assert len(refreshes) == 1
    assert refreshes[0].payload == {
        "p_snapshot_id": "snapshot-1",
        "p_company_id": "company-a",
    }
    assert result == {
        "occurrences_seen": 3,
        "occurrences_persisted": 3,
        "definitions": 1,
        "references": 2,
        "other_occurrences": 0,
        "files_with_occurrences": 3,
    }


def test_empty_index_is_a_valid_noop():
    client = FakeSupabase()
    result = ScipOccurrenceIndexer(client).persist(
        _index(),
        repository_id="repo-1",
        snapshot_id="snapshot-1",
        company_id="company-a",
        source_revision="revision-a",
    )
    assert result["occurrences_persisted"] == 0
    assert client.calls == []


def test_rejects_occurrence_from_different_source_revision_before_writing():
    client = FakeSupabase()
    with pytest.raises(ValueError, match="source revision"):
        ScipOccurrenceIndexer(client).persist(
            _index(_occurrence("a", revision="revision-b")),
            repository_id="repo-1",
            snapshot_id="snapshot-1",
            company_id="company-a",
            source_revision="revision-a",
        )
    assert client.calls == []


def test_rejects_duplicate_occurrence_identity():
    client = FakeSupabase()
    with pytest.raises(ValueError, match="duplicate"):
        ScipOccurrenceIndexer(client).persist(
            _index(_occurrence("a"), _occurrence("a")),
            repository_id="repo-1",
            snapshot_id="snapshot-1",
            company_id="company-a",
            source_revision="revision-a",
        )
    assert client.calls == []


def test_rejects_default_tenant_scope():
    with pytest.raises(ValueError, match="company_id"):
        ScipOccurrenceIndexer(FakeSupabase()).persist(
            _index(),
            repository_id="repo-1",
            snapshot_id="snapshot-1",
            company_id="default",
            source_revision="revision-a",
        )


def test_retriever_scopes_symbol_navigation_to_active_snapshot():
    client = FakeSupabase({
        "repositories": [{"active_snapshot_id": "snapshot-current"}],
        "code_symbol_occurrences": [{"symbol": "scip-symbol", "role": "definition"}],
    })
    retriever = ScipOccurrenceRetriever(client)
    rows = retriever.find_definitions(
        company_id="company-a",
        repository_id="repo-1",
        symbol="scip-symbol",
    )

    assert rows[0]["role"] == "definition"
    repository_query, occurrence_query = client.calls
    assert repository_query.filters == {"id": "repo-1", "company_id": "company-a"}
    assert occurrence_query.filters == {
        "company_id": "company-a",
        "repository_id": "repo-1",
        "snapshot_id": "snapshot-current",
        "symbol": "scip-symbol",
        "role": "definition",
    }


def test_retriever_returns_empty_when_repository_has_no_active_snapshot():
    client = FakeSupabase({"repositories": []})
    rows = ScipOccurrenceRetriever(client).find_symbol(
        company_id="company-a",
        repository_id="repo-1",
        symbol="scip-symbol",
    )
    assert rows == []
    assert len(client.calls) == 1


def test_retriever_treats_non_definition_scip_occurrences_as_references():
    client = FakeSupabase({
        "repositories": [{"active_snapshot_id": "snapshot-current"}],
        "code_symbol_occurrences": [
            {"symbol": "scip-symbol", "role": "reference"},
            {"symbol": "scip-symbol", "role": "occurrence"},
        ],
    })
    rows = ScipOccurrenceRetriever(client).find_references(
        company_id="company-a",
        repository_id="repo-1",
        symbol="scip-symbol",
    )
    assert len(rows) == 2
    assert client.calls[1].filters["role"] == ["reference", "occurrence"]

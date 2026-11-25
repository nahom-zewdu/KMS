"""Tests for tenant- and active-snapshot-scoped source chunk retrieval."""
from types import SimpleNamespace

from codebase.source_chunk_retriever import SourceChunkRetriever


class Query:
    def __init__(self, db, table):
        self.db, self.table_name = db, table
        self.filters, self.maximum = [], None

    def select(self, _):
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def ilike(self, key, value):
        self.filters.append(("ilike", key, value))
        return self

    def order(self, *_):
        return self

    def limit(self, value):
        self.maximum = value
        return self

    def execute(self):
        rows = self.db.rows.get(self.table_name, [])
        for op, key, value in self.filters:
            if op == "eq":
                rows = [row for row in rows if row.get(key) == value]
            else:
                needle = value.strip("%").replace("\\_", "_").replace("\\%", "%").casefold()
                rows = [row for row in rows if needle in str(row.get(key, "")).casefold()]
        return SimpleNamespace(data=rows[: self.maximum])


class Database:
    def __init__(self):
        self.rows = {
            "repositories": [
                {"id": "repo-a", "company_id": "company-a", "active_snapshot_id": "snap-new"},
                {"id": "repo-b", "company_id": "company-b", "active_snapshot_id": "snap-other"},
            ],
            "source_code_chunks": [
                self.chunk("chunk-new", "company-a", "repo-a", "snap-new", "new revision"),
                self.chunk("chunk-old", "company-a", "repo-a", "snap-old", "new revision"),
                self.chunk("chunk-other", "company-b", "repo-b", "snap-other", "new revision"),
            ],
        }

    @staticmethod
    def chunk(chunk_id, company, repo, snapshot, content):
        return {
            "chunk_id": chunk_id, "company_id": company, "repository_id": repo,
            "snapshot_id": snapshot, "source_revision": "rev-new",
            "file_path": "src/service.py", "content": content,
            "content_hash": "a" * 64, "source_content_hash": "b" * 64,
            "start_line": 1, "end_line": 1, "start_byte": 0,
            "end_byte": len(content.encode()), "chunk_index": 0,
            "chunker_version": "line-window-v1",
        }

    def table(self, name):
        return Query(self, name)


def test_retriever_returns_only_active_snapshot_evidence_with_provenance():
    retriever = SourceChunkRetriever(Database())
    result = retriever.retrieve(
        company_id="company-a", repository_id="repo-a", terms=["revision"],
    )
    assert len(result) == 1
    candidate = result[0]
    assert candidate.record_id == "chunk-new"
    assert candidate.snapshot_id == "snap-new"
    assert candidate.source_revision == "rev-new"
    assert candidate.evidence_type == "code_chunk"
    assert candidate.file_path == "src/service.py"
    assert candidate.evidence_id


def test_retriever_returns_empty_for_wrong_tenant_or_missing_terms():
    retriever = SourceChunkRetriever(Database())
    assert retriever.retrieve(
        company_id="company-a", repository_id="repo-b", terms=["revision"],
    ) == []
    assert retriever.retrieve(
        company_id="company-a", repository_id="repo-a", terms=[],
    ) == []

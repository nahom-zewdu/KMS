"""Opt-in lexical retrieval benchmark over KMS's real Python implementation.

This is a repository-specific baseline, not a semantic or production-quality
claim. It indexes the checked-out codebase/query_engine modules with the real
indexers and retrievers, while an in-memory PostgREST double isolates retrieval
behavior from database/RLS performance.
"""
from __future__ import annotations

from pathlib import Path
from statistics import mean
from types import SimpleNamespace

import pytest

from codebase.source_chunk_indexer import SourceChunkIndexer
from codebase.source_chunk_retriever import SourceChunkRetriever
from codebase.source_chunker import SourceChunker
from codebase.symbol_indexer import CodeSymbolIndexer
from query_engine.code_lexical import CodeLexicalRetriever

pytestmark = pytest.mark.skipif(
    __import__("os").getenv("KMS_NLP_REPOSITORY_BENCHMARK") != "1",
    reason="set KMS_NLP_REPOSITORY_BENCHMARK=1 to run the real-repository benchmark",
)

_NLP_ROOT = Path(__file__).resolve().parents[1]
_COMPANY_ID = "kms-repository-benchmark-company"
_REPOSITORY_ID = "kms-repository-benchmark-repository"
_SNAPSHOT_ID = "kms-repository-benchmark-snapshot"
_SOURCE_REVISION = "working-tree-benchmark"


class MemoryQuery:
    """Minimal PostgREST behavior used by the production indexers/retrievers."""

    def __init__(self, database, table):
        self.database = database
        self.table_name = table
        self.filters = []
        self.orders = []
        self.maximum = None
        self.upsert_rows = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def ilike(self, column, pattern):
        self.filters.append(("ilike", column, pattern))
        return self

    def order(self, column):
        self.orders.append(column)
        return self

    def limit(self, maximum):
        self.maximum = maximum
        return self

    def upsert(self, rows, **_kwargs):
        self.upsert_rows = rows
        return self

    def execute(self):
        rows = self.database.rows.setdefault(self.table_name, [])
        if self.upsert_rows is not None:
            key_fields = (
                ("snapshot_id", "symbol_id")
                if self.table_name == "code_symbols"
                else ("snapshot_id", "chunk_id")
            )
            positions = {
                tuple(row.get(key) for key in key_fields): index
                for index, row in enumerate(rows)
            }
            for row in self.upsert_rows:
                key = tuple(row.get(field) for field in key_fields)
                if key in positions:
                    rows[positions[key]] = dict(row)
                else:
                    positions[key] = len(rows)
                    rows.append(dict(row))
            return SimpleNamespace(data=[])

        selected = list(rows)
        for operator, column, value in self.filters:
            if operator == "eq":
                selected = [row for row in selected if row.get(column) == value]
            else:
                # Sufficient for this fixture: terms are literal, not SQL patterns.
                needle = value[1:-1].replace("\\\\", "\\")
                needle = needle.replace("\\%", "%").replace("\\_", "_")
                selected = [
                    row for row in selected
                    if needle.casefold() in str(row.get(column) or "").casefold()
                ]
        for column in reversed(self.orders):
            selected.sort(
                key=lambda row: (
                    row.get(column) is None,
                    row.get(column) if row.get(column) is not None else 0,
                )
            )
        if self.maximum is not None:
            selected = selected[:self.maximum]
        return SimpleNamespace(data=selected)


class MemorySupabase:
    """One benchmark tenant and one active snapshot."""

    def __init__(self):
        self.rows = {
            "repositories": [{
                "id": _REPOSITORY_ID,
                "company_id": _COMPANY_ID,
                "active_snapshot_id": _SNAPSHOT_ID,
            }],
            "code_symbols": [],
            "source_code_chunks": [],
        }

    def table(self, name):
        return MemoryQuery(self, name)


# Questions are written in task language; terms remain explicit lexical signals.
# Expected paths were manually selected from the implementation being evaluated.
_PASSAGE_QUERIES = [
    {
        "id": "repo-01-chunk-bounds",
        "question": "Where are source size and chunk size limits enforced?",
        "terms": ["SourceChunkingError", "max_chunk_bytes"],
        "expected_ranges": [{"file_path": "codebase/source_chunker.py", "start_line": 86, "end_line": 98}],
    },
    {
        "id": "repo-02-chunk-persistence",
        "question": "How are source chunks persisted idempotently for a snapshot?",
        "terms": ["on_conflict", "chunk_id", "source_code_chunks"],
        "expected_ranges": [{"file_path": "codebase/source_chunk_indexer.py", "start_line": 53, "end_line": 77}],
    },
    {
        "id": "repo-03-active-chunk-retrieval",
        "question": "How does passage retrieval restrict results to the active snapshot?",
        "terms": ["rows_by_id", "matched_terms", "source_code_chunks"],
        "expected_ranges": [{"file_path": "codebase/source_chunk_retriever.py", "start_line": 34, "end_line": 64}],
    },
    {
        "id": "repo-04-symbol-lookup",
        "question": "Where are declarations searched by qualified name and identifier?",
        "terms": ["find_qualified_name", "search_names", "active_snapshot_id"],
        "expected_ranges": [
            {"file_path": "codebase/symbol_retriever.py", "start_line": 17, "end_line": 38},
            {"file_path": "codebase/symbol_retriever.py", "start_line": 63, "end_line": 87},
        ],
    },
    {
        "id": "repo-05-lexical-evidence",
        "question": "How are declaration matches converted into provenance-aware candidates?",
        "terms": ["match_modes", "EvidenceCandidate", "qualified_name"],
        "expected_ranges": [{"file_path": "query_engine/code_lexical.py", "start_line": 121, "end_line": 161}],
    },
    {
        "id": "repo-06-evidence-identity",
        "question": "How is stable identity calculated for source evidence?",
        "terms": ["evidence_id", "content_hash", "start_byte"],
        "expected_ranges": [{"file_path": "query_engine/evidence.py", "start_line": 83, "end_line": 105}],
    },
    {
        "id": "repo-07-scip-references",
        "question": "Where can callers retrieve SCIP references for an exact symbol?",
        "terms": ["find_references", "ScipOccurrenceRetriever", "reference"],
        "expected_ranges": [{"file_path": "codebase/scip_occurrence_retriever.py", "start_line": 31, "end_line": 60}],
    },
    {
        "id": "repo-08-baseline-indexing",
        "question": "Where does baseline ingestion connect repository indexing to source chunks?",
        "terms": ["SourceChunkIndexer", "source_chunk_indexer"],
        "expected_ranges": [{"file_path": "codebase/baseline.py", "start_line": 587, "end_line": 655}],
    },
    {
        "id": "repo-09-symbol-indexing",
        "question": "How are extracted declarations batch-upserted into code_symbols?",
        "terms": ["CodeSymbolExtractor", "code_symbols", "symbols_persisted"],
        "expected_ranges": [{"file_path": "codebase/symbol_indexer.py", "start_line": 115, "end_line": 127}],
    },
    {
        "id": "repo-10-chunk-provenance",
        "question": "Where are UTF-8 byte offsets and one-based source line ranges generated?",
        "terms": ["encoded_lines", "start_byte", "end_byte"],
        "expected_ranges": [{"file_path": "codebase/source_chunker.py", "start_line": 100, "end_line": 149}],
    },
]
_NO_EVIDENCE_TERMS = ["quasar_telemetry_zygomorphic_94821"]


def _scope(candidate):
    assert candidate.company_id == _COMPANY_ID
    assert candidate.repository_id == _REPOSITORY_ID
    assert candidate.snapshot_id == _SNAPSHOT_ID
    assert candidate.source_revision == _SOURCE_REVISION
    assert candidate.file_path


def _source_files():
    roots = (_NLP_ROOT / "codebase", _NLP_ROOT / "query_engine")
    files = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            files.append({
                "path": path.relative_to(_NLP_ROOT).as_posix(),
                "content": path.read_text(encoding="utf-8"),
            })
    return files


def test_real_kms_python_repository_lexical_retrieval_benchmark():
    source_files = _source_files()
    assert len(source_files) >= 15, f"unexpectedly small corpus: {len(source_files)} files"

    database = MemorySupabase()
    symbol_metrics = CodeSymbolIndexer(database).index_files(
        source_files,
        repository_id=_REPOSITORY_ID,
        snapshot_id=_SNAPSHOT_ID,
        company_id=_COMPANY_ID,
        source_revision=_SOURCE_REVISION,
    )
    chunk_metrics = SourceChunkIndexer(
        database,
        chunker=SourceChunker(
            max_source_bytes=1_000_000,
            max_chunk_bytes=6_000,
            max_lines=30,
            overlap_lines=5,
            chunker_version="kms-repository-benchmark-v1",
        ),
    ).index_files(
        source_files,
        repository_id=_REPOSITORY_ID,
        snapshot_id=_SNAPSHOT_ID,
        company_id=_COMPANY_ID,
        source_revision=_SOURCE_REVISION,
    )
    assert symbol_metrics["files_indexed"] >= 15
    assert chunk_metrics["files_indexed"] == len(source_files)
    assert chunk_metrics["chunks_persisted"] > len(source_files)

    chunk_retriever = SourceChunkRetriever(database, max_results=300)
    query_results = []
    for query in _PASSAGE_QUERIES:
        candidates = chunk_retriever.retrieve(
            company_id=_COMPANY_ID,
            repository_id=_REPOSITORY_ID,
            terms=query["terms"],
        )
        for candidate in candidates:
            _scope(candidate)
        expected_range_ranks = []
        for expected in query["expected_ranges"]:
            matching_ranks = [
                candidate.rank
                for candidate in candidates
                if candidate.file_path == expected["file_path"]
                and candidate.start_line <= expected["end_line"]
                and candidate.end_line >= expected["start_line"]
            ]
            expected_range_ranks.append(
                min(matching_ranks) if matching_ranks else None
            )
        relevant_ranks = [
            rank for rank in expected_range_ranks if rank is not None
        ]
        query_results.append({
            "id": query["id"],
            "question": query["question"],
            "expected_ranges": query["expected_ranges"],
            "expected_range_ranks": expected_range_ranks,
            "matched_expected_ranges": len(relevant_ranks),
            "total_expected_ranges": len(expected_range_ranks),
            "first_relevant_rank": min(relevant_ranks) if relevant_ranks else None,
            "top_results": [{
                "rank": candidate.rank,
                "file_path": candidate.file_path,
                "line_range": [candidate.start_line, candidate.end_line],
                "matched_terms": candidate.metadata["match_terms"],
            } for candidate in candidates[:5]],
        })

    no_evidence = chunk_retriever.retrieve(
        company_id=_COMPANY_ID,
        repository_id=_REPOSITORY_ID,
        terms=_NO_EVIDENCE_TERMS,
    )
    assert not no_evidence

    reciprocal_ranks = [
        1.0 / item["first_relevant_rank"]
        for item in query_results
        if item["first_relevant_rank"] is not None
    ]
    report = {
        "corpus": {
            "files": len(source_files),
            "symbols_persisted": symbol_metrics["symbols_persisted"],
            "chunks_persisted": chunk_metrics["chunks_persisted"],
            "files_with_symbol_syntax_errors": symbol_metrics["files_with_syntax_errors"],
        },
        "evaluation": {
            "queries": len(query_results),
            "queries_with_relevant_results": len(reciprocal_ranks),
            "expected_ranges": sum(item["total_expected_ranges"] for item in query_results),
            "matched_expected_ranges": sum(item["matched_expected_ranges"] for item in query_results),
            "range_recall_at_1": sum(
                rank == 1
                for item in query_results
                for rank in item["expected_range_ranks"]
            ) / sum(item["total_expected_ranges"] for item in query_results),
            "range_recall_at_5": sum(
                rank is not None and rank <= 5
                for item in query_results
                for rank in item["expected_range_ranks"]
            ) / sum(item["total_expected_ranges"] for item in query_results),
            "range_recall_at_10": sum(
                rank is not None and rank <= 10
                for item in query_results
                for rank in item["expected_range_ranks"]
            ) / sum(item["total_expected_ranges"] for item in query_results),
            "complete_query_recall_at_1": mean(
                all(rank == 1 for rank in item["expected_range_ranks"])
                for item in query_results
            ),
            "complete_query_recall_at_5": mean(
                all(rank is not None and rank <= 5 for rank in item["expected_range_ranks"])
                for item in query_results
            ),
            "complete_query_recall_at_10": mean(
                all(rank is not None and rank <= 10 for rank in item["expected_range_ranks"])
                for item in query_results
            ),
            "recall_at_1": mean(
                item["first_relevant_rank"] == 1 for item in query_results
            ),
            "recall_at_5": mean(
                item["first_relevant_rank"] is not None
                and item["first_relevant_rank"] <= 5
                for item in query_results
            ),
            "recall_at_10": mean(
                item["first_relevant_rank"] is not None
                and item["first_relevant_rank"] <= 10
                for item in query_results
            ),
            "mrr": mean(reciprocal_ranks) if reciprocal_ranks else 0.0,
            "no_evidence_candidates": len(no_evidence),
        },
        "query_results": query_results,
    }
    print(__import__("json").dumps(report, indent=2, sort_keys=True))

    assert len(query_results) == 10
    assert report["evaluation"]["queries_with_relevant_results"] >= 8
    assert report["evaluation"]["no_evidence_candidates"] == 0

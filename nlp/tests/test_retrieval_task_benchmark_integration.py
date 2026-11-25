"""Task-separated retrieval evaluation over the versioned mini repository fixture.

Uses the real symbol/chunk indexers and retrievers with an in-memory
PostgREST double. This measures deterministic retrieval behavior, not database
query planning, RLS, or production repository quality.
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from types import SimpleNamespace

from codebase.source_chunk_indexer import SourceChunkIndexer
from codebase.source_chunk_retriever import SourceChunkRetriever
from codebase.source_chunker import SourceChunker
from codebase.symbol_indexer import CodeSymbolIndexer
from query_engine.code_lexical import CodeLexicalRetriever

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "retrieval"
_REPOSITORY_ROOT = _FIXTURE_ROOT / "mini_repo_v2"
_BENCHMARK_PATH = _FIXTURE_ROOT / "retrieval_tasks_v1.json"
_COMPANY_ID = "benchmark-company"
_REPOSITORY_ID = "benchmark-repository"
_SNAPSHOT_ID = "benchmark-snapshot-v1"
_SOURCE_REVISION = "benchmark-revision-v1"


class MemoryQuery:
    """Small PostgREST subset required by the production indexers/retrievers."""

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
                # Fixture terms are literal strings; this is not a SQL LIKE emulator.
                needle = value[1:-1].replace("\\\\", "\\")
                needle = needle.replace("\\%", "%").replace("\\_", "_")
                selected = [
                    row for row in selected
                    if needle.casefold() in str(row.get(column) or "").casefold()
                ]
        for column in reversed(self.orders):
            # Preserve native column types (e.g. integer line/byte offsets).
            # Keep NULL values last.
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
    """One tenant and one active snapshot for the synthetic repository."""

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


def _scope(candidate):
    assert candidate.company_id == _COMPANY_ID
    assert candidate.repository_id == _REPOSITORY_ID
    assert candidate.snapshot_id == _SNAPSHOT_ID
    assert candidate.source_revision == _SOURCE_REVISION


def _metrics(query_results, expected_key, cutoffs=(1, 5, 10)):
    evaluated = [item for item in query_results if item["relevant_count"] > 0]
    result = {
        "evaluated_queries": len(evaluated),
        "no_evidence_queries": len(query_results) - len(evaluated),
    }
    for cutoff in cutoffs:
        result[f"recall_at_{cutoff}"] = mean(
            item[f"recall_at_{cutoff}"] for item in evaluated
        ) if evaluated else 0.0
    result["mrr"] = mean(
        item["reciprocal_rank"] for item in evaluated
    ) if evaluated else 0.0
    return result


def _score_ranges(retriever, queries):
    results = []
    for query in queries:
        candidates = retriever.retrieve(
            company_id=_COMPANY_ID,
            repository_id=_REPOSITORY_ID,
            terms=query["terms"],
        )
        for candidate in candidates:
            _scope(candidate)
        expected = query["expected_ranges"]
        hit_ranks = []
        for label in expected:
            matching = [
                candidate.rank for candidate in candidates
                if candidate.file_path == label["file_path"]
                and candidate.start_line <= label["end_line"]
                and candidate.end_line >= label["start_line"]
            ]
            if matching:
                hit_ranks.append(min(matching))
        result = {
            "query_id": query["id"],
            "relevant_count": len(expected),
            "retrieved_relevant_ranks": sorted(hit_ranks),
            "ranking": [{
                "rank": candidate.rank,
                "file_path": candidate.file_path,
                "start_line": candidate.start_line,
                "end_line": candidate.end_line,
                "matched_terms": candidate.metadata["match_terms"],
            } for candidate in candidates],
            "reciprocal_rank": 1.0 / min(hit_ranks) if hit_ranks else 0.0,
        }
        for cutoff in (1, 5, 10):
            result[f"recall_at_{cutoff}"] = (
                sum(rank <= cutoff for rank in hit_ranks) / len(expected)
                if expected else 0.0
            )
        results.append(result)
    return {
        "metrics": _metrics(results, "expected_ranges"),
        "query_results": results,
    }


def _score_declarations(retriever, queries):
    results = []
    for query in queries:
        candidates = retriever.retrieve(
            company_id=_COMPANY_ID,
            repository_id=_REPOSITORY_ID,
            identifiers=query["terms"],
        )
        for candidate in candidates:
            _scope(candidate)
        expected_symbols = query["expected_symbols"]
        hit_ranks = []
        for symbol in expected_symbols:
            matching = [
                candidate.rank for candidate in candidates
                if candidate.metadata.get("name") == symbol
            ]
            if matching:
                hit_ranks.append(min(matching))
        result = {
            "query_id": query["id"],
            "expected_symbols": expected_symbols,
            "relevant_count": len(expected_symbols),
            "retrieved_relevant_ranks": sorted(hit_ranks),
            "ranking": [{
                "rank": candidate.rank,
                "name": candidate.metadata.get("name"),
                "qualified_name": candidate.metadata.get("qualified_name"),
                "file_path": candidate.file_path,
            } for candidate in candidates],
            "reciprocal_rank": 1.0 / min(hit_ranks) if hit_ranks else 0.0,
        }
        for cutoff in (1, 5, 10):
            result[f"recall_at_{cutoff}"] = (
                sum(rank <= cutoff for rank in hit_ranks) / len(expected_symbols)
                if expected_symbols else 0.0
            )
        results.append(result)
    return {
        "metrics": _metrics(results, "expected_symbols"),
        "query_results": results,
    }


def test_task_separated_retrieval_benchmark_reports_per_query_results():
    benchmark = json.loads(_BENCHMARK_PATH.read_text(encoding="utf-8"))
    database = MemorySupabase()
    source_files = [{
        "path": path.relative_to(_REPOSITORY_ROOT).as_posix(),
        "content": path.read_text(encoding="utf-8"),
    } for path in sorted(_REPOSITORY_ROOT.rglob("*.py"))]

    symbol_indexing = CodeSymbolIndexer(database).index_files(
        source_files,
        repository_id=_REPOSITORY_ID,
        snapshot_id=_SNAPSHOT_ID,
        company_id=_COMPANY_ID,
        source_revision=_SOURCE_REVISION,
    )
    chunk_indexing = SourceChunkIndexer(
        database,
        chunker=SourceChunker(
            max_source_bytes=1_000_000,
            max_chunk_bytes=1_200,
            max_lines=5,
            overlap_lines=1,
            chunker_version="task-benchmark-line-window-v1",
        ),
    ).index_files(
        source_files,
        repository_id=_REPOSITORY_ID,
        snapshot_id=_SNAPSHOT_ID,
        company_id=_COMPANY_ID,
        source_revision=_SOURCE_REVISION,
    )
    assert len(source_files) == benchmark["corpus"]["file_count"] == 9
    assert symbol_indexing["files_indexed"] == 9
    assert chunk_indexing["files_indexed"] == 9
    assert chunk_indexing["chunks_persisted"] > 9

    symbol_retriever = CodeLexicalRetriever(database, top_k=100)
    chunk_retriever = SourceChunkRetriever(database, max_results=100)
    queries = benchmark["queries"]
    declarations = [q for q in queries if q["task_type"] == "declaration_discovery"]
    call_sites = [q for q in queries if q["task_type"] == "call_site_context"]
    passages = [q for q in queries if q["task_type"] == "passage_retrieval"]
    no_evidence = [q for q in queries if q["task_type"] == "no_evidence"]

    declaration_result = _score_declarations(symbol_retriever, declarations)
    call_result = _score_ranges(chunk_retriever, call_sites)
    passage_result = _score_ranges(chunk_retriever, passages)

    empty_results = []
    for query in no_evidence:
        symbol_hits = symbol_retriever.retrieve(
            company_id=_COMPANY_ID,
            repository_id=_REPOSITORY_ID,
            identifiers=query["terms"],
        )
        chunk_hits = chunk_retriever.retrieve(
            company_id=_COMPANY_ID,
            repository_id=_REPOSITORY_ID,
            terms=query["terms"],
        )
        empty_results.append({
            "query_id": query["id"],
            "symbol_candidates": len(symbol_hits),
            "chunk_candidates": len(chunk_hits),
        })
    assert all(
        item["symbol_candidates"] == item["chunk_candidates"] == 0
        for item in empty_results
    ), empty_results

    report = {
        "corpus_files": len(source_files),
        "indexed_symbols": symbol_indexing["symbols_persisted"],
        "indexed_chunks": chunk_indexing["chunks_persisted"],
        "declaration_discovery": declaration_result,
        "call_site_context": call_result,
        "passage_retrieval": passage_result,
        "no_evidence": empty_results,
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    assert declaration_result["metrics"]["evaluated_queries"] == 10
    assert call_result["metrics"]["evaluated_queries"] == 10
    assert passage_result["metrics"]["evaluated_queries"] == 10
    assert len(empty_results) == 3

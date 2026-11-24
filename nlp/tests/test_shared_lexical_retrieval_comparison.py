"""Shared file-level evaluation for symbol and source-chunk lexical retrieval.

Both systems receive the same identifier signals and are scored against the
same declaration-file ground truth. Chunk hits are deduplicated by file before
ranking, so multiple chunks from one file do not occupy multiple positions.
This is a narrow file-discovery comparison, not passage-quality evaluation.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from statistics import mean
from types import SimpleNamespace

from codebase.source_chunk_indexer import SourceChunkIndexer
from codebase.source_chunk_retriever import SourceChunkRetriever
from codebase.source_chunker import SourceChunker
from codebase.symbol_indexer import CodeSymbolIndexer
from query_engine.code_lexical import CodeLexicalRetriever


_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "retrieval"
_REPOSITORY_ROOT = _FIXTURE_ROOT / "mini_repo"
_BENCHMARK_PATH = _FIXTURE_ROOT / "shared_definition_file_benchmark.json"
_COMPANY_ID = "company-a"
_REPOSITORY_ID = "mini-repo-a"
_SNAPSHOT_ID = "mini-repo-a@fixture-v1"
_SOURCE_REVISION = "fixture-v1"


class MemoryQuery:
    """Small PostgREST subset supporting both real indexers and retrievers."""

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
            if self.table_name == "code_symbols":
                existing = {
                    (row.get("snapshot_id"), row.get("symbol_id")): index
                    for index, row in enumerate(rows)
                }
                for row in self.upsert_rows:
                    key = (row.get("snapshot_id"), row.get("symbol_id"))
                    if key in existing:
                        rows[existing[key]] = dict(row)
                    else:
                        existing[key] = len(rows)
                        rows.append(dict(row))
            else:
                existing = {
                    row.get("chunk_id"): index for index, row in enumerate(rows)
                }
                for row in self.upsert_rows:
                    key = row.get("chunk_id")
                    if key in existing:
                        rows[existing[key]] = dict(row)
                    else:
                        existing[key] = len(rows)
                        rows.append(dict(row))
            return SimpleNamespace(data=[])

        selected = list(rows)
        for operator, column, value in self.filters:
            if operator == "eq":
                selected = [row for row in selected if row.get(column) == value]
                continue

            # Mirror the already-verified chunk benchmark's narrow PostgREST
            # double: fixture terms are literal identifiers, not SQL wildcard
            # expressions. Undo the retriever's escaping, then use substring
            # matching. This is intentionally not a general SQL LIKE emulator.
            needle = value[1:-1].replace("\\\\", "\\")
            needle = needle.replace("\\%", "%").replace("\\_", "_")
            selected = [
                row for row in selected
                if needle.casefold() in str(row.get(column) or "").casefold()
            ]

        for column in reversed(self.orders):
            selected.sort(key=lambda row: row.get(column) or "")
        if self.maximum is not None:
            selected = selected[:self.maximum]
        return SimpleNamespace(data=selected)


class MemorySupabase:
    """Shared in-memory snapshot for the actual symbol and chunk pipelines."""

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


def _file_ranking(candidates):
    """Project evidence rankings to unique files, preserving first occurrence."""
    paths = []
    seen = set()
    for candidate in candidates:
        path = candidate.file_path
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return [{"rank": rank, "file_path": path} for rank, path in enumerate(paths, 1)]


def _evaluate(retriever, queries, *, candidate_limit=50):
    results = []
    for query in queries:
        if isinstance(retriever, CodeLexicalRetriever):
            candidates = retriever.retrieve(
                company_id=_COMPANY_ID,
                repository_id=_REPOSITORY_ID,
                identifiers=[query["identifier"]],
            )
        else:
            candidates = retriever.retrieve(
                company_id=_COMPANY_ID,
                repository_id=_REPOSITORY_ID,
                terms=[query["identifier"]],
            )

        for candidate in candidates:
            assert candidate.company_id == _COMPANY_ID
            assert candidate.repository_id == _REPOSITORY_ID
            assert candidate.snapshot_id == _SNAPSHOT_ID
            assert candidate.source_revision == _SOURCE_REVISION

        ranking = _file_ranking(candidates)
        rank_by_path = {item["file_path"]: item["rank"] for item in ranking}
        expected = query["expected_paths"]
        relevant_ranks = sorted(
            rank_by_path[path] for path in expected if path in rank_by_path
        )
        result = {
            "query_id": query["id"],
            "identifier": query["identifier"],
            "expected_paths": expected,
            "ranking": ranking[:candidate_limit],
            "relevant_ranks": relevant_ranks,
            "reciprocal_rank": 1.0 / min(relevant_ranks) if relevant_ranks else 0.0,
        }
        for cutoff in (1, 5, 10):
            result[f"recall_at_{cutoff}"] = (
                sum(rank <= cutoff for rank in relevant_ranks) / len(expected)
                if expected else 0.0
            )
        results.append(result)

    metrics = {
        f"recall_at_{cutoff}": mean(
            item[f"recall_at_{cutoff}"] for item in results
        )
        for cutoff in (1, 5, 10)
    }
    metrics["mrr"] = mean(item["reciprocal_rank"] for item in results)
    return {"evaluated_queries": len(results), "metrics": metrics, "query_results": results}


def test_symbol_and_chunk_lexical_retrievers_on_shared_definition_file_queries():
    benchmark = json.loads(_BENCHMARK_PATH.read_text(encoding="utf-8"))
    database = MemorySupabase()
    source_files = [
        {
            "path": path.relative_to(_REPOSITORY_ROOT).as_posix(),
            "content": path.read_text(encoding="utf-8"),
        }
        for path in sorted(_REPOSITORY_ROOT.rglob("*.py"))
    ]

    symbol_indexing = CodeSymbolIndexer(database).index_files(
        source_files,
        repository_id=_REPOSITORY_ID,
        snapshot_id=_SNAPSHOT_ID,
        company_id=_COMPANY_ID,
        source_revision=_SOURCE_REVISION,
    )
    chunker = SourceChunker(
        max_source_bytes=1_000_000,
        max_chunk_bytes=1_200,
        max_lines=5,
        overlap_lines=1,
        chunker_version="benchmark-line-window-v1",
    )
    chunk_indexing = SourceChunkIndexer(database, chunker=chunker).index_files(
        source_files,
        repository_id=_REPOSITORY_ID,
        snapshot_id=_SNAPSHOT_ID,
        company_id=_COMPANY_ID,
        source_revision=_SOURCE_REVISION,
    )

    assert symbol_indexing["files_indexed"] == 4
    assert symbol_indexing["symbols_persisted"] > 0
    assert chunk_indexing["files_indexed"] == 4
    assert chunk_indexing["chunks_persisted"] > chunk_indexing["files_indexed"]

    symbol_retriever = CodeLexicalRetriever(database, top_k=50)
    chunk_retriever = SourceChunkRetriever(database, max_results=50)
    symbol_result = _evaluate(symbol_retriever, benchmark["queries"])
    chunk_result = _evaluate(chunk_retriever, benchmark["queries"])

    print(json.dumps({
        "comparison_unit": "unique file path",
        "queries": len(benchmark["queries"]),
        "symbol_lexical": symbol_result,
        "source_chunk_lexical": chunk_result,
    }, indent=2, sort_keys=True))

    assert symbol_result["evaluated_queries"] == 4
    assert chunk_result["evaluated_queries"] == 4
    assert symbol_result["metrics"]["recall_at_5"] == 1.0
    assert chunk_result["metrics"]["recall_at_5"] == 1.0

    # A definition-file query must at least retrieve the declared target.
    for result in (symbol_result, chunk_result):
        assert all(item["relevant_ranks"] for item in result["query_results"])

    # Scope and provenance must remain identical across both evidence types.
    assert all(row["company_id"] == _COMPANY_ID for row in database.rows["code_symbols"])
    assert all(row["company_id"] == _COMPANY_ID for row in database.rows["source_code_chunks"])

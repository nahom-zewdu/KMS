"""End-to-end source-chunk lexical benchmark on the synthetic repository fixture.

The in-memory PostgREST double exercises the real chunker, indexer, retriever,
and ranking path. It does not claim PostgreSQL query-planner or RLS coverage.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from statistics import mean
from types import SimpleNamespace

from codebase.source_chunk_indexer import SourceChunkIndexer
from codebase.source_chunk_retriever import SourceChunkRetriever


_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "retrieval"
_REPOSITORY_ROOT = _FIXTURE_ROOT / "mini_repo"
_BENCHMARK_PATH = _FIXTURE_ROOT / "source_chunk_benchmark.json"


class MemoryQuery:
    """Small PostgREST subset needed by the real source-chunk pipeline."""

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
            existing = {
                row["chunk_id"]: index for index, row in enumerate(rows)
            }
            for row in self.upsert_rows:
                key = row["chunk_id"]
                if key in existing:
                    rows[existing[key]] = dict(row)
                else:
                    existing[key] = len(rows)
                    rows.append(dict(row))
            return SimpleNamespace(data=[])

        selected = list(rows)
        for operator, column, value in self.filters:
            if operator == "eq":
                selected = [
                    row for row in selected if row.get(column) == value
                ]
                continue

            # The fixture terms contain no SQL wildcards. Unescape the
            # retriever's PostgREST pattern and apply case-insensitive contains.
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
    """In-memory tables with one active fixture repository snapshot."""

    def __init__(self):
        self.rows = {
            "repositories": [{
                "id": "mini-repo-a",
                "company_id": "company-a",
                "active_snapshot_id": "mini-repo-a@fixture-v1",
            }],
            "source_code_chunks": [],
        }

    def table(self, name):
        return MemoryQuery(self, name)


def _evaluate(retriever, benchmark):
    query_results = []
    for query in benchmark["queries"]:
        candidates = retriever.retrieve(
            company_id=benchmark["default_scope"]["company_id"],
            repository_id=benchmark["default_scope"]["repository_id"],
            terms=query["terms"],
        )
        expected_paths = set(query["expected_paths"])
        first_ranks = {}
        for candidate in candidates:
            assert candidate.company_id == benchmark["default_scope"]["company_id"]
            assert candidate.repository_id == benchmark["default_scope"]["repository_id"]
            assert candidate.snapshot_id == benchmark["default_scope"]["snapshot_id"]
            assert candidate.source_revision == benchmark["default_scope"]["source_revision"]
            if candidate.file_path in expected_paths:
                first_ranks.setdefault(candidate.file_path, candidate.rank)

        ranks = list(first_ranks.values())
        result = {
            "query_id": query["id"],
            "relevant_count": len(expected_paths),
            "retrieved_relevant_ranks": sorted(ranks),
            "reciprocal_rank": 1.0 / min(ranks) if ranks else 0.0,
        }
        for cutoff in (1, 5, 10):
            result[f"recall_at_{cutoff}"] = (
                sum(rank <= cutoff for rank in ranks) / len(expected_paths)
            )
        query_results.append(result)

    metrics = {
        f"recall_at_{cutoff}": mean(
            result[f"recall_at_{cutoff}"] for result in query_results
        )
        for cutoff in (1, 5, 10)
    }
    metrics["mrr"] = mean(
        result["reciprocal_rank"] for result in query_results
    )
    return {
        "evaluated_queries": len(query_results),
        "metrics": metrics,
        "query_results": query_results,
    }


def test_real_fixture_chunk_indexer_retriever_has_measurable_lexical_baseline():
    benchmark = json.loads(_BENCHMARK_PATH.read_text(encoding="utf-8"))
    database = MemorySupabase()
    source_files = [
        {
            "path": path.relative_to(_REPOSITORY_ROOT).as_posix(),
            "content": path.read_text(encoding="utf-8"),
        }
        for path in sorted(_REPOSITORY_ROOT.rglob("*.py"))
    ]

    indexing = SourceChunkIndexer(database).index_files(
        source_files,
        repository_id="mini-repo-a",
        snapshot_id="mini-repo-a@fixture-v1",
        company_id="company-a",
        source_revision="fixture-v1",
    )
    assert indexing["files_seen"] == 4
    assert indexing["files_indexed"] == 4
    assert indexing["files_rejected"] == 0
    assert indexing["chunks_persisted"] == 4

    retriever = SourceChunkRetriever(database, max_results=20)
    benchmark_result = _evaluate(retriever, benchmark)

    assert benchmark_result["evaluated_queries"] == 12
    assert benchmark_result["metrics"]["recall_at_5"] == 1.0
    assert benchmark_result["metrics"]["recall_at_10"] == 1.0
    assert benchmark_result["metrics"]["mrr"] >= 0.5, benchmark_result["query_results"]

    # A no-evidence query should remain empty; another repository or tenant
    # must not borrow this fixture's active snapshot or chunks.
    assert retriever.retrieve(
        company_id="company-a",
        repository_id="mini-repo-a",
        terms=["KubernetesDeployment"],
    ) == []
    assert retriever.retrieve(
        company_id="company-a",
        repository_id="mini-repo-b",
        terms=["PaymentService"],
    ) == []
    assert retriever.retrieve(
        company_id="company-b",
        repository_id="mini-repo-a",
        terms=["PaymentService"],
    ) == []

    persisted = database.rows["source_code_chunks"]
    assert len(persisted) == indexing["chunks_persisted"]
    assert all(row["company_id"] == "company-a" for row in persisted)
    assert all(row["repository_id"] == "mini-repo-a" for row in persisted)
    assert all(row["snapshot_id"] == "mini-repo-a@fixture-v1" for row in persisted)
    assert all(row["source_revision"] == "fixture-v1" for row in persisted)

"""Chunk-level source retrieval benchmark over the synthetic repository.

The in-memory PostgREST double exercises the real chunker, indexer, retriever,
and ranking path. It does not claim PostgreSQL query-planner or RLS coverage.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from types import SimpleNamespace

from codebase.source_chunk_indexer import SourceChunkIndexer
from codebase.source_chunk_retriever import SourceChunkRetriever
from codebase.source_chunker import SourceChunker


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
    scope = benchmark["default_scope"]
    for query in benchmark["queries"]:
        candidates = retriever.retrieve(
            company_id=scope["company_id"],
            repository_id=scope["repository_id"],
            terms=query["terms"],
        )
        first_ranks = {}
        for candidate in candidates:
            assert candidate.company_id == scope["company_id"]
            assert candidate.repository_id == scope["repository_id"]
            assert candidate.snapshot_id == scope["snapshot_id"]
            assert candidate.source_revision == scope["source_revision"]
            key = (
                candidate.file_path,
                candidate.start_line,
                candidate.end_line,
            )
            first_ranks.setdefault(key, candidate.rank)

        expected = {
            (item["file_path"], item["start_line"], item["end_line"])
            for item in query["expected_chunks"]
        }
        ranks = sorted(first_ranks[key] for key in expected if key in first_ranks)
        result = {
            "query_id": query["id"],
            "relevant_count": len(expected),
            "retrieved_relevant_ranks": ranks,
            "ranking": [
                {
                    "rank": candidate.rank,
                    "file_path": candidate.file_path,
                    "start_line": candidate.start_line,
                    "end_line": candidate.end_line,
                    "matched_terms": candidate.metadata["match_terms"],
                }
                for candidate in candidates
            ],
            "reciprocal_rank": 1.0 / min(ranks) if ranks else 0.0,
        }
        for cutoff in (1, 5, 10):
            result[f"recall_at_{cutoff}"] = (
                sum(rank <= cutoff for rank in ranks) / len(expected)
                if expected else 0.0
            )
        query_results.append(result)

    evaluated = [
        item for item, query in zip(query_results, benchmark["queries"])
        if query["expected_chunks"]
    ]
    metrics = {
        f"recall_at_{cutoff}": mean(
            item[f"recall_at_{cutoff}"] for item in evaluated
        )
        for cutoff in (1, 5, 10)
    }
    metrics["mrr"] = mean(item["reciprocal_rank"] for item in evaluated)
    return {
        "evaluated_queries": len(evaluated),
        "no_evidence_queries": len(query_results) - len(evaluated),
        "metrics": metrics,
        "query_results": query_results,
    }


def test_real_fixture_chunk_indexer_retriever_has_chunk_level_lexical_baseline():
    benchmark = json.loads(_BENCHMARK_PATH.read_text(encoding="utf-8"))
    database = MemorySupabase()
    source_files = [
        {
            "path": path.relative_to(_REPOSITORY_ROOT).as_posix(),
            "content": path.read_text(encoding="utf-8"),
        }
        for path in sorted(_REPOSITORY_ROOT.rglob("*.py"))
    ]

    # Small deterministic windows create multiple candidates per source file.
    # Chunks outside each query's explicit relevant ranges are ranking
    # distractors rather than silently counting an entire file as relevant.
    chunker = SourceChunker(
        max_source_bytes=1_000_000,
        max_chunk_bytes=1_200,
        max_lines=5,
        overlap_lines=1,
        chunker_version="benchmark-line-window-v1",
    )
    indexing = SourceChunkIndexer(database, chunker=chunker).index_files(
        source_files,
        repository_id="mini-repo-a",
        snapshot_id="mini-repo-a@fixture-v1",
        company_id="company-a",
        source_revision="fixture-v1",
    )
    assert indexing["files_seen"] == 4
    assert indexing["files_indexed"] == 4
    assert indexing["files_rejected"] == 0
    assert indexing["chunks_persisted"] > indexing["files_indexed"]

    retriever = SourceChunkRetriever(database, max_results=50)
    benchmark_result = _evaluate(retriever, benchmark)
    print(json.dumps(benchmark_result, indent=2, sort_keys=True))

    assert benchmark_result["evaluated_queries"] == 5
    assert benchmark_result["no_evidence_queries"] == 1
    assert benchmark_result["metrics"]["recall_at_10"] == 1.0, benchmark_result
    assert benchmark_result["metrics"]["mrr"] >= 0.5, benchmark_result

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

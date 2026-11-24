"""Opt-in comparison of SCIP semantic references against lexical call-site retrieval.

The benchmark resolves query identifiers to SCIP symbols using definition
occurrences in the same pinned fixture. This isolates reference-location
quality; it does not evaluate natural-language query-to-symbol resolution.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from codebase.scip_indexer import ScipIndexRunner
from query_engine.scip_occurrence_retriever import ScipOccurrenceRetriever


_FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "retrieval" / "mini_repo_v2"
)
_BENCHMARK_PATH = (
    Path(__file__).parent / "fixtures" / "retrieval" / "retrieval_tasks_v1.json"
)
_COMPANY_ID = "scip-benchmark-company"
_REPOSITORY_ID = "scip-benchmark-repository"
_SNAPSHOT_ID = "scip-benchmark-snapshot-v1"
_SOURCE_REVISION = "scip-benchmark-revision-v1"


class _Query:
    """Minimal PostgREST query double for SCIP occurrence reads."""

    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.orders = []
        self.maximum = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, tuple(values)))
        return self

    def order(self, column):
        self.orders.append(column)
        return self

    def limit(self, maximum):
        self.maximum = maximum
        return self

    def execute(self):
        selected = list(self.rows)
        for operator, column, value in self.filters:
            if operator == "eq":
                selected = [row for row in selected if row.get(column) == value]
            else:
                selected = [row for row in selected if row.get(column) in value]
        for column in reversed(self.orders):
            selected.sort(key=lambda row: (row.get(column) is None, row.get(column) or 0))
        if self.maximum is not None:
            selected = selected[: self.maximum]
        return type("Response", (), {"data": selected})()


class _Database:
    """One active snapshot containing normalized SCIP occurrences."""

    def __init__(self, occurrences):
        self.rows = {
            "repositories": [{
                "id": _REPOSITORY_ID,
                "company_id": _COMPANY_ID,
                "active_snapshot_id": _SNAPSHOT_ID,
            }],
            "code_symbol_occurrences": occurrences,
        }

    def table(self, name):
        return _Query(self.rows.get(name, []))


def _metrics(results):
    evaluated = [item for item in results if item["relevant_count"]]
    metrics = {"evaluated_queries": len(evaluated)}
    for cutoff in (1, 5, 10):
        metrics[f"recall_at_{cutoff}"] = (
            sum(item[f"recall_at_{cutoff}"] for item in evaluated) / len(evaluated)
            if evaluated else 0.0
        )
    metrics["mrr"] = (
        sum(item["reciprocal_rank"] for item in evaluated) / len(evaluated)
        if evaluated else 0.0
    )
    return metrics


@pytest.mark.skipif(
    os.getenv("KMS_SCIP_PYTHON_BENCHMARK") != "1",
    reason="set KMS_SCIP_PYTHON_BENCHMARK=1 to run the real SCIP call-site benchmark",
)
def test_scip_semantic_references_on_call_site_benchmark():
    """Measure exact SCIP reference locations for locally resolvable query symbols."""
    scip_python = shutil.which("scip-python")
    scip_cli = shutil.which("scip")
    if not scip_python or not scip_cli:
        pytest.skip("scip-python and scip CLI must both be installed")

    runner = ScipIndexRunner(
        indexer_argv=(
            scip_python,
            "index",
            "{repository_root}",
            "--project-name=kms-retrieval-benchmark",
            "--project-version=0.0.0",
        ),
        indexer_name="scip-python",
        scip_cli_argv=(scip_cli,),
        timeout_seconds=180,
        max_index_bytes=64 * 1024 * 1024,
        max_json_bytes=128 * 1024 * 1024,
        # scip-python 0.6.8 omits positionEncoding; its documented Python
        # convention is UTF-32 code-point offsets.
        position_encoding_override=3,
    )
    index = runner.run(
        repository_root=_FIXTURE_ROOT,
        source_revision=_SOURCE_REVISION,
    )

    persisted = [{
        **occurrence.to_dict(),
        "company_id": _COMPANY_ID,
        "repository_id": _REPOSITORY_ID,
        "snapshot_id": _SNAPSHOT_ID,
    } for occurrence in index.occurrences]
    database = _Database(persisted)
    retriever = ScipOccurrenceRetriever(database)
    benchmark = json.loads(_BENCHMARK_PATH.read_text(encoding="utf-8"))
    queries = [
        query for query in benchmark["queries"]
        if query["task_type"] == "call_site_context"
    ]

    definitions_by_token = {}
    for occurrence in index.occurrences:
        if occurrence.role != "definition":
            continue
        source = (_FIXTURE_ROOT / occurrence.file_path).read_bytes()
        token = source[occurrence.start_byte:occurrence.end_byte].decode("utf-8")
        definitions_by_token.setdefault(token, set()).add(occurrence.symbol)

    results = []
    for query in queries:
        target_symbols = sorted({
            symbol
            for term in query["terms"]
            for symbol in definitions_by_token.get(term, set())
        })
        if not target_symbols:
            results.append({
                "query_id": query["id"],
                "resolved_terms": [],
                "unresolved_terms": list(query["terms"]),
                "relevant_count": 0,
                "retrieved_relevant_ranks": [],
                "ranking": [],
                "reciprocal_rank": 0.0,
                **{f"recall_at_{cutoff}": 0.0 for cutoff in (1, 5, 10)},
            })
            continue

        occurrences_by_id = {}
        for symbol in target_symbols:
            for occurrence in retriever.find_references(
                company_id=_COMPANY_ID,
                repository_id=_REPOSITORY_ID,
                symbol=symbol,
            ):
                occurrences_by_id[occurrence["occurrence_id"]] = occurrence

        candidates = sorted(
            occurrences_by_id.values(),
            key=lambda item: (
                item["file_path"],
                item["start_byte"],
                item["end_byte"],
            ),
        )
        expected = query["expected_ranges"]
        hit_ranks = []
        ranking = []
        for rank, candidate in enumerate(candidates, start=1):
            ranking.append({
                "rank": rank,
                "file_path": candidate["file_path"],
                "start_line": candidate["start_line"],
                "end_line": candidate["end_line"],
                "symbol": candidate["symbol"],
            })
            if any(
                candidate["file_path"] == label["file_path"]
                and candidate["start_line"] <= label["end_line"]
                and candidate["end_line"] >= label["start_line"]
                for label in expected
            ):
                hit_ranks.append(rank)

        first_rank = min(hit_ranks) if hit_ranks else None
        result = {
            "query_id": query["id"],
            "resolved_terms": [
                term for term in query["terms"] if term in definitions_by_token
            ],
            "unresolved_terms": [
                term for term in query["terms"] if term not in definitions_by_token
            ],
            "relevant_count": len(expected),
            "retrieved_relevant_ranks": sorted(hit_ranks),
            "ranking": ranking,
            "reciprocal_rank": 1.0 / first_rank if first_rank else 0.0,
        }
        for cutoff in (1, 5, 10):
            result[f"recall_at_{cutoff}"] = (
                sum(rank <= cutoff for rank in hit_ranks) / len(expected)
                if expected else 0.0
            )
        results.append(result)

    covered = [item for item in results if item["relevant_count"]]
    report = {
        "indexer": index.indexer_name,
        "indexer_version": index.indexer_version,
        "occurrences_indexed": len(index.occurrences),
        "definitions_indexed": sum(
            occurrence.role == "definition" for occurrence in index.occurrences
        ),
        "references_indexed": sum(
            occurrence.role in {"reference", "occurrence"}
            for occurrence in index.occurrences
        ),
        "query_count": len(queries),
        "symbol_resolution_coverage": len(covered),
        "symbol_resolution_coverage_rate": len(covered) / len(queries) if queries else 0.0,
        "metrics_on_resolved_queries_only": _metrics(covered),
        "unresolved_queries": [
            {
                "query_id": item["query_id"],
                "unresolved_terms": item["unresolved_terms"],
            }
            for item in results if not item["relevant_count"]
        ],
        "query_results": results,
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    assert len(queries) == 10
    assert len(covered) >= 8, report["unresolved_queries"]

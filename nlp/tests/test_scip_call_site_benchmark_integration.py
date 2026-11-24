"""Opt-in SCIP semantic-reference coverage benchmark for call-site queries.

Query identifiers are mapped to SCIP symbols through definitions in the same
fixture. This isolates semantic reference retrieval; it does not measure
natural-language query-to-symbol resolution or rank the returned occurrences.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from codebase.scip_indexer import ScipIndexRunner
from codebase.scip_occurrence_retriever import ScipOccurrenceRetriever


_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "retrieval" / "mini_repo_v2"
_BENCHMARK_PATH = Path(__file__).parent / "fixtures" / "retrieval" / "retrieval_tasks_v1.json"
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
            selected.sort(
                key=lambda row: (
                    row.get(column) is None,
                    row.get(column) if row.get(column) is not None else 0,
                )
            )
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


def _overlaps(candidate, label):
    return (
        candidate["file_path"] == label["file_path"]
        and candidate["start_line"] <= label["end_line"]
        and candidate["end_line"] >= label["start_line"]
    )


def _metrics(results):
    evaluated = [item for item in results if item["expected_range_count"]]
    expected_count = sum(item["expected_range_count"] for item in evaluated)
    matched_count = sum(item["matched_expected_range_count"] for item in evaluated)
    retrieved_count = sum(item["retrieved_occurrence_count"] for item in evaluated)
    relevant_occurrences = sum(item["relevant_occurrence_count"] for item in evaluated)
    return {
        "evaluated_queries": len(evaluated),
        "expected_ranges": expected_count,
        "matched_expected_ranges": matched_count,
        "range_coverage_recall": matched_count / expected_count if expected_count else 0.0,
        "retrieved_occurrences": retrieved_count,
        "relevant_occurrences": relevant_occurrences,
        "occurrence_precision": relevant_occurrences / retrieved_count if retrieved_count else 0.0,
    }


@pytest.mark.skipif(
    os.getenv("KMS_SCIP_PYTHON_BENCHMARK") != "1",
    reason="set KMS_SCIP_PYTHON_BENCHMARK=1 to run the real SCIP call-site benchmark",
)
def test_scip_semantic_references_on_call_site_benchmark():
    """Measure SCIP reference coverage and precision on the call-site fixture."""
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
        # scip-python 0.6.8 omits positionEncoding; Python offsets are UTF-32
        # code points, so this compatibility assumption is explicit.
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
    retriever = ScipOccurrenceRetriever(_Database(persisted))
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
        resolved_terms = [
            term for term in query["terms"] if term in definitions_by_token
        ]
        unresolved_terms = [
            term for term in query["terms"] if term not in definitions_by_token
        ]
        symbols = sorted({
            symbol
            for term in resolved_terms
            for symbol in definitions_by_token[term]
        })
        occurrences_by_id = {}
        for symbol in symbols:
            for occurrence in retriever.find_references(
                company_id=_COMPANY_ID,
                repository_id=_REPOSITORY_ID,
                symbol=symbol,
            ):
                occurrences_by_id[occurrence["occurrence_id"]] = occurrence

        candidates = list(occurrences_by_id.values())
        expected = query["expected_ranges"]
        matched_ranges = [
            label for label in expected
            if any(_overlaps(candidate, label) for candidate in candidates)
        ]
        relevant_occurrences = [
            candidate for candidate in candidates
            if any(_overlaps(candidate, label) for label in expected)
        ]
        results.append({
            "query_id": query["id"],
            "resolved_terms": resolved_terms,
            "unresolved_terms": unresolved_terms,
            "expected_range_count": len(expected),
            "matched_expected_range_count": len(matched_ranges),
            "retrieved_occurrence_count": len(candidates),
            "relevant_occurrence_count": len(relevant_occurrences),
            "relevant_occurrences": [
                {
                    "file_path": item["file_path"],
                    "start_line": item["start_line"],
                    "end_line": item["end_line"],
                    "symbol": item["symbol"],
                }
                for item in relevant_occurrences
            ],
            "retrieved_occurrences": [
                {
                    "file_path": item["file_path"],
                    "start_line": item["start_line"],
                    "end_line": item["end_line"],
                    "symbol": item["symbol"],
                }
                for item in candidates
            ],
        })

    resolved = [item for item in results if item["resolved_terms"]]
    report = {
        "indexer": index.indexer_name,
        "indexer_version": index.indexer_version,
        "occurrences_indexed": len(index.occurrences),
        "definitions_indexed": sum(item.role == "definition" for item in index.occurrences),
        "references_indexed": sum(
            item.role in {"reference", "occurrence"} for item in index.occurrences
        ),
        "query_count": len(queries),
        "symbol_resolution_coverage": len(resolved),
        "symbol_resolution_coverage_rate": len(resolved) / len(queries) if queries else 0.0,
        "metrics_on_resolved_queries_only": _metrics(resolved),
        "unresolved_queries": [
            {"query_id": item["query_id"], "unresolved_terms": item["unresolved_terms"]}
            for item in results if not item["resolved_terms"]
        ],
        "query_results": results,
        "method_note": (
            "Coverage and precision only. SCIP occurrences are not assigned a "
            "relevance ranking; source-order sorting is deliberately not scored."
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    assert len(queries) == 10
    assert len(resolved) >= 8, report["unresolved_queries"]

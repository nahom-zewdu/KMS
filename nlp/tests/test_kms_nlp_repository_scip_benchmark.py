"""Opt-in real-SCIP call-site benchmark over KMS's Python subsystem.

Unlike the lexical repository benchmark, this runs scip-python against the
checked-out NLP source tree and checks cross-file semantic references. The
query-to-symbol step is deliberately exact-token based; it is not natural-
language symbol resolution, and occurrences are measured for coverage only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from codebase.scip_indexer import ScipIndexRunner
from codebase.scip_occurrence_retriever import ScipOccurrenceRetriever


pytestmark = pytest.mark.skipif(
    os.getenv("KMS_NLP_REPOSITORY_SCIP_BENCHMARK") != "1",
    reason="set KMS_NLP_REPOSITORY_SCIP_BENCHMARK=1 to run the real-repository SCIP benchmark",
)

_NLP_ROOT = Path(__file__).resolve().parents[1]
_COMPANY_ID = "kms-nlp-scip-benchmark-company"
_REPOSITORY_ID = "kms-nlp-scip-benchmark-repository"
_SNAPSHOT_ID = "kms-nlp-scip-benchmark-snapshot"
_SOURCE_REVISION = "kms-nlp-scip-working-tree"


class _Query:
    """Minimal PostgREST read behavior for normalized occurrence rows."""

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
            selected.sort(key=lambda row: row.get(column) or "")
        if self.maximum is not None:
            selected = selected[:self.maximum]
        return type("Response", (), {"data": selected})()


class _Database:
    """One tenant and active snapshot containing real SCIP output."""

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


# Ground truth is source-reviewed and intentionally limited to direct
# cross-file references. Line ranges are one-based and may be widened only
# when the implementation moves; update them after reviewing the source.
_CALL_SITE_QUERIES = [
    {
        "id": "scip-01-baseline-source-chunk-indexer",
        "question": "Which baseline component constructs the source chunk indexer?",
        "token": "SourceChunkIndexer",
        "expected": [{"file_path": "codebase/baseline.py", "start_line": 35, "end_line": 35}],
    },
    {
        "id": "scip-02-baseline-symbol-indexer",
        "question": "Which baseline component constructs the code symbol indexer?",
        "token": "CodeSymbolIndexer",
        "expected": [{"file_path": "codebase/baseline.py", "start_line": 34, "end_line": 34}],
    },
    {
        "id": "scip-03-chunker-dependency",
        "question": "Which chunking implementation does the source chunk indexer depend on?",
        "token": "SourceChunker",
        "expected": [{"file_path": "codebase/source_chunk_indexer.py", "start_line": 6, "end_line": 6}],
    },
]


def _overlaps(occurrence, expected):
    return (
        occurrence["file_path"] == expected["file_path"]
        and occurrence["start_line"] <= expected["end_line"]
        and occurrence["end_line"] >= expected["start_line"]
    )


def test_real_kms_python_repository_scip_references():
    """Measure semantic cross-file reference coverage on the actual NLP tree."""
    scip_python = shutil.which("scip-python")
    scip_cli = shutil.which("scip")
    if not scip_python or not scip_cli:
        pytest.skip("scip-python and scip CLI must both be installed")

    runner = ScipIndexRunner(
        indexer_argv=(
            scip_python,
            "index",
            "{repository_root}",
            "--project-name=kms-nlp-repository-benchmark",
            "--project-version=0.0.0",
        ),
        indexer_name="scip-python",
        scip_cli_argv=(scip_cli,),
        timeout_seconds=600,
        max_index_bytes=128 * 1024 * 1024,
        max_json_bytes=256 * 1024 * 1024,
        # scip-python 0.6.8 omits positionEncoding; Python uses UTF-32
        # code-point offsets. Keep this compatibility assumption explicit.
        position_encoding_override=3,
    )
    index = runner.run(
        repository_root=_NLP_ROOT,
        source_revision=_SOURCE_REVISION,
    )

    persisted = [{
        **occurrence.to_dict(),
        "company_id": _COMPANY_ID,
        "repository_id": _REPOSITORY_ID,
        "snapshot_id": _SNAPSHOT_ID,
    } for occurrence in index.occurrences]
    retriever = ScipOccurrenceRetriever(_Database(persisted), max_results=2000)

    definitions_by_token = {}
    for occurrence in index.occurrences:
        if occurrence.role != "definition":
            continue
        source_path = _NLP_ROOT / occurrence.file_path
        source = source_path.read_bytes()
        token = source[occurrence.start_byte:occurrence.end_byte].decode("utf-8")
        definitions_by_token.setdefault(token, set()).add(occurrence.symbol)

    results = []
    for query in _CALL_SITE_QUERIES:
        symbols = sorted(definitions_by_token.get(query["token"], set()))
        occurrences_by_id = {}
        for symbol in symbols:
            for occurrence in retriever.find_references(
                company_id=_COMPANY_ID,
                repository_id=_REPOSITORY_ID,
                symbol=symbol,
            ):
                occurrences_by_id[occurrence["occurrence_id"]] = occurrence
        candidates = list(occurrences_by_id.values())
        matched = [
            label for label in query["expected"]
            if any(_overlaps(candidate, label) for candidate in candidates)
        ]
        results.append({
            "id": query["id"],
            "question": query["question"],
            "resolved_symbols": len(symbols),
            "expected_ranges": len(query["expected"]),
            "matched_expected_ranges": len(matched),
            "retrieved_occurrences": len(candidates),
            "relevant_occurrences": [
                {
                    "file_path": item["file_path"],
                    "start_line": item["start_line"],
                    "end_line": item["end_line"],
                    "symbol": item["symbol"],
                }
                for item in candidates
                if any(_overlaps(item, label) for label in query["expected"])
            ],
        })

    absent = retriever.find_references(
        company_id=_COMPANY_ID,
        repository_id=_REPOSITORY_ID,
        symbol="local 999999 kms nonexistent symbol",
    )
    report = {
        "indexer": index.indexer_name,
        "indexer_version": index.indexer_version,
        "indexed_occurrences": len(index.occurrences),
        "definitions": sum(item.role == "definition" for item in index.occurrences),
        "references_and_occurrences": sum(
            item.role in {"reference", "occurrence"} for item in index.occurrences
        ),
        "queries": len(results),
        "queries_with_resolved_symbols": sum(item["resolved_symbols"] > 0 for item in results),
        "expected_ranges": sum(item["expected_ranges"] for item in results),
        "matched_expected_ranges": sum(item["matched_expected_ranges"] for item in results),
        "range_coverage_recall": (
            sum(item["matched_expected_ranges"] for item in results)
            / sum(item["expected_ranges"] for item in results)
        ),
        "no_evidence_candidates": len(absent),
        "query_results": results,
        "method_note": (
            "Real scip-python indexing over the checked-out NLP source tree; normalized "
            "occurrences are read through an in-memory PostgREST double. Exact identifier "
            "to SCIP symbol resolution only; coverage is measured, not ranking."
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    assert len(index.occurrences) > 0
    assert len(results) == 3
    assert report["queries_with_resolved_symbols"] == 3
    assert report["matched_expected_ranges"] >= 2, report["query_results"]
    assert report["no_evidence_candidates"] == 0

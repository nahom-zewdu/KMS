"""Validate task-specific retrieval benchmark labels against fixture source."""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path


_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "retrieval"
_REPOSITORY_ROOT = _FIXTURE_ROOT / "mini_repo_v2"
_BENCHMARK_PATH = _FIXTURE_ROOT / "retrieval_tasks_v1.json"
_EXPECTED_COUNTS = {
    "declaration_discovery": 10,
    "call_site_context": 10,
    "passage_retrieval": 10,
    "no_evidence": 3,
}


def _source(path: str) -> str:
    return (_REPOSITORY_ROOT / path).read_text(encoding="utf-8")


def _declared_names(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_retrieval_task_benchmark_has_balanced_task_types_and_unique_ids():
    benchmark = json.loads(_BENCHMARK_PATH.read_text(encoding="utf-8"))
    queries = benchmark["queries"]

    assert benchmark["version"] == 1
    assert benchmark["corpus"]["root"] == "mini_repo_v2"
    assert len(queries) == sum(_EXPECTED_COUNTS.values())
    assert Counter(query["task_type"] for query in queries) == _EXPECTED_COUNTS
    assert len({query["id"] for query in queries}) == len(queries)

    for query in queries:
        assert query["question"].strip()
        assert query["terms"]
        assert all(term.strip() for term in query["terms"])


def test_declaration_labels_resolve_to_real_python_declarations():
    benchmark = json.loads(_BENCHMARK_PATH.read_text(encoding="utf-8"))

    for query in benchmark["queries"]:
        if query["task_type"] != "declaration_discovery":
            continue

        assert query["expected_symbols"]
        assert query["expected_paths"]
        assert not query.get("expected_ranges")

        for path in query["expected_paths"]:
            source = _source(path)
            declared = _declared_names(source)
            assert set(query["expected_symbols"]) <= declared, (
                query["id"], path, query["expected_symbols"], declared
            )


def test_call_site_and_passage_labels_resolve_to_term_bearing_ranges():
    benchmark = json.loads(_BENCHMARK_PATH.read_text(encoding="utf-8"))

    for query in benchmark["queries"]:
        if query["task_type"] not in {"call_site_context", "passage_retrieval"}:
            continue

        assert query["expected_ranges"], query["id"]
        for label in query["expected_ranges"]:
            lines = _source(label["file_path"]).splitlines()
            start = label["start_line"]
            end = label["end_line"]
            assert 1 <= start <= end <= len(lines), (query["id"], label)
            excerpt = "\n".join(lines[start - 1:end]).casefold()
            assert any(term.casefold() in excerpt for term in query["terms"]), (
                query["id"], label, query["terms"], excerpt
            )


def test_no_evidence_queries_have_no_matching_terms_or_positive_labels():
    benchmark = json.loads(_BENCHMARK_PATH.read_text(encoding="utf-8"))
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _REPOSITORY_ROOT.rglob("*.py")
    ).casefold()

    for query in benchmark["queries"]:
        if query["task_type"] != "no_evidence":
            continue

        assert query["expected_symbols"] == []
        assert query["expected_paths"] == []
        assert query["expected_ranges"] == []
        assert all(term.casefold() not in corpus for term in query["terms"]), (
            query["id"], query["terms"]
        )

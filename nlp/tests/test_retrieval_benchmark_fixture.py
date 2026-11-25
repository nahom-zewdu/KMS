"""Sanity checks for the versioned KRT-03 retrieval benchmark fixture."""

import json
from pathlib import Path


_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "retrieval"


def test_benchmark_has_unique_queries_and_declared_scope():
    benchmark = json.loads((_FIXTURE_ROOT / "benchmark.json").read_text())
    queries = benchmark["queries"]

    assert benchmark["version"] == 1
    assert benchmark["default_scope"] == {
        "company_id": "company-a",
        "repository_id": "mini-repo-a",
        "snapshot_id": "mini-repo-a@fixture-v1",
        "source_revision": "fixture-v1",
    }
    assert len(queries) == 20
    assert len({query["id"] for query in queries}) == len(queries)


def test_expected_code_paths_and_symbols_exist_in_fixture():
    benchmark = json.loads((_FIXTURE_ROOT / "benchmark.json").read_text())
    repository = _FIXTURE_ROOT / "mini_repo"
    source_files = list(repository.rglob("*.py"))
    source_text = "\n".join(path.read_text() for path in source_files)

    for query in benchmark["queries"]:
        for relative_path in query.get("expected_paths", []):
            assert (repository / relative_path).is_file(), (
                query["id"], relative_path
            )
        for symbol in query.get("expected_symbols", []):
            assert symbol.split(".")[-1] in source_text, (
                query["id"], symbol
            )


def test_expected_event_ids_exist_and_other_tenant_event_is_not_relevant():
    benchmark = json.loads((_FIXTURE_ROOT / "benchmark.json").read_text())
    events = json.loads((_FIXTURE_ROOT / "events.json").read_text())
    company_a_ids = {
        event["record_id"]
        for event in events
        if event["company_id"] == "company-a"
    }

    for query in benchmark["queries"]:
        for event_id in query.get("expected_event_ids", []):
            assert event_id in company_a_ids, (query["id"], event_id)

    assert "pull/42" in {
        event["record_id"] for event in events
        if event["company_id"] == "company-b"
    }
    scope_query = next(
        query for query in benchmark["queries"] if query["id"] == "scope-01"
    )
    assert scope_query["expected_event_ids"] == []



def test_benchmark_marks_only_explicit_lexical_queries_as_supported():
    benchmark = json.loads((_FIXTURE_ROOT / "benchmark.json").read_text())
    supported = [
        query for query in benchmark["queries"]
        if "lexical_input" in query
    ]

    assert len(supported) == 8
    assert all(
        set(query["lexical_input"]).issubset(
            {"file_paths", "qualified_names", "identifiers"}
        )
        for query in supported
    )
    assert all(
        query.get("expected_paths") or query.get("expected_symbols")
        for query in supported
    )

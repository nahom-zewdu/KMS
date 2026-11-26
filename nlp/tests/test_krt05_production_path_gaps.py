"""KRT-05 production-path regression tests for ambiguity and structured counts."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from codebase.symbol_retriever import CodeSymbolRetriever
from query_engine.core import QueryEngine
from query_engine.evidence_gatherer import BoundedEvidenceGatherer
from query_engine.planned_query import PlannedQueryExecutor
from query_engine.query_plan import QueryScope
from query_engine.symbol_resolution import ConservativeScipSymbolResolver
from query_engine.structured import answer_structured_question


_FIXTURES = Path(__file__).parent / "fixtures" / "evaluation"


class _UnusedOccurrences:
    def list_file_occurrences(self, **_kwargs):
        return []

    def find_references(self, **_kwargs):
        return []


class _UnusedSourceChunks:
    def retrieve(self, **_kwargs):
        return []


def _fixture_declarations():
    root = _FIXTURES / "ambiguous_symbols"
    rows = []
    for filename in ("worker_a.py", "worker_b.py"):
        path = root / filename
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "process_task"
        )
        lines = source.splitlines(keepends=True)
        start_byte = sum(len(line.encode("utf-8")) for line in lines[:function.lineno - 1])
        end_byte = sum(len(line.encode("utf-8")) for line in lines[:function.end_lineno])
        rows.append({
            "id": f"decl-{filename}",
            "symbol_id": f"symbol-{filename}",
            "company_id": "benchmark-company",
            "repository_id": "benchmark-repository",
            "snapshot_id": "benchmark-snapshot-v1",
            "source_revision": "benchmark-revision-v1",
            "name": function.name,
            "qualified_name": f"{filename[:-3]}.{function.name}",
            "file_path": filename,
            "kind": "function",
            "start_line": function.lineno,
            "end_line": function.end_lineno,
            "start_byte": start_byte,
            "end_byte": end_byte,
            "content_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        })
    return rows


def test_duplicate_fixture_declarations_abstain_through_planned_query_pipeline():
    rows = _fixture_declarations()
    db = _FixtureSupabase({
        "repositories": [{
            "id": "benchmark-repository",
            "company_id": "benchmark-company",
            "active_snapshot_id": "benchmark-snapshot-v1",
        }],
        "code_symbols": rows,
    })
    declarations = CodeSymbolRetriever(db)
    occurrences = _UnusedOccurrences()
    gatherer = BoundedEvidenceGatherer(
        source_chunks=_UnusedSourceChunks(),
        symbols=declarations,
        occurrences=occurrences,
    )
    resolver = ConservativeScipSymbolResolver(declarations, occurrences)
    synthesis_calls = []
    executor = PlannedQueryExecutor(
        evidence_gatherer=gatherer,
        symbol_resolver=resolver,
        synthesizer=lambda *args: synthesis_calls.append(args) or {},
    )

    result = executor.execute(
        "Find the declaration of process_task where multiple declarations share that identifier.",
        scope=QueryScope(
            company_id="benchmark-company",
            repository_id="benchmark-repository",
        ),
    )

    assert result.plan.intent.value == "declaration_discovery"
    symbol_query = next(
        query for table, query in db.queries if table == "code_symbols"
    )
    assert symbol_query.filters == {
        "company_id": "benchmark-company",
        "repository_id": "benchmark-repository",
        "snapshot_id": "benchmark-snapshot-v1",
        "ilike:qualified_name": "%process_task%",
    }
    assert symbol_query.pattern == "%process_task%"
    assert result.reason == "ambiguous_declaration"
    assert result.answer["abstain_reason"] == "ambiguous_declaration"
    assert result.evidence == ()
    assert synthesis_calls == []



def test_explicit_file_path_disambiguates_duplicate_fixture_declarations():
    rows = _fixture_declarations()
    rows.append({
        **rows[0],
        "id": "decl-worker-a-cleanup",
        "symbol_id": "symbol-worker-a-cleanup",
        "name": "cleanup",
        "qualified_name": "worker_a.cleanup",
        "start_line": 1,
        "end_line": 1,
    })
    db = _FixtureSupabase({
        "repositories": [{
            "id": "benchmark-repository",
            "company_id": "benchmark-company",
            "active_snapshot_id": "benchmark-snapshot-v1",
        }],
        "code_symbols": rows,
    })
    declarations = CodeSymbolRetriever(db)
    occurrences = _UnusedOccurrences()
    gatherer = BoundedEvidenceGatherer(
        source_chunks=_UnusedSourceChunks(),
        symbols=declarations,
        occurrences=occurrences,
    )
    executor = PlannedQueryExecutor(
        evidence_gatherer=gatherer,
        symbol_resolver=ConservativeScipSymbolResolver(declarations, occurrences),
        synthesizer=lambda _query, evidence: {
            "claims": [{
                "text": "The declaration is in worker_a.py.",
                "evidence_ids": [evidence[0].evidence_id],
            }],
        },
    )

    result = executor.execute(
        "Find the declaration of process_task in worker_a.py.",
        scope=QueryScope(
            company_id="benchmark-company",
            repository_id="benchmark-repository",
        ),
    )

    assert result.completed
    assert result.reason is None
    assert len(result.evidence) == 1
    assert result.evidence[0].file_path == "worker_a.py"
    assert result.answer["abstain_reason"] is None


class _TableQuery:
    def __init__(self, rows):
        self.rows = list(rows)
        self.filters = {}
        self.maximum = None

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def ilike(self, key, pattern):
        self.pattern = pattern
        self.filters[f"ilike:{key}"] = pattern
        return self

    def order(self, key, **_kwargs):
        self.orders = getattr(self, "orders", []) + [key]
        return self

    def limit(self, maximum):
        self.maximum = maximum
        return self

    def execute(self):
        rows = list(self.rows)
        for key, value in self.filters.items():
            if key.startswith("ilike:"):
                column = key.split(":", 1)[1]
                needle = value.strip("%").casefold()
                rows = [row for row in rows if needle in str(row.get(column) or "").casefold()]
            else:
                rows = [row for row in rows if row.get(key) == value]
        for column in reversed(getattr(self, "orders", [])):
            rows.sort(key=lambda row: str(row.get(column) or ""))
        if self.maximum is not None:
            rows = rows[:self.maximum]
        return SimpleNamespace(data=rows)


class _FixtureSupabase:
    def __init__(self, tables):
        self.tables = tables
        self.queries = []

    def table(self, name):
        query = _TableQuery(self.tables.get(name, []))
        self.queries.append((name, query))
        return query


def _structured_repository_rows():
    fixture = json.loads(
        (_FIXTURES / "structured_company_repositories_v1.json").read_text(encoding="utf-8")
    )
    company_id = "benchmark-company"
    return [
        {"company_id": company_id, **repository}
        for repository in fixture["companies"][company_id]["repositories"]
    ]



class _FakeRedis:
    def __init__(self):
        self.messages = []

    def publish(self, channel, message):
        self.messages.append((channel, message))


def test_query_engine_routes_repository_count_before_source_retrieval(monkeypatch):
    db = _FixtureSupabase({
        "repositories": _structured_repository_rows(),
    })
    engine = QueryEngine(supabase=db, redis=_FakeRedis())

    def unexpected_source_retrieval(*_args, **_kwargs):
        raise AssertionError("structured facts must not enter source retrieval")

    monkeypatch.setattr(
        "query_engine.core.retrieve_source_chunks",
        unexpected_source_retrieval,
    )

    result = engine.handle_query({
        "record_id": "krt05-structured-count",
        "company_id": "benchmark-company",
        "content": "How many repositories are connected to this company?",
    })

    payload = json.loads(result)
    assert payload["answer"] == "2 connected repositories are registered for this company."
    assert payload["abstain_reason"] is None
    assert engine.redis.messages[0][0] == "query_results:krt05-structured-count"



def test_query_engine_abstains_if_structured_repository_count_cannot_be_verified(monkeypatch):
    db = _FixtureSupabase({"repositories": []})
    engine = QueryEngine(supabase=db, redis=_FakeRedis())

    monkeypatch.setattr("query_engine.core.answer_structured_question", lambda *_args, **_kwargs: None)

    def unexpected_source_retrieval(*_args, **_kwargs):
        raise AssertionError("unverified structured facts must not enter source retrieval")

    monkeypatch.setattr(
        "query_engine.core.retrieve_source_chunks",
        unexpected_source_retrieval,
    )

    result = engine.handle_query({
        "record_id": "krt05-structured-count-unavailable",
        "company_id": "benchmark-company",
        "content": "How many repositories are connected to this company?",
    })

    payload = json.loads(result)
    assert payload["abstain_reason"] == "structured_evidence_unavailable"
    assert engine.redis.messages[0][0] == "query_results:krt05-structured-count-unavailable"


def test_structured_repository_count_uses_authoritative_company_scoped_fixture():
    db = _FixtureSupabase({
        "repositories": _structured_repository_rows(),
    })

    result = answer_structured_question(
        db,
        "How many repositories are connected to this company?",
        "benchmark-company",
    )

    assert result["answer"] == "2 connected repositories are registered for this company."
    assert result["confidence"] == "high"
    assert result["abstain_reason"] is None
    assert {source["record_id"] for source in result["sources"]} == {
        "repo-catalog", "repo-billing",
    }
    repository_query = next(query for table, query in db.queries if table == "repositories")
    assert repository_query.filters == {"company_id": "benchmark-company"}


def test_structured_repository_count_does_not_include_another_company():
    rows = _structured_repository_rows() + [{
        "company_id": "another-company",
        "id": "repo-private",
        "full_name": "private/other",
    }]
    db = _FixtureSupabase({"repositories": rows})

    result = answer_structured_question(
        db,
        "How many repositories are connected to this company?",
        "benchmark-company",
    )

    assert result["answer"].startswith("2 connected repositories")
    assert all(
        source["record_id"] != "repo-private"
        for source in result["sources"]
    )


def test_structured_repository_count_reports_zero_without_fabricating_sources():
    result = answer_structured_question(
        _FixtureSupabase({"repositories": []}),
        "How many repositories are connected to this company?",
        "benchmark-company",
    )

    assert result["answer"].startswith("0 connected repositories")
    assert result["sources"] == []

"""End-to-end lexical benchmark through the real parser/indexer/retriever.

The in-memory PostgREST double exercises the application pipeline without
claiming PostgreSQL query-planner, RLS, or deployed-schema integration.
"""

from __future__ import annotations

from pathlib import Path
import re
from types import SimpleNamespace

from codebase.symbol_indexer import CodeSymbolIndexer
from query_engine.code_lexical import CodeLexicalRetriever
from query_engine.lexical_benchmark import run_lexical_benchmark


_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "retrieval"
_REPOSITORY_ROOT = _FIXTURE_ROOT / "mini_repo"
_COMPANY_ID = "company-a"
_REPOSITORY_ID = "mini-repo-a"
_SNAPSHOT_ID = "mini-repo-a@fixture-v1"
_SOURCE_REVISION = "fixture-v1"


class MemoryQuery:
    """Small deterministic subset of the PostgREST query chain used by KRT-02."""

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
            return SimpleNamespace(data=[])

        selected = list(rows)
        for operator, column, value in self.filters:
            if operator == "eq":
                selected = [row for row in selected if row.get(column) == value]
            else:
                expression = "".join(
                    ".*" if char == "%" else "." if char == "_" else re.escape(char)
                    for char in value
                )
                matcher = re.compile(f"^{expression}$", re.IGNORECASE)
                selected = [
                    row for row in selected
                    if matcher.match(str(row.get(column) or ""))
                ]
        for column in reversed(self.orders):
            selected.sort(key=lambda row: row.get(column) or "")
        if self.maximum is not None:
            selected = selected[:self.maximum]
        return SimpleNamespace(data=selected)


class MemorySupabase:
    """Store symbol rows and one active snapshot using the Supabase table API."""

    def __init__(self):
        self.rows = {
            "repositories": [
                {
                    "id": _REPOSITORY_ID,
                    "company_id": _COMPANY_ID,
                    "active_snapshot_id": _SNAPSHOT_ID,
                }
            ],
            "code_symbols": [],
        }

    def table(self, name):
        return MemoryQuery(self, name)


def test_real_fixture_indexer_retriever_pipeline_has_measurable_lexical_baseline():
    database = MemorySupabase()
    source_files = [
        {
            "path": path.relative_to(_REPOSITORY_ROOT).as_posix(),
            "content": path.read_text(encoding="utf-8"),
        }
        for path in _REPOSITORY_ROOT.rglob("*.py")
    ]

    indexing = CodeSymbolIndexer(database).index_files(
        source_files,
        repository_id=_REPOSITORY_ID,
        snapshot_id=_SNAPSHOT_ID,
        company_id=_COMPANY_ID,
        source_revision=_SOURCE_REVISION,
    )
    assert indexing["files_seen"] == 4
    assert indexing["files_indexed"] == 4
    assert indexing["files_unsupported"] == 0
    assert indexing["symbols_persisted"] > 0

    retriever = CodeLexicalRetriever(database, top_k=30)
    benchmark = run_lexical_benchmark(
        _FIXTURE_ROOT / "benchmark.json",
        retriever,
    )

    assert benchmark["evaluated_queries"] == 8
    assert benchmark["unsupported_queries"] == [
        "path-02",
        "reference-01",
        "code-01",
        "code-02",
        "code-03",
        "multi-01",
        "multi-02",
        "event-01",
        "event-02",
        "empty-01",
        "scope-01",
        "scope-02",
    ]
    assert benchmark["metrics"] == {
        "recall_at_1": 1.0,
        "recall_at_5": 1.0,
        "recall_at_10": 1.0,
        "mrr": 1.0,
    }, benchmark["query_results"]

    # The unrelated repository has no active pointer in this tenant; retrieval
    # must return no candidates rather than borrowing the fixture's snapshot.
    assert retriever.retrieve(
        company_id=_COMPANY_ID,
        repository_id="mini-repo-b",
        identifiers=["PaymentService"],
    ) == []

    persisted = database.rows["code_symbols"]
    assert all(row["company_id"] == _COMPANY_ID for row in persisted)
    assert all(row["repository_id"] == _REPOSITORY_ID for row in persisted)
    assert all(row["snapshot_id"] == _SNAPSHOT_ID for row in persisted)
    assert all(row["source_revision"] == _SOURCE_REVISION for row in persisted)

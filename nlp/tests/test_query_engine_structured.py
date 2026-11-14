import json
from types import SimpleNamespace

from query_engine.structured import answer_structured_question


class Query:
    def __init__(self, rows):
        self.rows = list(rows)
        self.filters = {}

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def in_(self, key, values):
        self.filters[key] = set(values)
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        rows = self.rows
        for key, value in self.filters.items():
            if isinstance(value, set):
                rows = [row for row in rows if row.get(key) in value]
            else:
                rows = [row for row in rows if row.get(key) == value]
        return SimpleNamespace(data=rows)


class Supabase:
    def __init__(self, **tables):
        self.tables = tables

    def table(self, name):
        return Query(self.tables.get(name, []))


def test_file_count_uses_all_company_repository_file_rows():
    db = Supabase(
        repositories=[
            {"id": "r1", "company_id": "c1", "full_name": "acme/api"},
            {"id": "r2", "company_id": "c1", "full_name": "acme/web"},
        ],
        codebase_files=[
            {"repository_id": "r1", "file_path": "a.go"},
            {"repository_id": "r1", "file_path": "b.go"},
            {"repository_id": "r2", "file_path": "app.tsx"},
        ],
    )

    result = answer_structured_question(db, "How many files are indexed for this company?", "c1")

    assert "3 files" in result["answer"]
    assert "acme/api: 2" in result["answer"]
    assert "acme/web: 1" in result["answer"]


def test_ramp_step_count_uses_company_scoped_active_plan():
    db = Supabase(ramp_plans=[
        {"id": "p1", "company_id": "c1", "role": "backend-engineer", "steps": [{}, {}, {}, {}, {}, {}]},
    ])
    context = json.dumps({"plan_id": "p1", "role": "backend-engineer", "steps": []})

    result = answer_structured_question(db, "How many steps do we have for this ramp?", "c1", context)

    assert "has 6 steps" in result["answer"]


def test_ownership_answer_uses_file_ownership_edges_not_generated_people():
    db = Supabase(
        entities=[
            {"id": "f1", "name": "routes.go", "type": "FILE",
             "metadata": {"file_path": "api/handlers/routes.go"}},
            {"id": "p1", "name": "nahom-zewdu", "type": "person", "metadata": {}},
        ],
        edges=[
            {"company_id": "c1", "source_id": "p1", "target_id": "f1", "type": "OWNS", "confidence": 0.8},
        ],
    )
    context = json.dumps({
        "kind": "ramp_overview",
        "steps": [{"target": {"files": [{"path": "api/handlers/routes.go"}]}}],
    })

    result = answer_structured_question(db, "Can you show me the owners?", "c1", context)

    assert result["owners"] == ["nahom-zewdu"]
    assert "api/handlers/routes.go" in result["answer"]


def test_authorship_is_reported_as_last_author_not_ownership():
    db = Supabase(
        repositories=[{"id": "r1", "full_name": "acme/api"}],
        codebase_files=[
            {"repository_id": "r1", "file_path": "api/handlers/routes.go", "last_author": "nahom-zewdu"},
            {"repository_id": "r1", "file_path": "api/handlers/query.go", "last_author": "nahom-zewdu"},
            {"repository_id": "r1", "file_path": "api/handlers/github.go", "last_author": None},
        ],
    )
    context = json.dumps({
        "steps": [{
            "target": {"files": [
                {"path": "api/handlers/routes.go"},
                {"path": "api/handlers/query.go"},
            ]}
        }]
    })

    result = answer_structured_question(db, "Who implemented api handlers?", "c1", context)

    assert "last-author metadata" in result["answer"]
    assert "nahom-zewdu" in result["answer"]
    assert result["owners"] == []
    assert "not everyone who implemented" in result["answer"]


def test_followup_file_question_resolves_paths_from_conversation_history():
    db = Supabase(
        repositories=[{"id": "r1", "full_name": "acme/api"}],
        codebase_files=[
            {"repository_id": "r1", "file_path": "api/handlers/routes.go", "language": "Go",
             "module_path": "api/handlers", "last_author": "nahom-zewdu"},
            {"repository_id": "r1", "file_path": "api/handlers/github.go", "language": "Go",
             "module_path": "api/handlers", "last_author": None},
        ],
    )
    history = [
        {"role": "assistant", "content": "The current Ramp references api/handlers/routes.go and api/handlers/github.go."}
    ]

    result = answer_structured_question(
        db, "Can you tell me anything about those files?", "c1",
        json.dumps({"kind": "ramp_overview", "steps": []}),
        conversation_history=history,
    )

    assert "api/handlers/routes.go" in result["answer"]
    assert "api/handlers/github.go" in result["answer"]
    assert "Go" in result["answer"]

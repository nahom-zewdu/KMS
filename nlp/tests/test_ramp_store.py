import copy

import pytest

from ramp.generator_v2 import RampPlanner
from ramp.models import ImplementationSurface
from ramp.store import RampPlanPersistenceError, RampStore


class Query:
    def __init__(self, database, table_name):
        self.database = database
        self.table_name = table_name
        self.filters = {}
        self.record = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self.filters[field] = value
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def upsert(self, record, on_conflict):
        assert on_conflict == "company_id,role"
        self.record = record
        return self

    def execute(self):
        if self.record is not None:
            if self.database.write_error:
                raise self.database.write_error
            existing = next(
                (
                    row for row in self.database.rows
                    if row["company_id"] == self.record["company_id"]
                    and row["role"] == self.record["role"]
                ),
                None,
            )
            if existing is None:
                self.database.rows.append(copy.deepcopy(self.record))
            else:
                existing.update(copy.deepcopy(self.record))
            return type("Response", (), {"data": [self.record]})()

        rows = [
            row for row in self.database.rows
            if all(row.get(field) == value for field, value in self.filters.items())
        ]
        return type("Response", (), {"data": rows})()


class Database:
    def __init__(self, rows=None, write_error=None):
        self.rows = copy.deepcopy(rows or [])
        self.write_error = write_error

    def table(self, name):
        assert name == "ramp_plans"
        return Query(self, name)


def step(step_id, title):
    return {
        "id": step_id,
        "title": title,
        "do": "Inspect the implementation.",
        "done_when": "Confirm the behavior in source.",
        "evidence": [{"path": "api/server.go"}],
        "machine": {"eligible": True},
    }


def plan(step_id, title):
    return {
        "company_id": "company-a",
        "role": "backend-engineer",
        "employee_name": "Engineer",
        "steps": [step(step_id, title)],
        "meta": {"source": "ramp_v2", "selected_count": 1},
        "is_active": True,
    }


def existing_row():
    return {
        "id": "previous-plan",
        "company_id": "company-a",
        "role": "backend-engineer",
        "steps": [step("previous-step", "Existing valid step")],
        "meta": {"source": "ramp_v2"},
        "is_active": True,
    }


def test_failed_plan_upsert_preserves_previous_active_plan():
    database = Database(
        [existing_row()],
        write_error=RuntimeError("sensitive database detail"),
    )
    store = RampStore(database)

    with pytest.raises(RampPlanPersistenceError) as exc_info:
        store.save_plan(plan("new-step", "New step"))

    assert exc_info.value.error_type == "RuntimeError"
    assert "sensitive database detail" not in str(exc_info.value)
    active = store.get_active("company-a", "backend-engineer")
    assert active["id"] == "previous-plan"
    assert active["steps"][0]["id"] == "previous-step"


def test_generation_persistence_failure_keeps_previous_active_plan():
    database = Database(
        [existing_row()],
        write_error=RuntimeError("database unavailable"),
    )
    planner = RampPlanner(database)
    planner.evidence.implementation_surfaces = lambda _company_id: [
        ImplementationSurface(
            ref="api/server.go",
            path="api/server.go",
            repository_id="repo-1",
            module_path="api",
            language="Go",
            importance=0.9,
        )
    ]
    planner.evidence.module_records = lambda _company_id: []
    planner.evidence.ownership = lambda _company_id: []
    planner.evidence.github_history = lambda _company_id: []
    planner.evidence.implementation_relationships = lambda _company_id: []
    planner.store = RampStore(database)

    with pytest.raises(RampPlanPersistenceError):
        planner.generate("backend-engineer", "company-a")

    active = planner.get_active("company-a", "backend-engineer")
    assert active["id"] == "previous-plan"
    assert active["steps"][0]["id"] == "previous-step"


def test_valid_plan_upsert_replaces_existing_active_plan():
    store = RampStore(Database([existing_row()]))

    store.save_plan(plan("new-step", "New valid step"))

    active = store.get_active("company-a", "backend-engineer")
    assert active["steps"][0]["id"] == "new-step"
    assert active["steps"][0]["title"] == "New valid step"
    assert active["is_active"] is True


def test_empty_or_ineligible_plan_is_rejected_before_upsert():
    database = Database([existing_row()])
    store = RampStore(database)
    invalid = plan("invalid-step", "Invalid step")
    invalid["steps"][0]["machine"]["eligible"] = False

    with pytest.raises(ValueError, match="not eligible"):
        store.save_plan(invalid)

    assert store.get_active("company-a", "backend-engineer")["id"] == "previous-plan"
    assert len(database.rows) == 1

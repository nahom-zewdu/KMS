from unittest.mock import Mock

import pytest

from ramp.store import RampStore


class Query:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.filters = []
        self.record = None
        self.conflict = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def upsert(self, record, on_conflict=None):
        self.record = dict(record)
        self.conflict = on_conflict
        return self

    def execute(self):
        rows = [
            row for row in self.rows
            if all(row.get(field) == value for field, value in self.filters)
        ]
        if self.record is not None:
            return type("Response", (), {"data": [self.record]})()
        return type("Response", (), {"data": rows})()


def store_with_plan():
    plan = {
        "id": "plan-1",
        "company_id": "company-1",
        "steps": [{"id": "step-1"}, {"id": "step-2"}],
    }
    tables = {
        "ramp_plans": Query([plan]),
        "ramp_step_feedback": Query(),
    }
    client = Mock()
    client.table.side_effect = lambda name: tables[name]
    return RampStore(client), tables


def test_submit_feedback_validates_step_and_persists_one_user_rating():
    store, tables = store_with_plan()

    result = store.submit_step_feedback(
        "plan-1", "step-1", "company-1", "user-1", "useful", "Clear next steps"
    )

    saved = tables["ramp_step_feedback"].record
    assert result["rating"] == "useful"
    assert saved["company_id"] == "company-1"
    assert saved["user_id"] == "user-1"
    assert saved["reason"] == "Clear next steps"
    assert tables["ramp_step_feedback"].conflict == "plan_id,step_id,user_id"


@pytest.mark.parametrize("rating", ["", "bad", "USEFUL?"])
def test_submit_feedback_rejects_unknown_rating(rating):
    store, _ = store_with_plan()
    with pytest.raises(ValueError, match="rating"):
        store.submit_step_feedback("plan-1", "step-1", "company-1", "user-1", rating)


def test_submit_feedback_rejects_cross_company_plan():
    store, tables = store_with_plan()
    with pytest.raises(ValueError, match="not found"):
        store.submit_step_feedback("plan-1", "step-1", "company-2", "user-1", "useful")
    assert tables["ramp_step_feedback"].record is None


def test_submit_feedback_rejects_step_not_in_plan():
    store, tables = store_with_plan()
    with pytest.raises(KeyError, match="step_id"):
        store.submit_step_feedback("plan-1", "other-step", "company-1", "user-1", "useful")
    assert tables["ramp_step_feedback"].record is None


def test_submit_feedback_rejects_long_reason():
    store, tables = store_with_plan()
    with pytest.raises(ValueError, match="1000"):
        store.submit_step_feedback(
            "plan-1", "step-1", "company-1", "user-1", "useful", "x" * 1001
        )
    assert tables["ramp_step_feedback"].record is None


def test_submit_feedback_updates_existing_engineer_rating_in_place():
    store, tables = store_with_plan()
    tables["ramp_step_feedback"] = Query([{
        "id": "feedback-1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "plan_id": "plan-1",
        "step_id": "step-1",
        "company_id": "company-1",
        "user_id": "user-1",
        "rating": "partially_useful",
        "reason": None,
    }])

    store.submit_step_feedback(
        "plan-1", "step-1", "company-1", "user-1", "useful", "Much clearer now"
    )

    saved = tables["ramp_step_feedback"].record
    assert saved["id"] == "feedback-1"
    assert saved["created_at"] == "2026-01-01T00:00:00+00:00"
    assert saved["rating"] == "useful"


def test_get_step_feedback_is_scoped_to_requesting_engineer():
    store, tables = store_with_plan()
    tables["ramp_step_feedback"] = Query([{
        "plan_id": "plan-1",
        "step_id": "step-1",
        "company_id": "company-1",
        "user_id": "user-1",
        "rating": "useful",
        "reason": "Clear",
    }])

    result = store.get_step_feedback("plan-1", "step-1", "company-1", "user-1")

    assert result["rating"] == "useful"
    assert ("user_id", "user-1") in tables["ramp_step_feedback"].filters


def test_feedback_summary_returns_aggregates_without_user_identifiers():
    store, tables = store_with_plan()
    tables["ramp_step_feedback"] = Query([
        {"step_id": "step-1", "rating": "useful", "user_id": "secret-user"},
        {"step_id": "step-1", "rating": "not_useful", "user_id": "secret-user-2"},
        {"step_id": "step-2", "rating": "partially_useful", "user_id": "secret-user-3"},
    ])
    store.supabase.table.side_effect = lambda name: tables[name]

    result = store.feedback_summary("plan-1", "company-1")

    assert result["total"] == 3
    assert result["ratings"] == {
        "not_useful": 1,
        "partially_useful": 1,
        "useful": 1,
    }
    assert result["steps"]["step-1"]["not_useful"] == 1
    assert "user_id" not in str(result)
    assert "reason" not in str(result)

from datetime import datetime, timezone
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from codebase.baseline import CodebaseBaselineSync


class UpsertQuery:
    def __init__(self):
        self.calls = []

    def upsert(self, rows, **kwargs):
        self.calls.append((rows, kwargs))
        return self

    def execute(self):
        return SimpleNamespace(data=[])


def make_issue(
    number,
    *,
    state="open",
    updated_at=None,
    body="Issue body",
    labels=None,
    assignee=None,
    pull_request=None,
):
    updated_at = updated_at or datetime(2026, 11, 10, tzinfo=timezone.utc)
    return SimpleNamespace(
        number=number,
        title=f"Issue {number}",
        body=body,
        state=state,
        html_url=f"https://github.com/acme/service/issues/{number}",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        updated_at=updated_at,
        labels=labels or [],
        assignee=assignee,
        pull_request=pull_request,
    )


def test_issue_backfill_is_bounded_batched_and_does_not_import_pull_requests():
    supabase = Mock()
    query = UpsertQuery()
    supabase.table.return_value = query
    repo = Mock()
    repo.get_issues.return_value = [
        make_issue(
            1,
            body="x" * 10050,
            labels=[SimpleNamespace(name=f"label-{i}") for i in range(25)],
        ),
        make_issue(2, state="closed"),
        make_issue(3, pull_request={"url": "https://api.github.com/pulls/3"}),
    ]
    sync = CodebaseBaselineSync(supabase)

    count = sync._backfill_issue_events(
        repo, "acme/service", "company-a", max_issues=10, batch_size=1
    )

    assert count == 2
    assert len(query.calls) == 2
    first_batch, first_options = query.calls[0]
    second_batch, second_options = query.calls[1]
    assert first_options == {"on_conflict": "delivery_id", "ignore_duplicates": True}
    assert second_options == first_options
    first = first_batch[0]
    second = second_batch[0]
    assert first["source"] == "github"
    assert first["event_type"] == "issues"
    assert first["company_id"] == "company-a"
    assert first["processed"] is True
    assert first["truncated"] is True
    assert len(first["payload"]["issue"]["body"]) == 10000
    assert len(first["payload"]["issue"]["labels"]) == 20
    assert first["payload"]["issue"]["state"] == "open"
    assert second["payload"]["issue"]["state"] == "closed"
    assert first["created_at"] == "2026-11-10T00:00:00+00:00"
    assert first["delivery_id"].startswith(
        "backfill:github-issue:company-a:acme/service:1:"
    )
    assert first["id"] == str(uuid.uuid5(uuid.NAMESPACE_URL, first["delivery_id"]))
    repo.get_issues.assert_called_once_with(state="all", sort="updated", direction="desc")


def test_issue_backfill_rejects_invalid_tenant_and_limits():
    sync = CodebaseBaselineSync(Mock())
    repo = Mock()

    with pytest.raises(ValueError):
        sync._backfill_issue_events(repo, "acme/service", "default")
    with pytest.raises(ValueError):
        sync._backfill_issue_events(repo, "acme/service", "company-a", max_issues=0)
    repo.get_issues.assert_not_called()

def test_issue_backfill_caps_scanned_github_items_including_pull_requests():
    supabase = Mock()
    query = UpsertQuery()
    supabase.table.return_value = query
    repo = Mock()
    repo.get_issues.return_value = [
        make_issue(10, pull_request={"url": "https://api.github.com/pulls/10"}),
        make_issue(11),
    ]
    sync = CodebaseBaselineSync(supabase)

    count = sync._backfill_issue_events(
        repo, "acme/service", "company-a", max_issues=1
    )

    assert count == 0
    assert query.calls == []


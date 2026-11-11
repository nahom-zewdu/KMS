from unittest.mock import Mock

import pytest

from ramp.evidence import RampEvidenceRetrievalError, RampEvidenceStore


class Query:
    def __init__(self, rows, error=None):
        self.rows = rows
        self.error = error

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self.error:
            raise self.error
        return type("Response", (), {"data": self.rows})()


def test_required_empty_file_query_is_a_valid_empty_result():
    supabase = Mock()
    supabase.table.side_effect = lambda name: {
        "repositories": Query([{"id": "repo-1"}]),
        "codebase_files": Query([]),
    }[name]

    assert RampEvidenceStore(supabase).implementation_surfaces("company-a") == []


def test_required_file_query_failure_is_explicit_and_sanitized():
    supabase = Mock()
    supabase.table.side_effect = lambda name: {
        "repositories": Query([{"id": "repo-1"}]),
        "codebase_files": Query([], RuntimeError("sensitive database detail")),
    }[name]

    with pytest.raises(RampEvidenceRetrievalError) as exc_info:
        RampEvidenceStore(supabase).implementation_surfaces("company-a")

    error = exc_info.value
    assert error.source == "codebase_files"
    assert error.operation == "list implementation surfaces"
    assert error.error_type == "RuntimeError"
    assert "sensitive database detail" not in str(error)


def test_repository_query_failure_is_not_interpreted_as_empty_evidence():
    supabase = Mock()
    supabase.table.return_value = Query([], RuntimeError("connection refused"))

    with pytest.raises(RampEvidenceRetrievalError) as exc_info:
        RampEvidenceStore(supabase).implementation_surfaces("company-a")

    assert exc_info.value.source == "repositories"
    assert "connection refused" not in str(exc_info.value)

def test_implementation_surfaces_retain_repository_identity_for_source_links():
    supabase = Mock()
    supabase.table.side_effect = lambda name: {
        "repositories": Query([{
            "id": "repo-1",
            "full_name": "acme/service",
            "default_branch": "release/2026",
        }]),
        "codebase_files": Query([{
            "id": "file-1",
            "repository_id": "repo-1",
            "file_path": "api/handlers/github webhook.go",
            "module_path": "api/handlers",
            "language": "Go",
            "importance_score": 0.9,
            "metadata": {"existing": True},
        }]),
    }[name]

    surfaces = RampEvidenceStore(supabase).implementation_surfaces("company-a")

    assert len(surfaces) == 1
    assert surfaces[0].metadata == {
        "existing": True,
        "repository_full_name": "acme/service",
        "repository_default_branch": "release/2026",
    }

def test_contribution_issues_require_open_unassigned_labeled_issue_and_indexed_paths():
    issue = {
        "number": 42,
        "title": "Add retry visibility to webhook processing",
        "body": (
            "Acceptance criteria:\\n"
            "- [ ] Show retry state in the response\\n"
            "- [ ] Add a regression test\\n"
            "Relevant file: api/handlers/webhook.go"
        ),
        "state": "open",
        "html_url": "https://github.com/acme/service/issues/42",
        "labels": [{"name": "good first issue"}],
        "assignee": None,
    }
    events = [
        {
            "delivery_id": "delivery-42",
            "company_id": "company-a",
            "event_type": "issues",
            "payload": {"repo": "acme/service", "action": "opened", "issue": issue},
            "created_at": "2026-11-01T00:00:00Z",
        },
        {
            "delivery_id": "delivery-43",
            "company_id": "company-a",
            "event_type": "issues",
            "payload": {
                "repo": "acme/service",
                "issue": {**issue, "number": 43, "assignee": {"login": "alice"}},
            },
            "created_at": "2026-11-02T00:00:00Z",
        },
        {
            "delivery_id": "delivery-44",
            "company_id": "company-a",
            "event_type": "issues",
            "payload": {
                "repo": "acme/service",
                "issue": {**issue, "number": 44, "labels": []},
            },
            "created_at": "2026-11-03T00:00:00Z",
        },
    ]
    supabase = Mock()
    supabase.table.side_effect = lambda name: {
        "repositories": Query([{
            "id": "repo-1",
            "full_name": "acme/service",
            "default_branch": "main",
        }]),
        "events": Query(events),
        "codebase_files": Query([{
            "repository_id": "repo-1",
            "file_path": "api/handlers/webhook.go",
        }]),
    }[name]

    results = RampEvidenceStore(supabase).contribution_issues("company-a")

    assert len(results) == 1
    assert results[0]["ref"] == "github-issue:delivery-42:42"
    assert results[0]["file_paths"] == ["api/handlers/webhook.go"]
    assert results[0]["acceptance_checks"] == [
        "- [ ] Show retry state in the response",
        "- [ ] Add a regression test",
    ]
    assert results[0]["url"] == "https://github.com/acme/service/issues/42"


def test_contribution_issues_reject_paths_not_present_in_company_repository_index():
    issue = {
        "number": 7,
        "title": "Update webhook retry behavior",
        "body": (
            "- [ ] Update retry behavior\\n"
            "- [ ] Add tests\\n"
            "Relevant file: api/handlers/missing.go"
        ),
        "state": "open",
        "labels": [{"name": "help wanted"}],
        "assignee": None,
    }
    supabase = Mock()
    supabase.table.side_effect = lambda name: {
        "repositories": Query([{"id": "repo-1", "full_name": "acme/service"}]),
        "events": Query([{
            "delivery_id": "delivery-7",
            "company_id": "company-a",
            "payload": {"repo": "acme/service", "issue": issue},
        }]),
        "codebase_files": Query([{
            "repository_id": "repo-1",
            "file_path": "api/handlers/webhook.go",
        }]),
    }[name]

    assert RampEvidenceStore(supabase).contribution_issues("company-a") == []


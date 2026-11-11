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


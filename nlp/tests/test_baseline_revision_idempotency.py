"""Regression tests for idempotent baseline revision handling."""

from types import SimpleNamespace
from unittest.mock import Mock

from codebase.baseline import CodebaseBaselineSync


def _sync_with_repository_row(row):
    sync = CodebaseBaselineSync.__new__(CodebaseBaselineSync)
    sync.supabase = Mock()
    query = Mock()
    query.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query
    query.execute.return_value = SimpleNamespace(data=[row] if row else [])
    sync.supabase.table.return_value = query
    return sync


def test_ready_baseline_at_same_revision_is_already_indexed():
    sync = _sync_with_repository_row({
        "baseline_status": "ready",
        "baseline_revision": "abc123",
    })

    assert sync._is_revision_already_ready("org/repo", "company-a", "abc123") is True


def test_ready_baseline_at_different_revision_requires_sync():
    sync = _sync_with_repository_row({
        "baseline_status": "ready",
        "baseline_revision": "old123",
    })

    assert sync._is_revision_already_ready("org/repo", "company-a", "new456") is False


def test_indexing_baseline_is_not_treated_as_complete():
    sync = _sync_with_repository_row({
        "baseline_status": "indexing",
        "baseline_revision": "abc123",
    })

    assert sync._is_revision_already_ready("org/repo", "company-a", "abc123") is False


def test_missing_repository_row_requires_sync():
    sync = _sync_with_repository_row(None)

    assert sync._is_revision_already_ready("org/repo", "company-a", "abc123") is False

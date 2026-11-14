"""Regression tests for database-coordinated baseline synchronization."""

from types import SimpleNamespace
from unittest.mock import Mock

from codebase.baseline import CodebaseBaselineSync


def _sync_with_claim_status(status):
    sync = CodebaseBaselineSync.__new__(CodebaseBaselineSync)
    sync.gh = Mock()
    repository = sync.gh.get_repo.return_value
    repository.default_branch = "main"
    repository.get_branch.return_value.commit.sha = "abc123"
    sync.supabase = Mock()
    sync.supabase.rpc.return_value.execute.return_value = SimpleNamespace(data=status)
    return sync


def test_same_ready_revision_is_skipped_by_atomic_claim():
    sync = _sync_with_claim_status("ready")

    assert sync.sync_repository("org/repo", "company-a") is True

    sync.supabase.rpc.assert_called_once_with(
        "claim_repository_baseline",
        {
            "p_full_name": "org/repo",
            "p_company_id": "company-a",
            "p_source_revision": "abc123",
            "p_run_id": sync.supabase.rpc.call_args.args[1]["p_run_id"],
            "p_lease_seconds": 180,
        },
    )
    sync.supabase.table.assert_not_called()


def test_concurrent_repository_claim_is_left_retryable():
    sync = _sync_with_claim_status("busy")

    assert sync.sync_repository("org/repo", "company-a") is False

    sync.supabase.table.assert_not_called()
    assert sync.supabase.rpc.call_count == 1


def test_unknown_claim_response_does_not_start_indexing():
    sync = _sync_with_claim_status(None)

    assert sync.sync_repository("org/repo", "company-a") is False

    sync.supabase.table.assert_not_called()


def test_company_scope_is_required_before_claiming():
    sync = _sync_with_claim_status("ready")

    try:
        sync.sync_repository("org/repo", "default")
    except ValueError as exc:
        assert "company_id" in str(exc)
    else:
        raise AssertionError("expected invalid company scope to be rejected")

    sync.supabase.rpc.assert_not_called()

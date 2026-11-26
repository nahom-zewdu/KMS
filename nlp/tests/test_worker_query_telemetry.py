from types import SimpleNamespace
from unittest.mock import patch


def _query_handler_class():
    # QueryHandler currently initializes default clients at import time.
    with (
        patch("utils.supabase.init_supabase", return_value=None),
        patch("utils.redis.init_redis", return_value=None),
    ):
        from worker.query import QueryHandler
    return QueryHandler


def test_worker_emits_correlated_content_free_lifecycle_logs(caplog):
    query_handler = _query_handler_class()
    handler = query_handler.__new__(query_handler)
    handler.query_engine = SimpleNamespace(handle_query=lambda job: "ok")
    job = {"record_id": "query-123", "content": "private question"}

    with caplog.at_level("INFO", logger="query"):
        handler.process(job, "query_jobs", "1-0", None)

    messages = [record.getMessage() for record in caplog.records]
    assert any("query_id=query-123 stage=worker_start" in item for item in messages)
    assert any("query_id=query-123 stage=worker_complete" in item for item in messages)
    assert all("private question" not in item for item in messages)


def test_worker_failure_logs_type_and_reraises_without_error_text(caplog):
    handler = QueryHandler.__new__(QueryHandler)

    def fail(_job):
        raise RuntimeError("private provider response")

    handler.query_engine = SimpleNamespace(handle_query=fail)
    with caplog.at_level("ERROR", logger="query"):
        try:
            handler.process({"record_id": "query-456"}, "query_jobs", "1-0", None)
        except RuntimeError as exc:
            assert str(exc) == "private provider response"
        else:
            raise AssertionError("worker failure should be re-raised")

    messages = [record.getMessage() for record in caplog.records]
    assert any("query_id=query-456 stage=worker_failure" in item for item in messages)
    assert any("error_type=RuntimeError" in item for item in messages)
    assert all("private provider response" not in item for item in messages)

# worker/query.py
"""
Handles query_jobs → search KG → LLM answer.
"""
import logging
import time
from query_engine.core import QueryEngine
from utils.supabase import init_supabase
from utils.redis import init_redis

logger = logging.getLogger("query")

class QueryHandler:
    def __init__(self, supabase = init_supabase(), redis_client = init_redis()):
        self.supabase = supabase
        self.redis = redis_client
        self.query_engine = QueryEngine(self.supabase, self.redis)

    def process(self, job: dict, stream: str, msg_id: str, redis_client):
        query_id = str(job.get("record_id") or "unknown")
        started = time.perf_counter()
        logger.info(
            "kms_query_stage query_id=%s stage=worker_start stream=%s",
            query_id, stream,
        )
        try:
            self.query_engine.handle_query(job)
        except Exception as exc:
            logger.error(
                "kms_query_stage query_id=%s stage=worker_failure duration_ms=%.3f error_type=%s",
                query_id, (time.perf_counter() - started) * 1000, type(exc).__name__,
            )
            raise  # Let consumer retry
        logger.info(
            "kms_query_stage query_id=%s stage=worker_complete duration_ms=%.3f",
            query_id, (time.perf_counter() - started) * 1000,
        )
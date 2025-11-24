# worker/query.py
"""
Handles query_jobs → search KG → LLM answer.
"""
import logging
from query_engine.core import QueryEngine
from utils.supabase import init_supabase
from utils.redis import init_redis
class QueryHandler:
    def __init__(self, supabase = init_supabase(), redis_client = init_redis()):
        self.supabase = supabase
        self.redis = redis_client
        self.query_engine = QueryEngine(self.supabase, self.redis)

    def process(self, job: dict, stream: str, msg_id: str, redis_client):
        try:
            self.query_engine.handle_query(job)
            # Only ack if success (already handled inside QueryEngine via publish)
            redis_client.xack(stream, "kms", msg_id)
            redis_client.xdel(stream, msg_id)
        except Exception as e:
            logging.error(f"QueryHandler failed: {e}")
            raise  # Let consumer retry
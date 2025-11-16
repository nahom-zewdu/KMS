# worker/query.py
"""
Handles query_jobs → search KG → LLM answer.
"""
import logging
from query_handler import handle_query as _handle_query
from utils.supabase import init_supabase
from utils.redis import init_redis
class QueryHandler:
    def __init__(self, supabase = init_supabase(), redis_client = init_redis()):
        self.supabase = supabase
        self.redis = redis_client

    def process(self, job: dict, stream: str, msg_id: str, redis_client):
        _handle_query(job, self.supabase, self.redis)  # supabase injected globally
        
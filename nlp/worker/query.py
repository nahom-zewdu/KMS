# worker/query.py
"""
Handles query_jobs → search KG → LLM answer.
"""
import logging
from query_handler import handle_query as _handle_query

class QueryHandler:
    def process(self, job: dict, stream: str, msg_id: str, redis_client):
        _handle_query(job, None, redis_client)  # supabase injected globally
        
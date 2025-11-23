# nlp/query_engine/analytics.py
"""
Query analytics — know exactly what your team asks.

Tracks:
- question text (anonymized hash)
- route taken
- latency
- cache hit/miss
- success/failure
"""

from datetime import datetime
from supabase import Client
import logging
import hashlib

logger = logging.getLogger(__name__)

def log_query(
    supabase: Client,
    query_id: str,
    question: str,
    route: str,
    latency_ms: float,
    cache_hit: bool,
    answer_length: int
):
    """
    Log query for product analytics and improvement.
    """
    try:
        supabase.table("query_logs").insert({
            "query_id": query_id,
            "question_hash": hashlib.sha256(question.encode()).hexdigest(),
            "route": route,
            "latency_ms": round(latency_ms, 2),
            "cache_hit": cache_hit,
            "answer_length": answer_length,
            "asked_at": datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        logger.warning(f"Query log failed: {e}")

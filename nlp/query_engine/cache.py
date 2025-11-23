# nlp/query_engine/cache.py
"""
Redis-powered answer caching layer.

- 24h TTL for exact question matches
- 7-day TTL for graph-only answers (they rarely change)
- <30ms warm hits → Slack feels instant
- Cache invalidation on new ingestion (future)
"""

import hashlib
import logging
from typing import Optional
from redis import Redis

logger = logging.getLogger(__name__)

class QueryCache:
    """
    High-hit-rate Redis cache for query answers.
    """

    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    def _hash(self, question: str) -> str:
        """Deterministic cache key."""
        return hashlib.sha256(question.strip().lower().encode()).hexdigest()

    def get(self, question: str) -> Optional[str]:
        """Return cached answer or None."""
        key = f"cache:answer:{self._hash(question)}"
        try:
            cached = self.redis.get(key)
            if cached:
                logger.info("Cache HIT")
                return cached.decode()
        except Exception as e:
            logger.warning(f"Cache get failed: {e}")
        return None

    def set(self, question: str, answer: str, is_graph_only: bool = False):
        """Cache answer with appropriate TTL."""
        key = f"cache:answer:{self._hash(question)}"
        ttl = 60 * 60 * 24 * 7 if is_graph_only else 60 * 60 * 24  # 7d vs 1d
        try:
            self.redis.setex(key, ttl, answer)
            logger.info(f"Cache SET (TTL: {ttl//3600}h)")
        except Exception as e:
            logger.warning(f"Cache set failed: {e}")

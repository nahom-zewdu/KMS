# nlp/query_engine/core.py
"""
KMS Query Engine v2 — The Oracle
Single public entrypoint. Minimal. Unbreakable.
"""
import time
import logging
from typing import Dict, Any
from supabase import Client
from redis import Redis
from .router import classify_intent
from .retrieval import DualRetriever
from .synthesizer import synthesize
from .cache import QueryCache
from .analytics import log_query

logger = logging.getLogger("engine.core")

class QueryEngine:
    """The final, minimal, production-ready query engine."""
    
    def __init__(self, supabase: Client, redis: Redis):
        self.supabase = supabase
        self.redis = redis
        self.cache = QueryCache(redis)
        self.retriever = DualRetriever(supabase)

    def handle_query(self, job: Dict[str, Any]) -> str:
        """Public method called by consumer."""
        start = time.time()
        qid = job["record_id"]
        question = job["content"].strip()

        logger.info(f"Query {qid} | {question}")

        # 1. Cache
        if cached := self.cache.get(question):
            self.redis.publish(f"query_results:{qid}", cached)
            return cached

        # 2. Route
        priority = classify_intent(question)

        # 3. Retrieve both
        graph_facts, vector_context = self.retriever.retrieve(question)
        
        logger.info(f"Graph facts: {graph_facts}| Vector context: {vector_context}")
        # 4. Synthesize
        answer = synthesize(question, graph_facts, vector_context, priority)

        # 5. Cache + log + publish
        self.cache.set(question, answer)
        latency = (time.time() - start) * 1000
        log_query(self.supabase, qid, question, priority, latency, len(graph_facts) > 0, len(answer))

        self.redis.publish(f"query_results:{qid}", answer)
        logger.info(f"Answer sent | {qid} | {latency:.1f}ms")

        return answer
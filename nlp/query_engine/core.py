# nlp/query_engine/core.py
"""
Core query engine orchestrator.

This is the single public entrypoint for all @KMS queries.
Routes questions to the optimal path and returns final answer.
"""

from typing import Dict, Any
import logging
import time
from .graph.traverser import GraphTraverser
from .vector.retriever import VectorRetriever
from .router import classify_intent
from .synthesizer import synthesize
from .cache import QueryCache
from .decay import update_edge_lifecycle
from .analytics import log_query

logger = logging.getLogger(__name__)

class QueryEngine:
    """
    High-performance query engine for KMS.

    Routes natural language questions to the fastest, most accurate path:
    - Graph-first: ownership, fixes, assignments
    - Vector-first: historical context, "why" questions
    - Hybrid: complex multi-hop questions

    All answers include inline citations and confidence scoring with caching, decay, and analytics.
    """

    def __init__(self, supabase_client, redis_client):
        self.supabase = supabase_client
        self.redis = redis_client
        self.graph = GraphTraverser(supabase_client)
        self.vector = VectorRetriever(supabase_client)
        self.cache = QueryCache(redis_client)

    def handle_query(self, job: Dict[str, Any]) -> str:
        start_time = time.time()
        query_id = job["record_id"]
        question = job["content"].strip()

        logger.info(f"Query {query_id} | {question}")

        if not question:
            answer = "Please ask a clear question."
            self.redis.publish(f"query_results:{query_id}", answer)
            return answer

        # 1. Cache check
        cached = self.cache.get(question)
        if cached:
            latency = (time.time() - start_time) * 1000
            log_query(self.supabase, query_id, question, "cached", latency, True, len(cached))
            self.redis.publish(f"query_results:{query_id}", cached)
            return cached

        # 2. Route
        route = classify_intent(question)
        path = route["path"]

        # 3. Execute
        graph_answer = None
        vector_chunks = None

        if path in ("graph", "hybrid"):
            graph_answer = self.graph.traverse(question)

        if not graph_answer or path in ("vector", "hybrid"):
            vector_chunks = self.vector.retrieve(question)

        # 4. Synthesize
        answer = synthesize(
            question=question,
            graph_facts=[graph_answer] if graph_answer else None,
            vector_chunks=vector_chunks,
            route=path
        )

        # 5. Cache
        is_graph_only = bool(graph_answer and not vector_chunks)
        self.cache.set(question, answer, is_graph_only=is_graph_only)

        # 6. Analytics
        latency = (time.time() - start_time) * 1000
        log_query(self.supabase, query_id, question, path, latency, False, len(answer))

        # 7. Publish
        self.redis.publish(f"query_results:{query_id}", answer)
        logger.info(f"Answer sent | {query_id} | {latency:.1f}ms")

        return answer

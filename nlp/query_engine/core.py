# nlp/query_engine/core.py
"""
Core query engine orchestrator.

This is the single public entrypoint for all @KMS queries.
Routes questions to the optimal path and returns final answer.
Now with:
- Full error isolation
- Circuit breaker pattern
- Graceful degradation
- Observability hooks
"""

from typing import Dict, Any
import logging
import time
import datetime
from datetime import timedelta

from redis.exceptions import RedisError
from supabase import Client

from .graph.traverser import GraphTraverser
from .vector.retriever import VectorRetriever
from .router import classify_intent
from .synthesizer import synthesize
from .cache import QueryCache
from .analytics import log_query
from .errors import safe_answer, RetrievalError

logger = logging.getLogger(__name__)

class QueryEngine:
    def __init__(self, supabase_client: Client, redis_client):
        self.supabase = supabase_client
        self.redis = redis_client
        self.graph = GraphTraverser(supabase_client)
        self.vector = VectorRetriever(supabase_client)
        self.cache = QueryCache(redis_client)

        # Circuit breaker state
        self.failures = 0
        self.last_failure_time = None

    def _is_healthy(self) -> bool:
        """Simple circuit breaker disable LLM paths if failing."""
        if self.failures > 5:
            if self.last_failure_time and datetime.datetime.now(datetime.UTC) - self.last_failure_time < timedelta(minutes=5):
                return False
        return True

    @safe_answer("I'm experiencing issues right now. The team has been notified.")
    def handle_query(self, job: Dict[str, Any]) -> str:
        start_time = time.time()
        query_id = job["record_id"]
        question = job["content"].strip()

        logger.info(f"Query {query_id} | {question}")

        if not question:
            answer = "Please ask a clear question."
            self.redis.publish(f"query_results:{query_id}", answer)
            return answer

        # 1. Cache first (always safe)
        cached = self.cache.get(question)
        if cached:
            latency = (time.time() - start_time) * 1000
            log_query(self.supabase, query_id, question, "cached", latency, True, len(cached))
            self.redis.publish(f"query_results:{query_id}", cached)
            return cached

        # 2. Health check
        if not self._is_healthy():
            answer = "I'm temporarily in safe mode. Only cached answers available."
            self.cache.set(question, answer)
            self.redis.publish(f"query_results:{query_id}", answer)
            return answer

        try:
            # 3. Route
            route = classify_intent(question)
            path = route["path"]

            # 4. Execute with isolation
            graph_answer = None
            vector_chunks = []
            if path in ("graph", "hybrid"):
                try:
                    graph_answer = self.graph.traverse(question)
                except Exception as e:
                    logger.warning(f"Graph path failed: {e}")
                    path = "vector"  # degrade gracefully

            if not graph_answer or path in ("vector", "hybrid"):
                try:
                    vector_chunks = self.vector.retrieve(question)
                except Exception as e:
                    logger.warning(f"Vector path failed: {e}")
                    vector_chunks = []

            logger.info(f"Vector chunks retrieved: {len(vector_chunks)}")

            # 5. Synthesize (only if we have something)
            if not graph_answer and (not vector_chunks or len(vector_chunks) == 0):
                answer = "I couldn't find any relevant information yet."
            else:
                answer = synthesize(
                    question=question,
                    graph_facts=[graph_answer] if graph_answer else None,
                    vector_chunks=vector_chunks,
                    route=path
                )

            # 6. Success path
            self.failures = 0  # reset circuit breaker
            is_graph_only = bool(graph_answer and not vector_chunks)
            self.cache.set(question, answer, is_graph_only=is_graph_only)

        except RedisError as e:
            logger.error(f"Redis failed: {e}")
            answer = "I'm having connectivity issues. Your question was logged."
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            self.failures += 1
            self.last_failure_time = datetime.datetime.now(datetime.UTC)
            answer = "Something went wrong. Retrying usually works."

        # 7. Always log + publish
        latency = (time.time() - start_time) * 1000
        log_query(self.supabase, query_id, question, path if 'path' in locals() else "error", latency, False, len(answer))
        self.redis.publish(f"query_results:{query_id}", answer)
        logger.info(f"Answer sent | {query_id} | {latency:.1f}ms")

        return answer
    
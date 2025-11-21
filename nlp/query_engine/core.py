# nlp/query_engine/core.py
"""
Core query engine orchestrator.

This is the single public entrypoint for all @KMS queries.
Routes questions to the optimal path and returns final answer.
"""

from typing import Dict, Any
import logging
from .graph.traverser import GraphTraverser
from .vector.retriever import VectorRetriever
from .router import classify_intent
from .synthesizer import synthesize

logger = logging.getLogger(__name__)

class QueryEngine:
    """
    High-performance query engine for KMS.

    Routes natural language questions to the fastest, most accurate path:
    - Graph-first: ownership, fixes, assignments
    - Vector-first: historical context, "why" questions
    - Hybrid: complex multi-hop questions

    All answers include inline citations and confidence scoring.
    """

    def __init__(self, supabase_client, redis_client):
        self.supabase = supabase_client
        self.redis = redis_client
        self.logger = logger
        self.graph = GraphTraverser(supabase_client)
        self.vector = VectorRetriever(supabase_client)

    def handle_query(self, job: Dict[str, Any]) -> str:
        """
        Process a query_job from Redis stream.

        Args:
            job: Dict containing:
                - record_id: str (query ID)
                - content: str (user question)
                - created_at: str (optional timestamp)

        Returns:
            Final answer string with citations (published to Redis)
        """
        query_id = job["record_id"]
        question = job["content"].strip()

        self.logger.info(f"Query {query_id} | {question}")

        if not question:
            answer = "Please ask a clear question."
        else:
            # 1. Route
            route = classify_intent(question)
            logger.info(f"Route: {route['path']} (confidence: {route['confidence']:.0%})")

            # 2. Execute
            graph_answer = None
            vector_chunks = None

            if route["path"] in ("graph", "hybrid"):
                graph_answer = self.graph.traverse(question)

            if not graph_answer or route["path"] in ("vector", "hybrid"):
                vector_chunks = self.vector.retrieve(question)

            # 3. Synthesize
            answer = synthesize(
                question=question,
                graph_facts=[graph_answer] if graph_answer else None,
                vector_chunks=vector_chunks,
                route=route["path"]
            )

        # Publish result
        self.redis.publish(f"query_results:{query_id}", answer)
        self.logger.info(f"Answer published | {query_id}")

        return answer

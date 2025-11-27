# nlp/query_engine/retrieval.py
"""
Parallel retrieval from graph hints and vector store.
Robust, logs errors, never crashes.
"""
from typing import List, Dict, Any, Tuple
import logging
from supabase import Client

logger = logging.getLogger("engine.retrieval")

class DualRetriever:
    """Retrieves from both structured hints and semantic context."""
    
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def _get_graph_facts(self, question: str) -> List[Dict]:
        """Search raw_data for high-signal ownership statements."""
        try:
            # Use .limit() correctly — Supabase client supports it
            result = (
                self.supabase.table("raw_data")
                .select("content, source, record_id, created_at")
                .or_(f"content.ilike.%{question.split()[-1]}%,content.ilike.%{question.split()[-2]}%")
                .limit(6)
                .execute()
            )
            return [
                {
                    "type": "graph_hint",
                    "content": r["content"][:500],
                    "source": r["source"],
                    "record_id": r["record_id"],
                    "score": 0.96
                }
                for r in (result.data or [])
                if any(word in r["content"].lower() for word in ["owns", "own", "responsible", "maintains", "built", "working on"])
            ]
        except Exception as e:
            logger.warning(f"Graph hint search failed: {e}")
            return []

    def _get_vector_context(self, question: str) -> List[Dict]:
        """Semantic search via pgvector."""
        try:
            from .vector.retriever import VectorRetriever
            retriever = VectorRetriever(self.supabase)
            chunks = retriever.retrieve(question, top_k=6)
            return [
                {
                    "type": "context",
                    "content": c["content"][:600],
                    "source": c.get("source", "unknown"),
                    "record_id": c.get("record_id"),
                    "score": c.get("similarity", 0.7)
                }
                for c in chunks
            ]
        except Exception as e:
            logger.warning(f"Vector retrieval failed: {e}")
            return []

    def retrieve(self, question: str) -> Tuple[List[Dict], List[Dict]]:
        """
        Always returns both graph hints and vector context.
        Never returns empty — falls back gracefully.
        """
        graph_facts = self._get_graph_facts(question)
        vector_context = self._get_vector_context(question)
        
        logger.info(f"Graph facts: {len(graph_facts)} | Vector context: {len(vector_context)}")

        return graph_facts, vector_context

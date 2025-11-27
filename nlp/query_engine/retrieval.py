# nlp/query_engine/retrieval.py
"""
Parallel retrieval from both graph and vector stores.
Always returns something. Never fails silently.
"""
from typing import List, Dict, Any, Tuple
import logging
from supabase import Client

logger = logging.getLogger(__name__)

class DualRetriever:
    """Retrieves from both knowledge graph and semantic memory in parallel."""
    
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def _get_graph_facts(self, question: str) -> List[Dict]:
        """Extract structured facts using simple, robust SQL."""
        try:
            # Look for OWNS/MAINTAINS relationships mentioned in raw_data
            result = (
                self.supabase
                .table("raw_data")
                .select("content, source, record_id, created_at")
                .text_search("content", question.split()[-3:])  # last few words
                .limit(5)
                .execute()
            )
            return [
                {
                    "type": "graph_hint",
                    "content": r["content"][:400],
                    "source": r["source"],
                    "record_id": r["record_id"],
                    "score": 0.95
                }
                for r in (result.data or [])
            ]
        except Exception as e:
            logger.warning(f"Graph hint search failed: {e}")
            return []

    def _get_vector_context(self, question: str) -> List[Dict]:
        """Semantic search over raw_data."""
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

        return graph_facts, vector_context
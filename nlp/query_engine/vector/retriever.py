# nlp/query_engine/vector/retriever.py
"""
Vector-first retrieval path.

Uses pgvector semantic search on raw_data to answer historical and contextual questions.
"""

from typing import List, Dict, Any
from sentence_transformers import SentenceTransformer
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def get_embedder():
    """Cached sentence transformer model."""
    return SentenceTransformer('all-MiniLM-L6-v2')

class VectorRetriever:
    """
    Retrieves semantically relevant context using pgvector.

    Fast path for "why", "when", "what happened" questions.
    """

    def __init__(self, supabase_client):
        self.supabase = supabase_client
        self.model = get_embedder()

    def _embed(self, text: str) -> list:
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def retrieve(self, question: str, top_k: int = 8) -> List[Dict]:
        """Fetch top-k relevant chunks."""
        embedding = self._embed(question)
        response = (
            self.supabase.rpc("match_documents", {
                "query_embedding": embedding,
                "match_count": top_k,
                "match_threshold": 0.65
            })
            .execute()
        )
        chunks = response.data or []
        return chunks

    def answer(self, question: str) -> str:
        """Simple RAG answer (bridge to v2)."""
        chunks = self.retrieve(question)
        if not chunks:
            return "I don't know."

        context = "\n\n".join([
            f"[{i+1}] {c['content'][:500]}..."
            for i, c in enumerate(chunks)
        ])

        prompt = f"""
Answer in 1-2 sentences using only this context:

Context:
{context}

Question: {question}

Answer:
        """.strip()

        from engine.llm import llm_infer
        return llm_infer(prompt) or "I don't know."

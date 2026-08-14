# nlp/query_engine/vector/retriever.py
"""
Vector-first retrieval path.

Uses pgvector semantic search on raw_data to answer historical and contextual questions.
"""

import re
from typing import List, Dict, Any
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def get_embedder():
    """Cached sentence transformer model."""
    logger.info("Loading sentence transformer model...")

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")

    logger.info(
        "Sentence transformer loaded: %d dimensions",
        model.get_sentence_embedding_dimension(),
    )

    return model

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

    def _call_match_documents(self, embedding: list, top_k: int, threshold: float, company_id: str) -> List[Dict[str, Any]]:
        response = self.supabase.rpc(
            "match_documents",
            {
                "query_embedding": embedding,
                "match_count": top_k,
                "match_threshold": threshold,
                "filter_company_id": company_id,
            },
        ).execute()
        return response.data or []

    def retrieve(self, question: str, top_k: int = 8, company_id: str = "default") -> List[Dict]:
        """Fetch top-k relevant chunks."""
        embedding = self._embed(question)
        thresholds = [0.65, 0.55, 0.45]
        for threshold in thresholds:
            try:
                chunks = self._call_match_documents(embedding, top_k, threshold, company_id)
                if chunks:
                    if threshold != thresholds[0]:
                        logger.info("Vector retrieval low recall at %.2f, relaxing threshold to %.2f and returning %d chunks.", thresholds[0], threshold, len(chunks))
                    return chunks
            except Exception as e:
                logger.warning("Vector retrieval failed at threshold %.2f: %s", threshold, e)
                continue

        # Keyword fallback company-scoped (authorship / recent Slack)
        try:
            tokens = [t for t in re.findall(r"[a-zA-Z]{4,}", question.lower()) if t not in {
                "what", "who", "whom", "working", "about", "with", "from", "this", "that", "have", "been", "does", "into"
            }][:4]
            if not tokens:
                return []
            q = (
                self.supabase.table("raw_data")
                .select("content,source,record_id,company_id,created_at")
                .eq("company_id", company_id)
                .order("created_at", desc=True)
                .limit(20)
            )
            # PostgREST: or=(content.ilike.%tok1%,content.ilike.%tok2%)
            ors = ",".join(f"content.ilike.%{t}%" for t in tokens)
            res = q.or_(ors).execute()
            rows = res.data or []
            if rows:
                logger.info("Keyword fallback returned %d raw_data rows", len(rows))
                return [
                    {
                        "content": r.get("content") or "",
                        "source": r.get("source") or "raw",
                        "record_id": r.get("record_id") or "",
                        "company_id": r.get("company_id"),
                        "similarity": 0.55,
                    }
                    for r in rows[:top_k]
                ]
        except Exception as e:
            logger.warning("Keyword fallback failed: %s", e)
        return []

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

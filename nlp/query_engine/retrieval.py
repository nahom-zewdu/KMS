# nlp/query_engine/retrieval.py
"""
Clean & Reliable Retrieval — Fixed for your current schema.
"""
from typing import List, Dict
from supabase import Client
from .analyzer import analyze_query
from .vector.retriever import VectorRetriever
import logging

logger = logging.getLogger(__name__)

class AdaptiveRetriever:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def retrieve(self, question: str) -> List[Dict]:
        analysis = analyze_query(question)
        logger.info("------------------------------")
        logger.info(f"Query analysis: {analysis}")

        chunks: List[Dict] = []

        # === GRAPH SEARCH — SIMPLE & WORKING ===
        if analysis.get("entities"):
            for entity in analysis["entities"][:5]:
                try:
                    # Search by name only — use two separate queries instead of .or_()
                    # Query 1: source.name matches entity
                    res1 = (
                        self.supabase.table("edges")
                        .select(
                            "source:entities!source_id(name)",
                            "target:entities!target_id(name)",
                            "type",
                            "confidence"
                        )
                        .ilike("source.name", f"%{entity}%")
                        .limit(8)
                        .execute()
                    )

                    # Query 2: target.name matches entity
                    res2 = (
                        self.supabase.table("edges")
                        .select(
                            "source:entities!source_id(name)",
                            "target:entities!target_id(name)",
                            "type",
                            "confidence"
                        )
                        .ilike("target.name", f"%{entity}%")
                        .limit(8)
                        .execute()
                    )

                    # Merge and deduplicate results
                    seen_edges = set()
                    for res in [res1, res2]:
                        for row in res.data or []:
                            src = row.get("source", {}).get("name", "Unknown")
                            tgt = row.get("target", {}).get("name", "Unknown")
                            rel = row.get("type", "RELATED")
                            conf = row.get("confidence", 0.9)

                            edge_key = (src, rel, tgt)
                            if edge_key not in seen_edges:
                                seen_edges.add(edge_key)
                                chunks.append({
                                    "content": f"{src} {rel} {tgt}",
                                    "source": "graph",
                                    "record_id": "graph",
                                    "score": conf
                                })
                except Exception as e:
                    logger.warning(f"Graph search failed for '{entity}': {e}")

        # === VECTOR SEARCH (already working) ===
        try:
            vec = VectorRetriever(self.supabase)
            vec_chunks = vec.retrieve(analysis.get("rewritten", question), top_k=8)
            for c in vec_chunks:
                chunks.append({
                    "content": c.get("content", "")[:900],
                    "source": c.get("source", "raw"),
                    "record_id": c.get("record_id", ""),
                    "score": c.get("similarity", 0.7)
                })
        except Exception as e:
            logger.warning(f"Vector failed: {e}")

        # Dedupe + Rank
        seen = set()
        unique = []
        for c in sorted(chunks, key=lambda x: x.get("score", 0.5), reverse=True):
            key = c.get("content", "")[:120]
            if key not in seen:
                seen.add(key)
                unique.append(c)
                if len(unique) >= 10:
                    break

        logger.info(f"Retrieved {len(unique)} adaptive chunks")
        return unique

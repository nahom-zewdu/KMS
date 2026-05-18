# nlp/query_engine/retrieval.py
"""
Simplified & Reliable Retrieval — No more complex nested or() failures.
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

        # === SIMPLE GRAPH SEARCH (Reliable) ===
        if analysis.get("entities"):
            for entity in analysis["entities"][:4]:
                try:
                    # Search entities first (uses search_vector)
                    entity_res = (
                        self.supabase.table("entities")
                        .select("id, name, type")
                        .or_(f"name.ilike.%{entity}%,search_vector.ilike.%{entity}%")
                        .limit(5)
                        .execute()
                    )

                    entity_ids = [e["id"] for e in entity_res.data or []]

                    if entity_ids:
                        # Then find edges connected to these entities
                        edge_res = (
                            self.supabase.table("edges")
                            .select(
                                "source:entities!source_id(name)",
                                "target:entities!target_id(name)",
                                "type",
                                "confidence"
                            )
                            .in_("source_id", entity_ids)
                            .or_("target_id.in.(" + ",".join(entity_ids) + ")")  # safer syntax
                            .limit(8)
                            .execute()
                        )

                        for row in edge_res.data or []:
                            src = row.get("source", {}).get("name", "Unknown")
                            tgt = row.get("target", {}).get("name", "Unknown")
                            rel = row.get("type", "RELATED")
                            conf = row.get("confidence", 0.9)

                            chunks.append({
                                "content": f"{src} {rel} {tgt}",
                                "source": "graph",
                                "record_id": "graph",
                                "score": conf
                            })
                except Exception as e:
                    logger.warning(f"Graph search failed for '{entity}': {e}")

        # === VECTOR SEARCH ===
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

        # Rank and dedupe
        seen = set()
        unique = []
        for c in sorted(chunks, key=lambda x: x.get("score", 0.5), reverse=True):
            key = c.get("content", "")[:150]
            if key not in seen:
                seen.add(key)
                unique.append(c)
                if len(unique) >= 10:
                    break

        logger.info(f"Retrieved {len(unique)} adaptive chunks")
        return unique

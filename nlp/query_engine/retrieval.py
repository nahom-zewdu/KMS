# nlp/query_engine/retrieval.py
"""
FINAL VERSION — Works perfectly with your actual Supabase schema.
Uses proper PostgREST syntax for nested foreign tables.
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

        if analysis.get("entities"):
            relations = analysis["relations"] or ["OWNS", "MAINTAINS", "FIXES", "ASSIGNED_TO", "PART_OF", "DEPLOYED_IN", "MOVED_TO", "MIGRATED_TO", "IMPLEMENTED"]
            
            for entity in analysis["entities"][:4]:
                try:
                    res = self.supabase.rpc("search_edges_by_entity", {
                        "search_term": entity,
                        "relation_types": relations
                    }).execute()

                    for row in res.data or []:
                        src = row.get("source_name", "Unknown")
                        tgt = row.get("target_name", "Unknown")
                        rel_type = row.get("type", "RELATED_TO")
                        conf = row.get("confidence", 0.9)

                        chunks.append({
                            "content": f"{src} {rel_type} {tgt}",
                            "source": "graph",
                            "record_id": f"edge-{row.get('id', '')[:8]}",
                            "score": conf
                        })
                except Exception as e:
                    logger.warning(f"Graph RPC search failed for '{entity}': {e}")

        # === 2. VECTOR SEARCH on rewritten query ===
        try:
            vec_retriever = VectorRetriever(self.supabase)
            vec_chunks = vec_retriever.retrieve(
                analysis.get("rewritten", question),
                top_k=10
            )
            for c in vec_chunks:
                chunks.append({
                    "content": c["content"][:900],
                    "source": c.get("source", "unknown"),
                    "record_id": c.get("record_id", "")[:8],
                    "score": c.get("similarity", 0.7)
                })
        except Exception as e:
            logger.warning(f"Vector retrieval failed: {e}")

        # === 3. DEDUPE & RANK ===
        seen = set()
        unique_chunks = []
        for chunk in sorted(chunks, key=lambda x: x.get("score", 0.5), reverse=True):
            key = (chunk.get("source"), chunk.get("record_id"), chunk["content"][:100])
            if key not in seen:
                continue
            seen.add(key)
            unique_chunks.append(chunk)
            if len(unique_chunks) >= 10:
                break

        logger.info(f"Retrieved {len(unique_chunks)} adaptive chunks")
        logger.info(f"Chunks retrieved: {unique_chunks}")
        return unique_chunks

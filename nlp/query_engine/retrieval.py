# nlp/query_engine/retrieval.py
"""
Adaptive retrieval powered by query analysis.
"""
from typing import List, Dict
from supabase import Client
from .analyzer import analyze_query
import logging

logger = logging.getLogger(__name__)

class AdaptiveRetriever:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def retrieve(self, question: str) -> List[Dict]:
        # 1. Deep understanding
        analysis = analyze_query(question)
        logger.info(f"Query analysis: {analysis}")

        chunks = []

        # 2. Graph search using entities + relations
        if analysis["entities"] or analysis["relations"]:
            for entity in analysis["entities"][:3]:
                try:
                    res = self.supabase.table("edges")\
                        .select("source_id:entities!source_id(name), target_id:entities!target_id(name), type, confidence")\
                        .or_(f"source_id:entities!source_id.name.ilike.%{entity}%,target_id:entities!target_id.name.ilike.%{entity}%")\
                        .in_("type", analysis["relations"] or ["OWNS", "FIXES", "MAINTAINS"])\
                        .limit(5).execute()
                    for row in res.data:
                        chunks.append({
                            "content": f"{row['source_id']['name']} {row['type']} {row['target_id']['name']} (confidence: {row['confidence']})",
                            "source": "graph",
                            "record_id": "graph-edge",
                            "score": row.get("confidence", 0.9)
                        })
                except Exception as e:
                    logger.warning(f"Graph search failed: {e}")

        # 3. Vector search on rewritten query
        try:
            from .vector.retriever import VectorRetriever
            vec = VectorRetriever(self.supabase)
            vec_chunks = vec.retrieve(analysis["rewritten"], top_k=10)
            chunks.extend(vec_chunks)
        except Exception as e:
            logger.warning(f"Vector failed: {e}")

        # 4. Dedupe + sort
        seen = set()
        unique = []
        for c in sorted(chunks, key=lambda x: x.get("score", 0.5), reverse=True):
            key = c.get("record_id", "") + c.get("content", "")[:50]
            if key not in seen:
                seen.add(key)
                unique.append(c)

        logger.info(f"Retrieved {len(unique)} adaptive chunks")
        return unique[:8]
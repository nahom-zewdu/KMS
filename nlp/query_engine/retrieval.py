# nlp/query_engine/retrieval.py
"""
Clean & Reliable Retrieval — Fixed for your current schema.
"""
from typing import List, Dict, Any
from supabase import Client
from .analyzer import analyze_query
from .vector.retriever import VectorRetriever
import logging
import re

logger = logging.getLogger(__name__)

class AdaptiveRetriever:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def _normalize_entity(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.strip())

    def _find_entity_candidates(self, question: str, limit: int = 6) -> List[str]:
        """Fallback entity candidates from the knowledge graph."""
        candidates: List[str] = []
        if not question:
            return candidates

        try:
            response = (
                self.supabase.table("entities")
                .select("name")
                .ilike("name", f"%{question}%")
                .limit(limit)
                .execute()
            )
            for row in response.data or []:
                candidates.append(row.get("name", ""))
        except Exception as e:
            logger.warning("Entity fallback search failed on full question: %s", e)

        if len(candidates) >= limit:
            return list(dict.fromkeys(candidates))

        tokens = [t for t in re.findall(r"\b[a-zA-Z0-9\-/\.]{4,}\b", question.lower())]
        for token in tokens[:6]:
            if len(candidates) >= limit:
                break
            try:
                response = (
                    self.supabase.table("entities")
                    .select("name")
                    .ilike("name", f"%{token}%")
                    .limit(3)
                    .execute()
                )
                for row in response.data or []:
                    candidates.append(row.get("name", ""))
            except Exception as e:
                logger.debug("Entity fallback token search failed for '%s': %s", token, e)

        return list(dict.fromkeys(self._normalize_entity(c) for c in candidates if c))

    def _search_edges_by_entity(self, entity: str, relation_types: Any) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        entity = self._normalize_entity(entity)
        if not entity:
            return chunks

        if isinstance(relation_types, str):
            relation_types = [relation_types]
        elif relation_types is None:
            relation_types = []

        # Prefer the Supabase RPC if available
        try:
            rpc_response = (
                self.supabase.rpc(
                    "search_edges_by_entity",
                    {
                        "search_term": entity,
                        "relation_types": relation_types
                    }
                )
                .execute()
            )
            for row in rpc_response.data or []:
                chunks.append({
                    "content": f"{row.get('source_name', 'Unknown')} {row.get('type', 'RELATED')} {row.get('target_name', 'Unknown')}",
                    "source": "graph",
                    "record_id": str(row.get("id", "graph")),
                    "score": row.get("confidence", 0.9)
                })
            if chunks:
                return chunks
        except Exception as e:
            logger.debug("Graph RPC fallback failed for '%s': %s", entity, e)

        # Manual fallback: resolve entity IDs and read edge rows
        try:
            entity_rows = (
                self.supabase.table("entities")
                .select("id,name")
                .ilike("name", f"%{entity}%")
                .limit(12)
                .execute()
            )
            entity_ids = [row["id"] for row in entity_rows.data or [] if row.get("id")]
            if not entity_ids:
                return chunks

            entity_map = {row["id"]: row.get("name", "Unknown") for row in entity_rows.data or []}
            edge_rows = (
                self.supabase.table("edges")
                .select("id,source_id,target_id,type,confidence")
                .in_("source_id", entity_ids)
                .limit(12)
                .execute()
            )
            edge_rows2 = (
                self.supabase.table("edges")
                .select("id,source_id,target_id,type,confidence")
                .in_("target_id", entity_ids)
                .limit(12)
                .execute()
            )

            all_edges = (edge_rows.data or []) + (edge_rows2.data or [])
            if all_edges:
                missing_ids = {r.get("source_id") for r in all_edges if r.get("source_id")} | {r.get("target_id") for r in all_edges if r.get("target_id")}
                missing_ids -= set(entity_map.keys())

                if missing_ids:
                    missing_rows = (
                        self.supabase.table("entities")
                        .select("id,name")
                        .in_("id", list(missing_ids))
                        .execute()
                    )
                    for row in missing_rows.data or []:
                        entity_map[row["id"]] = row.get("name", "Unknown")

                seen_edges = set()
                for row in all_edges:
                    src = entity_map.get(row.get("source_id"), "Unknown")
                    tgt = entity_map.get(row.get("target_id"), "Unknown")
                    rel = row.get("type", "RELATED")
                    conf = row.get("confidence", 0.9)
                    edge_key = (src, rel, tgt)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        chunks.append({
                            "content": f"{src} {rel} {tgt}",
                            "source": "graph",
                            "record_id": str(row.get("id", "graph")),
                            "score": conf
                        })
        except Exception as e:
            logger.warning("Manual graph search failed for '%s': %s", entity, e)

        return chunks

    def _entity_context_chunks(self, entities: List[str]) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        seen_names = set()
        for entity in entities[:6]:
            try:
                response = (
                    self.supabase.table("entities")
                    .select("name,type")
                    .ilike("name", f"%{entity}%")
                    .limit(4)
                    .execute()
                )
                for row in response.data or []:
                    name = row.get("name")
                    if not name or name in seen_names:
                        continue
                    seen_names.add(name)
                    entity_type = row.get("type", "entity").lower()
                    if entity_type in ["person", "system", "feature", "tech"]:
                        content = f"{name} is a {entity_type}."
                    else:
                        content = f"{name} is a {entity_type} entity."
                    chunks.append({
                        "content": content,
                        "source": "graph",
                        "record_id": f"entity:{name}",
                        "score": 0.75
                    })
            except Exception as e:
                logger.debug("Entity context lookup failed for '%s': %s", entity, e)
        return chunks

    def retrieve(self, question: str) -> List[Dict]:
        analysis = analyze_query(question)
        logger.info("------------------------------")
        logger.info(f"Query analysis: {analysis}")

        chunks: List[Dict] = []
        entities = analysis.get("entities") or []
        if not entities:
            entities = self._find_entity_candidates(question)
            logger.info("No analyzer entities found, fell back to entity search: %s", entities)

        if entities:
            chunks.extend(self._entity_context_chunks(entities))
            for entity in entities[:5]:
                chunks.extend(self._search_edges_by_entity(entity, analysis.get("relations", [])))

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

        # Dedupe + Rank
        seen = set()
        unique = []
        for c in sorted(chunks, key=lambda x: x.get("score", 0.5), reverse=True):
            key = c.get("content", "")[:120]
            if key not in seen:
                seen.add(key)
                unique.append(c)
                if len(unique) >= 12:
                    break

        logger.info(f"Retrieved {len(unique)} adaptive chunks")
        return unique

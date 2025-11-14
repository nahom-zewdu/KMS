# nlp/engine/re.py
"""
LLM-powered Relation Extraction with entity grounding.
"""

from typing import List, Dict
import json
import logging
from typing import List, Dict, Any
from functools import lru_cache
from .llm import llm_infer
from .prompt import get_relation_prompt

logger = logging.getLogger("engine.re")

VALID_REL_TYPES = {"OWNS", "MAINTAINS", "ASSIGNED_TO", "FIXES", "DEPLOYED_IN", "PART_OF"}

def _ensure_entity_list(entities: List[Any]) -> List[Dict[str, Any]]:
    """
    Ensure we have a list of dicts: [{'text':..., 'type':...}, ...]
    """
    normalized = []
    for e in entities:
        if hasattr(e, "dict"):
            d = e.dict()
        elif isinstance(e, dict):
            d = e
        else:
            # Skip unknown shapes
            continue
        # keep only relevant keys
        normalized.append({
            "text": d.get("text", "").strip().lower(),
            "type": d.get("type", "").upper()
        })
    return normalized

# cached wrapper expects hashable args -> we pass JSON string
def _cached_re(text: str, entities_json: str) -> str:
    """
    text: the input text
    entities_json: JSON string of normalized entity list (deterministic)
    """
    # Always deserialize string into list for the prompt
    try:
        entities_list = json.loads(entities_json)
    except TypeError:
        # if somehow a list is passed, convert it to string first
        entities_list = entities_json
        entities_json = json.dumps(entities_list, separators=(",", ":"), sort_keys=True)
    
    prompt = get_relation_prompt(text, entities_list)
    return llm_infer(prompt)

def extract_relations(text: str, entities: List[Any], record_id: str, created_at: str) -> List[Dict[str, Any]]:
    """
    Return list of relations ready for DB insertion:
    [{ "source": "...", "target": "...", "type": "...", "record_id": ..., "created_at": ... }, ...]
    """
    if not entities:
        return []

    normalized_entities = _ensure_entity_list(entities)
    if not normalized_entities:
        return []

    # deterministic serialization for cache
    entities_json = json.dumps(normalized_entities, separators=(",", ":"), sort_keys=True)

    try:
        raw = _cached_re(text, entities_json)
    except Exception as e:
        logger.error("RE LLM failed: %s", e)
        return []

    # parse expected JSON object: {"relations": [ ... ]}
    try:
        obj = json.loads(raw)
        raw_rel = obj.get("relations", [])
    except Exception:
        # fallback: try to extract array substring
        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            raw_rel = json.loads(raw[start:end]) if start != -1 and end > 0 else []
        except Exception:
            logger.warning("Failed to parse relations JSON; returning empty list.")
            raw_rel = []

    relations = []
    for r in raw_rel:
        try:
            src = (r.get("source") or "").strip().lower()
            tgt = (r.get("target") or "").strip().lower()
            typ = (r.get("type") or "").strip().upper()
            if not src or not tgt or typ not in VALID_REL_TYPES:
                logger.debug("Skipping invalid relation: %s", r)
                continue
            
            relations.append({
                "source": src,
                "target": tgt,
                "type": typ,
                "record_id": record_id or "",
                "created_at": created_at or ""
            })
        except Exception as e:
            logger.warning("Skipping bad relation entry %s -> %s", r, e)

    logger.info("RE → %d relations", len(relations))
    logger.info("Relations: %s", relations)
    return relations

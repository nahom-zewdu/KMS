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
VALID_RELATION_PAIRS = {
    "OWNS": {
        ("PERSON", "PROJECT"),
        ("PERSON", "SYSTEM"),
    },
    "MAINTAINS": {
        ("PERSON", "PROJECT"),
        ("PERSON", "SYSTEM"),
        ("PERSON", "FILE"),
    },
    "ASSIGNED_TO": {
        ("PERSON", "TICKET"),
    },
    "FIXES": {
        ("PERSON", "TICKET"),
    },
    "DEPLOYED_IN": {
        ("PROJECT", "ENVIRONMENT"),
        ("SYSTEM", "ENVIRONMENT"),
    },
    "PART_OF": {
        ("FILE", "PROJECT"),
        ("SYSTEM", "PROJECT"),
    },
}

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

def extract_relations(
    text,
    entities,
    record_id,
    created_at,
):
    if not entities:
        return []

    normalized_entities = _ensure_entity_list(entities)
    if not normalized_entities:
        return []

    try:
        prompt = get_relation_prompt(
            text,
            normalized_entities
        )

        raw = llm_infer(prompt)

    except Exception as e:
        logger.error("RE LLM failed: %s", e)
        return []

    try:
        raw = llm_infer(prompt)
        obj = json.loads(raw)
        raw_relations = obj.get(
            "relations",
            []
        )
    except Exception:
        return []

    relations = []

    seen = set()
    
    entity_map = {e["text"]: e["type"] for e in normalized_entities}
    valid_entities = set(entity_map.keys())

    for rel in raw_relations:

        src = (
            rel.get("source", "")
            .strip()
            .lower()
        )

        tgt = (
            rel.get("target", "")
            .strip()
            .lower()
        )

        rel_type = (
            rel.get("type", "")
            .strip()
            .upper()
        )

        if rel_type not in VALID_REL_TYPES:
            continue

        if src not in valid_entities:
            continue

        if tgt not in valid_entities:
            continue

        src_type = entity_map[src]
        tgt_type = entity_map[tgt]

        allowed_pairs = VALID_RELATION_PAIRS.get(
            rel_type,
            set(),
        )

        if (src_type, tgt_type,) not in allowed_pairs:
            continue

        key = (src, tgt, rel_type,)

        if key in seen:
            continue

        seen.add(key)

        relations.append({
            "source": src,
            "target": tgt,
            "type": rel_type,
            "created_at": created_at,
        })

    logger.info("RE → %d relations", len(relations),)

    return relations

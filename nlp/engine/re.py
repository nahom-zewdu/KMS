# nlp/engine/re.py
"""
LLM-powered Relation Extraction with entity grounding.
"""
# engine/re.py
from typing import List, Dict
import json
from functools import lru_cache
from .schema import Entity
from .llm import parse_json_response
from .llm import llm_infer
from .prompt import get_relation_prompt
import logging

@lru_cache(maxsize=500)
def extract_relations_cached(text: str, entities_json: str, record_id: str, created_at: str) -> List[Dict]:
    prompt = get_relation_prompt(text, json.loads(entities_json))
    response = llm_infer(prompt)
    return parse_json_response(response)

def extract_relations(text: str, entities: List[Entity], record_id: str, created_at: str):
    # Convert to JSON string for caching
    entities_json = json.dumps([e.dict() for e in entities], separators=(',', ':'))
    raw_relations = extract_relations_cached(text, entities_json, record_id, created_at)
    
    relations = []
    for rel in raw_relations:
        try:
            source = rel.get("source", "").lower()
            target = rel.get("target", "").lower()
            rel_type = rel.get("type", "UNKNOWN").upper()
            
            if rel_type not in ["OWNS", "MAINTAINS", "ASSIGNED_TO", "FIXES", "DEPLOYED_IN", "PART_OF"]:
                continue
                
            relations.append({
                "source": source,
                "target": target,
                "type": rel_type,
                "record_id": record_id,
                "created_at": created_at
            })
        except Exception as e:
            logging.warning(f"Invalid relation: {rel} → {e}")
    
    logging.info(f"RE → {len(relations)} relations")
    return relations

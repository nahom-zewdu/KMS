# nlp/engine/re.py
"""
LLM-powered Relation Extraction with entity grounding.
"""
from typing import List, Dict
from .prompt import get_relation_prompt
from .llm import llm_infer, parse_json_response
from .schema import Relation, Entity,
import logging

def extract_relations(
    text: str,
    entities: List[Entity],
    record_id: str,
    created_at: str
) -> List[Relation]:
    """
    Extract relations between entities using LLM.
    """
    if len(entities) < 2:
        return []
    
    prompt = get_relation_prompt(text, [e.dict() for e in entities])
    response = llm_infer(prompt)
    raw_relations = parse_json_response(response)
    
    relations = []
    entity_map = {e.text: e for e in entities}
    
    for rel in raw_relations:
        try:
            source = rel.get("source", "").strip().lower()
            target = rel.get("target", "").strip().lower()
            rel_type = rel.get("type", "UNKNOWN")
            
            if source not in entity_map or target not in entity_map:
                continue
                
            relation = Relation(
                source=source,
                target=target,
                type=rel_type,
                confidence=rel.get("score", 0.9),
                record_id=record_id,
                source_type=entity_map[source].type,
                target_type=entity_map[target].type,
                created_at=created_at
            )
            if relation.type != "UNKNOWN":
                relations.append(relation)
        except Exception as e:
            logging.warning(f"Invalid relation: {rel} → {e}")
    
    logging.info(f"RE → {len(relations)} relations")
    return relations

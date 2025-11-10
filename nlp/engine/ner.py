# nlp/engine/ner.py
"""
LLM-powered Named Entity Recognition with schema enforcement.
"""
from typing import List, Dict
from .prompt import get_entity_prompt
from .llm import llm_infer, parse_json_response
from .schema import Entity
import logging

def extract_entities(text: str, record_id: str, source: str, created_at: str) -> List[Entity]:
    """
    Extract entities using LLM with zero-shot prompting.
    
    Args:
        text: Raw input text
        record_id: Source record ID
        source: 'slack' or 'github'
        created_at: ISO timestamp
    
    Returns:
        List[Entity] with validated schema
    """
    if not text.strip():
        return []
    
    prompt = get_entity_prompt(text)
    response = llm_infer(prompt)
    
    # Fallback: if not JSON, try to extract
    if not response.startswith("["):
        logging.warning(f"LLM returned non-JSON: {response[:100]}")
        # Try to extract known patterns
        entities = []
        import re
        # Match KMS-123
        for m in re.finditer(r'\b[KMS]-\d+\b', text, re.I):
            entities.append(Entity(text=m.group(0).lower(), type="TICKET", confidence=0.99, record_id=record_id, source=source, created_at=created_at))
        # Match prod, dev, staging
        for m in re.finditer(r'\b(prod|dev|staging|test)\b', text, re.I):
            entities.append(Entity(text=m.group(0).lower(), type="ENVIRONMENT", confidence=0.95, record_id=record_id, source=source, created_at=created_at))
        return entities
    
    raw_entities = parse_json_response(response)
    entities = []
    for ent in raw_entities:
        try:
            entity = Entity(
                text=ent.get("text", "").strip().lower(),
                type=ent.get("type", "UNKNOWN"),
                confidence=ent.get("score", 0.95),
                record_id=record_id,
                source=source,
                created_at=created_at
            )
            if entity.type != "UNKNOWN" and len(entity.text) > 1:
                entities.append(entity)
        except Exception as e:
            logging.warning(f"Invalid entity: {ent} → {e}")
    
    logging.info(f"NER → {len(entities)} entities")
    return entities

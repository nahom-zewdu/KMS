# nlp/engine/ner.py
"""
LLM-powered Named Entity Recognition with schema enforcement.
"""

from typing import List
import json
import logging
from .llm import llm_infer
from .prompt import get_entity_prompt
from .schema import Entity

logger = logging.getLogger("engine.ner")

ALLOWED_TYPES = {"PERSON", "SYSTEM", "TICKET", "PROJECT", "ENVIRONMENT"}

FORBIDDEN_TYPES = {"FILE"}

def extract_entities(
    text: str,
    record_id: str,
    source: str,
    created_at: str,
) -> List[Entity]:
    """
    Extract entities using LLM.
    NOTE: FILE entities are intentionally excluded and handled by CodebaseAnalyzer.
    """

    if not text.strip():
        return []

    prompt = get_entity_prompt(text)

    try:
        raw = llm_infer(prompt)
        obj = json.loads(raw)
        ents = obj.get("entities", [])
    except Exception as e:
        logger.error("NER failed: %s", e)
        return []

    seen = set()
    results = []

    lower_text = text.lower()

    for ent in ents:
        try:
            entity_text = ent.get("text", "").strip().lower()
            entity_type = ent.get("type", "").strip().upper()

            if entity_type in FORBIDDEN_TYPES:
                continue

            if entity_type not in ALLOWED_TYPES:
                continue

            if not entity_text:
                continue

            if entity_text not in lower_text:
                continue

            key = (entity_text, entity_type)
            if key in seen:
                continue

            seen.add(key)

            results.append(
                Entity(
                    text=entity_text,
                    type=entity_type,
                    confidence=0.95,
                    record_id=record_id,
                    source=source,
                    created_at=created_at,
                )
            )

        except Exception:
            continue

    logger.info("NER → %d entities", len(results))
    return results

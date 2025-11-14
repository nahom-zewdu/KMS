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
from datetime import datetime, timezone
import uuid

logger = logging.getLogger("engine.ner")

ALLOWED_TYPES = {"PERSON", "SYSTEM", "TICKET", "PROJECT", "ENVIRONMENT", "FILE"}

def _normalize_text(s: str) -> str:
    return s.strip().lower()

def extract_entities(text: str, record_id: str, source: str, created_at: str) -> List[Entity]:
    """
    Extract entities from text using LLM. Return validated List[Entity].
    created_at should be ISO string; if missing, we fallback to now().
    """
    if not text or not text.strip():
        return []

    if not created_at:
        created_at = datetime.now(timezone.utc).isoformat()

    prompt = get_entity_prompt(text)
    try:
        raw = llm_infer(prompt)
    except Exception as e:
        logger.error("LLM call failed for NER: %s", e)
        return []

    # Expect JSON object: {"entities": [ ... ]}
    try:
        obj = json.loads(raw)
        ents = obj.get("entities", [])
    except Exception:
        # Best-effort fallback: try to find a JSON array, else empty.
        logger.warning("NER LLM did not return JSON object, trying to parse array fallback.")
        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start != -1 and end > 0:
                ents = json.loads(raw[start:end])
            else:
                logger.warning("NER fallback failed; returning empty list.")
                return []
        except Exception:
            logger.exception("NER fallback parse failed.")
            return []

    results: List[Entity] = []
    for ent in ents:
        try:
            text_span = ent.get("text", "")
            typ = (ent.get("type") or "").strip().upper()
            # Basic validation
            if not text_span or typ not in ALLOWED_TYPES:
                logger.debug("Skipping invalid entity: %s", ent)
                continue
            norm_text = _normalize_text(text_span)
            # Build Entity model (pydantic)
            e = Entity(
                text=norm_text,
                type=typ,
                confidence=float(ent.get("score", 0.95)),
                record_id=record_id or "",
                source=source or "",
                created_at=created_at
            )
            results.append(e)
        except Exception as e:
            logger.warning("Invalid entity entry skipped: %s -> %s", ent, e)

    logger.info("NER → %d entities", len(results))
    logger.info("Entities: %s", [e.dict() for e in results])
    return results

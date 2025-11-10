# nlp/engine/prompt.py
"""
Prompt templates with caching and schema enforcement.
"""
from functools import lru_cache
from typing import List, Dict


ENTITY_PROMPT = """You are a JSON-only API. Extract ALL entities from the text.

Text: "{text}"

Return ONLY a valid JSON array. No explanations.

Schema:
[
  {{"text": "exact span lowercase", "type": "PERSON|SYSTEM|TICKET|PROJECT|ENVIRONMENT"}}
]

Examples:
- "jhon owns auth" → [{{"text": "jhon", "type": "PERSON"}}, {{"text": "auth", "type": "SYSTEM"}}]
- "fix KMS-123 in prod" → [{{"text": "kms-123", "type": "TICKET"}}, {{"text": "prod", "type": "ENVIRONMENT"}}]

JSON only. No markdown.
"""

RELATION_PROMPT = """Given entities and text, extract ALL relations.

Entities: {entities}
Text: "{text}"

Return JSON array of:
- "source": entity text
- "target": entity text
- "type": one of {OWNS, MAINTAINS, ASSIGNED_TO, FIXES, DEPLOYED_IN, PART_OF}

Examples:
- "jhon owns auth" → [{{"source": "jhon", "target": "auth", "type": "OWNS"}}]
- "KMS-123 is in prod" → [{{"source": "kms-123", "target": "prod", "type": "DEPLOYED_IN"}}]

JSON only.
"""

@lru_cache(maxsize=1000)
def get_entity_prompt(text: str) -> str:
    return ENTITY_PROMPT.format(text=text.strip())

@lru_cache(maxsize=1000)
def get_relation_prompt(text: str, entities: List[Dict]) -> str:
    entity_str = ", ".join([f"{e['text']} ({e['type']})" for e in entities])
    return RELATION_PROMPT.format(entities=entity_str, text=text.strip())

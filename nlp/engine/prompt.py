# nlp/engine/prompt.py
"""
Prompt templates with caching and schema enforcement.
"""
from functools import lru_cache
from typing import List, Dict

ENTITY_PROMPT = """
You are a deterministic JSON API. Extract ALL entities explicitly mentioned in the text.

Input text:
"{text}"

Return ONLY a JSON object with this exact schema:

{
  "entities": [
    {
      "text": "<exact lowercase span from input>",
      "type": "PERSON | SYSTEM | TICKET | PROJECT | ENVIRONMENT | FILE"
    }
  ]
}

Strict rules:
- Output must be valid JSON. No comments, no markdown, no explanation.
- "text" MUST be the exact substring from the input, converted to lowercase.
- Never generate entities that are not explicitly present in the text.
- Never infer or guess types beyond the allowed set.
- If no entities are present, return: { "entities": [] }
- Order entities by appearance in the text.

Valid examples:

Input: "jhon owns auth"
Output: {
  "entities": [
    {"text": "jhon", "type": "PERSON"},
    {"text": "auth", "type": "SYSTEM"}
  ]
}

Input: "fix KMS-123 in prod"
Output: {
  "entities": [
    {"text": "kms-123", "type": "TICKET"},
    {"text": "prod", "type": "ENVIRONMENT"}
  ]
}

Input: "modified config/auth.yaml"
Output: {
  "entities": [
    {"text": "config/auth.yaml", "type": "FILE"}
  ]
}
"""


ENTITY_PROMPT = """
You are a deterministic JSON API. Extract ALL entities explicitly mentioned in the text.

Input text:
"{text}"

Return ONLY a JSON object with this exact schema:

{
  "entities": [
    {
      "text": "<exact lowercase span from input>",
      "type": "PERSON | SYSTEM | TICKET | PROJECT | ENVIRONMENT | FILE"
    }
  ]
}

Strict rules:
- Output must be valid JSON. No comments, no markdown, no explanation.
- "text" MUST be the exact substring from the input, converted to lowercase.
- Never generate entities that are not explicitly present in the text.
- Never infer or guess types beyond the allowed set.
- If no entities are present, return: { "entities": [] }
- Order entities by appearance in the text.

Valid examples:

Input: "jhon owns auth"
Output: {
  "entities": [
    {"text": "jhon", "type": "PERSON"},
    {"text": "auth", "type": "SYSTEM"}
  ]
}

Input: "fix KMS-123 in prod"
Output: {
  "entities": [
    {"text": "kms-123", "type": "TICKET"},
    {"text": "prod", "type": "ENVIRONMENT"}
  ]
}

Input: "modified config/auth.yaml"
Output: {
  "entities": [
    {"text": "config/auth.yaml", "type": "FILE"}
  ]
}
"""


@lru_cache(maxsize=1000)
def get_entity_prompt(text: str) -> str:
    return ENTITY_PROMPT.format(text=text.strip())

@lru_cache(maxsize=1000)
def get_relation_prompt(text: str, entities: List[Dict]) -> str:
    entity_str = ", ".join([f"{e['text']} ({e['type']})" for e in entities])
    return RELATION_PROMPT.format(entities=entity_str, text=text.strip())

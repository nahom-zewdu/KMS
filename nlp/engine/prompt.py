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


RELATION_PROMPT = """
You are a deterministic JSON API. Identify ALL relations between the provided entities as they appear in the text.

Entities (JSON list):
{entities}

Input text:
"{text}"

Return ONLY a JSON object with this exact schema:

{
  "relations": [
    {
      "source": "<entity.text>",
      "target": "<entity.text>",
      "type": "OWNS | MAINTAINS | ASSIGNED_TO | FIXES | DEPLOYED_IN | PART_OF"
    }
  ]
}

Strict rules:
- Output must be valid JSON — no explanations, no markdown, no extra fields.
- Use ONLY the entities provided. Never invent new entities.
- source and target MUST match an entity.text value exactly.
- A relation MUST be explicitly implied by the text — no guessing.
- If no relations exist, return: { "relations": [] }
- Order relations by where their source entity appears in the text.

Valid examples:

Input:
Entities: [{"text": "jhon", "type": "PERSON"}, {"text": "auth", "type": "SYSTEM"}]
Text: "jhon owns auth"

Output:
{
  "relations": [
    {"source": "jhon", "target": "auth", "type": "OWNS"}
  ]
}

Input:
Entities: [{"text": "kms-123", "type": "TICKET"}, {"text": "prod", "type": "ENVIRONMENT"}]
Text: "KMS-123 is in prod"

Output:
{
  "relations": [
    {"source": "kms-123", "target": "prod", "type": "DEPLOYED_IN"}
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

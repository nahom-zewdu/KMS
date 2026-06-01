# nlp/engine/prompt.py
"""
Prompt templates with caching and schema enforcement.
"""

from functools import lru_cache
import json
from typing import List, Dict
from string import Template

ENTITY_PROMPT = Template("""
You are a deterministic JSON API. Extract ALL explicit entities in the text.
Your response MUST begin with "{" as the first character.

Input text:
"$text"

Return ONLY a JSON object with this schema:

{
  "entities": [
    {
      "text": "<exact lowercase span from input>",
      "type": "PERSON | SYSTEM | TICKET | PROJECT | ENVIRONMENT | FILE"
    }
  ]
}

Strict rules:
- You must only use entity.text values from the list provided. Do NOT create new or combined names. Every source and target must exactly match one of the entities
- Output must be valid JSON. No explanations or markdown.
- "text" MUST be an exact substring from the input, converted to lowercase.
- Do NOT infer or hallucinate entities not present.
- Do NOT create custom types. Only the allowed set.
- If no entities exist: { "entities": [] }
- Maintain the original order of appearance.

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
""".strip())

RELATION_PROMPT = Template("""
You are a deterministic JSON API. Identify ALL explicit relations between the provided entities.
Your response MUST begin with "{" as the first character.

Entities (JSON list):
$entities

Input text:
"$text"

Return ONLY a JSON object with this schema:

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
- Only output valid JSON. No markdown. No explanations.
- Use ONLY entities provided in the list.
- Do NOT invent new entities.
- "source" and "target" MUST exactly match entity.text.
- Relations must be explicitly implied by the input text.
- If no relations exist: { "relations": [] }
- Order relations by the source entity's first appearance in the text.

Valid examples:

Entities: [{"text": "jhon", "type": "PERSON"}, {"text": "auth", "type": "SYSTEM"}]
Text: "jhon owns auth"

Output:
{
  "relations": [
    {"source": "jhon", "target": "auth", "type": "OWNS"}
  ]
}

Entities: [{"text": "kms-123", "type": "TICKET"}, {"text": "prod", "type": "ENVIRONMENT"}]
Text: "KMS-123 is in prod"

Output:
{
  "relations": [
    {"source": "kms-123", "target": "prod", "type": "DEPLOYED_IN"}
  ]
}
""".strip())


@lru_cache(maxsize=1000)
def get_entity_prompt(text: str) -> str:
    return ENTITY_PROMPT.substitute(text=text.strip())


def get_relation_prompt(text: str, entities: List[Dict]) -> str:
    entities_repr = json.dumps(entities, separators=(",", ":"))

    return RELATION_PROMPT.substitute(
        text=text.strip(),
        entities=entities_repr
    )

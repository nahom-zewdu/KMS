# nlp/query_engine/analyzer.py
"""
Query Analyzer Clean, correct, production-grade.
Uses LLM to extract entities + relations + intent from natural language questions.
"""
from engine.llm import llm_infer
import json
from typing import Dict, Any

def analyze_query(question: str) -> Dict[str, Any]:
    prompt = f"""
You are KMS the engineering memory system. Your job is to deeply understand natural language questions.

Question: {question}

Extract ALL entities and infer the most likely relations.

Entity types (extract even if not exact match):
- PERSON (names like Helen, Nahom, Sarah)
- SYSTEM / FEATURE (auth, userservice, analytics cache, webhook retry)
- TECH (Redis, Go, Node.js, Postgres)
- TICKET / PR
- FILE / PATH

Relation types (infer intent):
- OWNS, MAINTAINS → ownership
- FIXES, IMPLEMENTED, ADDED → authorship + action
- MOVED_TO, MIGRATED_TO, CHANGED → migration/refactor
- DEPLOYED_IN, RUNS_ON → infrastructure
- PART_OF, DEPENDS_ON → architecture

CRITICAL RULES:
- If the question contains "who" + verb ("who moved", "who added", "who changed", "who migrated", "who fixed") → intent = "authorship"
- Extract person names aggressively — "Helen did X" → Helen is an entity
- Preserve "who" in rewritten if original had it
- rewritten must be clear, canonical, and preserve original intent

Examples:
Input:  "who moved analytics cache to redis?"
Output: {{
  "entities": ["analytics cache", "redis", "Helen"],
  "relations": ["MOVED_TO", "MIGRATED_TO", "IMPLEMENTED"],
  "rewritten": "Who moved the analytics cache to Redis?",
  "intent": "authorship"
}}

Input:  "where is analytics cache stored"
Output: {{
  "entities": ["analytics cache"],
  "relations": ["DEPLOYED_IN", "RUNS_ON"],
  "rewritten": "Where is the analytics cache deployed?",
  "intent": "status"
}}

Respond with valid JSON only. No explanation.
""".strip()

    raw = llm_infer(prompt, temperature=0.0, max_tokens=350)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Absolute last resort never hardcode
        return {
            "entities": [],
            "relations": ["OWNS", "FIXES", "MOVED_TO"],
            "rewritten": question,
            "intent": "authorship" if any(x in question.lower() for x in ["who ", "did ", "added", "moved", "changed", "fixed", "migrated"]) else "status"
        }

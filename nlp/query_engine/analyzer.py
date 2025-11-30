# nlp/query_engine/analyzer.py
"""
Query Analyzer the single most important component.
Uses LLM once to deeply understand the question.
"""
from engine.llm import llm_infer
from typing import List, Dict, TypedDict
import json

class QueryAnalysis(TypedDict):
    entities: List[str]
    relations: List[str]
    rewritten: str
    intent: str  # "ownership", "history", "debugging", "status", "who_to_ping"

def analyze_query(question: str) -> QueryAnalysis:
    """
    One LLM call → full understanding of the query.
    """
    prompt = f"""
You are KMS, the engineering knowledge system for startup/fintech/saas companies.

Analyze this user question and extract structured intent.

Question: {question}

Entity types: PERSON, SYSTEM, TICKET, PROJECT, ENVIRONMENT, FILE
Relation types: OWNS, MAINTAINS, ASSIGNED_TO, FIXES, DEPLOYED_IN, PART_OF

Respond in valid JSON with this exact structure:
{{
  "entities": ["auth", "Nahom", "retry bug", "webhook"],
  "relations": ["OWNS", "FIXES", "PART_OF"],
  "rewritten": "Who is responsible for the authentication system?",
  "intent": "ownership" | "history" | "debugging" | "status" | "who_to_ping" | "timeline"
}}

Rules:
- Extract ALL mentioned or implied entities
- Infer the most likely relations
- Rewrite the question clearly and canonically
- If unsure about intent, use "status"

Respond only with JSON:
""".strip()

    raw = llm_infer(prompt, temperature=0.0, max_tokens=300)
    
    try:
        return json.loads(raw)
    except:
        # Fallback
        return {
            "entities": [],
            "relations": [],
            "rewritten": question,
            "intent": "status"
        }
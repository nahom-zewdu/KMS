# nlp/query_engine/synthesizer.py
"""
Final answer synthesis returns clean JSON.
Never crashes. Always valid.
"""
from engine.llm import llm_infer
from typing import List, Dict

def synthesize(
    question: str,
    graph_facts: List[Dict],
    vector_context: List[Dict],
    priority: str
) -> str:
    """
    Returns valid JSON: {"answer": "...", "sources": [...]}
    Safe for parsing. Never hallucinates.
    """
    # Build context
    context_blocks = []

    if graph_facts:
        context_blocks.append("=== STRUCTURED FACTS (HIGH CONFIDENCE) ===")
        for f in graph_facts[:3]:
            context_blocks.append(f"- {f['content']} (from {f['source']})")

    if vector_context:
        context_blocks.append("=== RELEVANT CONTEXT ===")
        for c in vector_context[:5]:
            context_blocks.append(f"- {c['content']} (from {c['source']})")

    context = "\n".join(context_blocks) if context_blocks else "No context found."

    priority_hint = {
        "graph_first": "Prioritize names, ownership, and responsibility.",
        "vector_first": "Focus on timeline, reasons, and changes.",
        "balanced": "Use both structured and historical data."
    }[priority]

    prompt = f"""
You are KMS, the engineering memory system.
Answer using ONLY the context below. Never make up facts.

{priority_hint}

Context:
{context}

Question: {question}

Respond with valid JSON using this exact structure:
{{
  "answer": "Your natural language answer in 1-3 sentences.",
  "sources": ["slack:abc123", "github:def456"]
}}

Include real sources from context. Use short record_id (8 chars).
If unsure, set "answer" to "I don't know yet." and "sources" to [].

Respond with JSON only:""".strip()

    raw_json = llm_infer(prompt, temperature=0.1, max_tokens=300)

    # Final safety net
    if not raw_json or "{" not in raw_json:
        return '{"answer": "I couldn\'t generate a clear answer.", "sources": []}'

    return raw_json
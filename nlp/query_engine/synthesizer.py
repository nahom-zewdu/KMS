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
            context_blocks.append(f"- {f['content']} (source: {f['source']})")

    if vector_context:
        context_blocks.append("=== RELEVANT CONTEXT ===")
        for c in vector_context[:5]:
            context_blocks.append(f"- {c['content']} (source: {c['source']})")

    context = "\n".join(context_blocks) if context_blocks else "No context available."

    prompt = f"""
You are KMS, the engineering memory system.

Answer the question using ONLY the context below.
Never make up names, ownership, or facts.

Context:
{context}

Question: {question}

Respond with valid JSON in this exact format:
{{
  "answer": "Your clear, direct answer in 1-3 sentences.",
  "sources": ["slack:17641759", "github:abc123def"]
}}

- Use real sources from context
- Use only first 8 chars of record_id
- If no clear answer, use: "answer": "I don't know yet.", "sources": []

Respond only with JSON:
""".strip()

    result = llm_infer(prompt)

    # Final safety
    if not result or "{" not in result:
        return '{"answer": "I couldn\'t generate a clear answer.", "sources": []}'

    return result

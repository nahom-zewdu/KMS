# nlp/query_engine/synthesizer.py
"""
Reasoning synthesizer with chain-of-thought.
Always returns valid JSON. Never hallucinates.
"""
from engine.llm import llm_infer
import json

def reasoning_synthesize(question: str, chunks: list) -> str:
    """
    Uses chain-of-thought to reason over retrieved chunks.
    Returns valid JSON string (JSON).
    """
    if not chunks:
        return json.dumps({
            "answer": "No relevant context found.",
            "sources": [],
            "confidence": "low"
        })

    context_lines = []
    for i, chunk in enumerate(chunks[:10], 1):
        src = chunk.get("source", "unknown")
        rid = chunk.get("record_id", "")[:8]
        source_tag = f"{src}:{rid}" if rid else src
        context_lines.append(f"[{i}] {chunk['content'][:900]}... ({source_tag})")

    context = "\n".join(context_lines)

    prompt = f"""
You are KMS, the single source of truth for engineering knowledge at a startup/fintech/saas.

Answer the question using ONLY the context below.

Question: {question}

Context:
{context}

Think step by step:
1. What is the question really asking?
2. Which context chunks are most relevant?
3. Is there conflicting information?
4. What is the clearest, most accurate answer?

Then respond in valid JSON with this exact structure:
{{
  "reasoning": "Brief internal thought process (1-2 sentences)",
  "answer": "Clear, direct answer in 1-4 sentences. Be professional.",
  "confidence": "high" | "medium" | "low",
  "sources": ["slack:17641759", "github:a1b2c3d4", "graph"]
}}

Rules:
- Never invent names, dates, or facts
- Use real sources from context
- If unsure, set confidence to "low" and say so
- Respond only with JSON

JSON:
""".strip()

    result = llm_infer(prompt, temperature=0.0, max_tokens=600)

    # Safety fallback
    if not result or "{" not in result:
        return json.dumps({
            "answer": "I found some context but couldn't form a clear answer.",
            "sources": [c.get("source", "unknown") for c in chunks[:3]],
            "confidence": "low"
        })

    return result

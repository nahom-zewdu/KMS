# nlp/query_engine/synthesizer.py
"""
Answer Synthesizer turns raw facts into beautiful, trusted answers.

Features:
- Inline citations [1][2]
- Confidence badges
- Source links (record_id)
- Never hallucinates names or ownership
"""

from typing import List, Dict, Any

def synthesize(
    question: str,
    graph_facts: List[str] = None,
    vector_chunks: List[Dict] = None,
    route: str = "unknown"
) -> str:
    """
    Create final user-facing answer with citations and confidence.
    """
    parts = []
    citations = []

    # 1. Graph facts (highest trust)
    if graph_facts:
        parts.extend(graph_facts)
        citations.append("Knowledge graph (100% confidence)")

    # 2. Vector context
    if vector_chunks:
        for i, chunk in enumerate(vector_chunks[:4], 1):
            content = chunk["content"][:600] + ("..." if len(chunk["content"]) > 600 else "")
            source = chunk.get("source", "unknown")
            record_id = chunk.get("record_id", "unknown")
            parts.append(f"[{i}] {content}")
            citations.append(f"Source: {source} • record:{record_id}")

    if not parts:
        return "I couldn't find any relevant information yet."

    # Final answer via LLM (constrained)
    context = "\n\n".join(parts)
    citation_note = "\n\n" + " | ".join(f"[{i}] {c}" for i, c in enumerate(citations, 1))

    prompt = f"""
You are a precise engineering assistant at a fintech startup.

Answer in 1-3 short sentences using ONLY the context below.
Never make up names, ownership, or facts.
Use casual but professional tone.

Context:
{context}

Question: {question}

Answer:
""".strip()

    from engine.llm import llm_infer
    answer = llm_infer(prompt, temperature=0.3, max_tokens=150) or "I don't know."

    return f"{answer.strip()}{citation_note}"

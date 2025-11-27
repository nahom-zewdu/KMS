# nlp/query_engine/synthesizer.py
"""
Final answer synthesis using LLM.
Receives BOTH graph hints and vector context.
Never hallucinates names or ownership it only reads.
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
    Generate final answer using constrained LLM.
    Always cites sources. Never makes up facts.
    """
    # Build context
    context_blocks = []

    if graph_facts:
        context_blocks.append("=== OWNERSHIP & STRUCTURED FACTS (HIGH CONFIDENCE) ===")
        for f in graph_facts[:3]:
            context_blocks.append(f"• {f['content']} (from {f['source']})")

    if vector_context:
        context_blocks.append("\n=== RELEVANT HISTORY & CONTEXT ===")
        for c in vector_context[:4]:
            context_blocks.append(f"• {c['content']} (from {c['source']})")

    context = "\n".join(context_blocks) if context_blocks else "No prior context found."

    priority_hint = {
        "graph_first": "Prioritize ownership, names, and responsibility.",
        "vector_first": "Focus on timeline, reasons, and context.",
        "balanced": "Use both structured and historical context."
    }[priority]

    prompt = f"""
You are KMS, the engineering memory system.
Answer the question using ONLY the context below.
Never guess names, ownership, or facts.
If unsure, say "I don't know yet" or "Not enough context".

{priority_hint}

Context:
{context}

Question: {question}

Answer in 1-3 short sentences. End with sources if available.
Answer:
""".strip()

    answer = llm_infer(prompt)

    if not answer or "I don't know" in answer.lower():
        return "I couldn't find clear information on that yet."

    # Add citations
    sources = set()
    for item in (graph_facts + vector_context):
        src = item.get("source")
        rid = item.get("record_id")
        if src and rid:
            sources.add(f"{src}:{rid[:8]}")

    citation = "\n\nSources: " + ", ".join(sorted(sources)) if sources else ""
    return answer.strip() + citation

# nlp/query_engine/synthesizer.py
"""
Reasoning synthesizer — company evidence only.
Returns JSON string matching the answer contract.
"""

from typing import List, Dict, Optional
from engine.llm import llm_infer


def reasoning_synthesize(
    question: str,
    chunks: List[Dict],
    allowed_owners: Optional[List[str]] = None,) -> str:
    """
    Synthesize a reasoning answer from relevant chunks.
    Returns a JSON string matching the answer contract.
    """
    context_lines = []
    for i, c in enumerate(chunks[:10], 1):
        src = c.get("source", "raw")
        rid = c.get("record_id", "")
        context_lines.append(
            f"[{i}] ({src} record_id={rid}) {c.get('content', '')[:500]}"
        )
    context = "\n".join(context_lines)
    owners_rule = (
        f"Owners may ONLY be chosen from this list: {allowed_owners}. "
        if allowed_owners
        else "Do not invent person names. If no owner in context, owners must be []. "
    )

    prompt = f"""
        You are KMS, the engineering memory system for one company.

        Answer using ONLY the context below. Never invent people, ownership, or systems.

        {owners_rule}
        If context is insufficient, set confidence to "low" and abstain_reason to "no_relevant_evidence".

        Context:
        {context}

        Question: {question}

        Respond with valid JSON only:
        {{
        "answer": "1-3 sentences, factual",
        "confidence": "high|medium|low",
        "sources": [{{"source": "graph|raw|slack|github", "record_id": "..."}}],
        "owners": [],
        "abstain_reason": null
        }}
        """.strip()

    return llm_infer(prompt, temperature=0.0, max_tokens=400) or ""

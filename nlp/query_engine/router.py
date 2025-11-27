# nlp/query_engine/router.py
"""
Minimal, deterministic intent router.
No LLM. No failure. 100% uptime.
Only purpose: decide if we should prioritize graph or vector.
"""
from typing import Literal

PathPriority = Literal["graph_first", "vector_first", "balanced"]

def classify_intent(question: str) -> PathPriority:
    """
    Classify question to bias retrieval order.
    Never fails. Always returns a valid path.
    """
    q = question.lower()

    # High-precision ownership/responsibility signals
    if any(phrase in q for phrase in [
        "who owns", "owner of", "owns ", "responsible for", "maintains ",
        "in charge of", "point of contact", "poc for", "who handles"
    ]):
        return "graph_first"

    # Historical/contextual signals
    if any(phrase in q for phrase in [
        "why ", "what happened", "when did", "how did", "what changed",
        "context on", "background", "what broke", "incident"
    ]):
        return "vector_first"

    # Default: balanced (most questions)
    return "balanced"
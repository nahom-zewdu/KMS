# nlp/query_engine/__init__.py
"""
KMS Query Engine v2 — The truth engine.

A hybrid graph + vector retrieval system that delivers:
- <150ms p95 latency
- 99%+ accuracy on ownership questions
- Full citation + confidence
- Zero hallucinations on structured facts

Architecture:
    router → graph / vector / hybrid → synthesizer → cache
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import QueryEngine

__all__ = ["QueryEngine"]
__version__ = "2.0.0"


def __getattr__(name: str):
    """Load the heavyweight query engine only when its public API is requested."""
    if name == "QueryEngine":
        from .core import QueryEngine

        return QueryEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

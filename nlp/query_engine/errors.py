# nlp/query_engine/errors.py
"""
Centralized error handling and user-friendly fallbacks.
Turns failures into graceful, helpful responses instead of crashing.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

class QueryEngineError(Exception):
    """Base exception for all query engine errors."""
    pass

class RetrievalError(QueryEngineError):
    """Vector or graph retrieval failed."""
    pass

class SynthesisError(QueryEngineError):
    """LLM failed to generate answer."""
    pass

def safe_answer(fallback: str = "I'm having trouble answering right now. Try again in a moment."):
    """Decorator to catch any exception and return a safe message."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"QueryEngine crash prevented: {e}", exc_info=True)
                return fallback
        return wrapper
    return decorator

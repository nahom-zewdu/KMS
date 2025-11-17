# utils/common.py
"""
Shared utilities: error logging, timing, validation.
"""
import logging
import time
from functools import wraps
from typing import Callable, Any

def log_error(message: str):
    """Log error with structured fields."""
    logging.error(message, extra={"error": True})

def timed(func: Callable) -> Callable:
    """Decorator to log function execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start
        logging.info(f"{func.__name__} completed in {duration:.3f}s")
        return result
    return wrapper

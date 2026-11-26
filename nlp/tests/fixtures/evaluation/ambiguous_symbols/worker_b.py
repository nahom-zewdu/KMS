"""Synthetic worker implementation B."""

def process_task(task: dict) -> bool:
    """Process a task using the fallback queue."""
    return bool(task)

"""Synthetic worker implementation A."""

def process_task(task: dict) -> str:
    """Process a task using the primary queue."""
    return str(task.get("id", ""))

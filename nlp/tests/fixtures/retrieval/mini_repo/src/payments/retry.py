"""Retry policy used by payment orchestration."""


class RetryPolicy:
    """Decides whether a failed payment attempt may be retried."""

    def should_retry(self, attempt: int) -> bool:
        """Allow one retry after the first attempt."""
        return attempt < 2

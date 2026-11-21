"""Minimal ledger persistence boundary."""


class Ledger:
    """Records successful payment activity."""

    def record_payment(self, account_id: str, amount: int) -> None:
        """Persist a successful payment entry."""
        self._insert(account_id, amount)

    def _insert(self, account_id: str, amount: int) -> None:
        """Stand in for the database insert."""
        return None

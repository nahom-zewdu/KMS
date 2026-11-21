"""Payment orchestration for the retrieval benchmark."""

from payments.retry import RetryPolicy
from storage.ledger import Ledger


class PaymentService:
    """Coordinates payment attempts, retry decisions, and ledger writes."""

    def __init__(self, retry_policy: RetryPolicy, ledger: Ledger) -> None:
        self.retry_policy = retry_policy
        self.ledger = ledger

    def charge(self, account_id: str, amount: int) -> str:
        """Attempt a charge and record successful payments."""
        result = self._send_charge(account_id, amount)
        if result == "temporary_error" and self.retry_policy.should_retry(1):
            result = self._send_charge(account_id, amount)
        if result == "success":
            self.ledger.record_payment(account_id, amount)
        return result

    def _send_charge(self, account_id: str, amount: int) -> str:
        """Represent the external payment boundary in this small fixture."""
        return "success"

"""Payment authorization, capture, and refund operations."""

def authorize_payment(account_id: str, amount: int) -> str:
    """Authorize a positive payment amount."""
    if amount <= 0:
        return "invalid_amount"
    return f"authorized:{account_id}"

def capture_payment(authorization: str) -> bool:
    """Capture a previously authorized payment."""
    return authorization.startswith("authorized:")

def refund_payment(transaction_id: str, amount: int) -> bool:
    """Validate a refund request."""
    if amount <= 0:
        return False
    return bool(transaction_id)

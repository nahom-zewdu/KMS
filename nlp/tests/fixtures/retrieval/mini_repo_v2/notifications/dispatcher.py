"""Notification dispatch orchestration."""

from notifications.email import send_receipt, send_refund_notice

def dispatch_receipt(mailer, order_id: str, total: int) -> bool:
    """Dispatch a receipt after purchase completion."""
    return send_receipt(mailer, order_id, total)

def dispatch_refund(mailer, order_id: str) -> bool:
    """Dispatch a refund confirmation."""
    return send_refund_notice(mailer, order_id)

"""Email rendering and delivery helpers."""

def render_receipt(order_id: str, total: int) -> str:
    """Render a plain-text purchase receipt."""
    return f"Order {order_id}: total {total}"

def send_receipt(mailer, order_id: str, total: int) -> bool:
    """Send a purchase receipt email."""
    message = render_receipt(order_id, total)
    return mailer.send(message)

def send_refund_notice(mailer, order_id: str) -> bool:
    """Send a refund confirmation email."""
    message = f"Refund processed for {order_id}"
    return mailer.send(message)

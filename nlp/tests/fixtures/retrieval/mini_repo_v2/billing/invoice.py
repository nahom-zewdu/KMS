"""Invoice calculation and construction."""

def calculate_subtotal(items: list[dict]) -> int:
    """Sum item prices before tax."""
    return sum(item["price"] * item["quantity"] for item in items)

def calculate_tax(subtotal: int, rate: float) -> int:
    """Calculate tax for an invoice subtotal."""
    tax_amount = subtotal * rate
    return round(tax_amount)

def build_invoice(order: dict, tax_rate: float) -> dict:
    """Build an invoice from an order."""
    subtotal = calculate_subtotal(order["items"])
    tax = calculate_tax(subtotal, tax_rate)
    return {"subtotal": subtotal, "tax": tax, "total": subtotal + tax}

"""Order persistence boundary."""

class OrderStore:
    """Stores and updates order records."""

    def get_order(self, order_id: str) -> dict | None:
        """Load an order by its identifier."""
        return self.records.get(order_id)

    def save_order(self, order_id: str, order: dict) -> None:
        """Persist an order record."""
        self.records[order_id] = order

    def mark_paid(self, order_id: str) -> None:
        """Mark an order as paid."""
        self.records[order_id]["status"] = "paid"

    def cancel_order(self, order_id: str) -> None:
        """Mark an order as cancelled."""
        self.records[order_id]["status"] = "cancelled"

"""HTTP-facing order operations."""

from storage.order_store import OrderStore

def get_order_route(store, order_id: str) -> dict | None:
    """Return an order for the API caller."""
    return store.get_order(order_id)

def create_order_route(store: OrderStore, order_id: str, order: dict) -> None:
    """Create and persist a new order."""
    store.save_order(order_id, order)

def refund_order_route(store: OrderStore, order_id: str) -> None:
    """Mark an order for cancellation after refund."""
    store.cancel_order(order_id)

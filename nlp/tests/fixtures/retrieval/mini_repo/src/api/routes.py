"""HTTP route registration for payment requests."""

from payments.service import PaymentService


def register_routes(app, payment_service: PaymentService) -> None:
    """Register the payment endpoint."""
    app.post("/payments", payment_service.charge)

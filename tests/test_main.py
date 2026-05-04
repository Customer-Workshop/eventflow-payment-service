"""Tests for the FastAPI application endpoints and lifecycle."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import PaymentRecord, PaymentStatus


class TestLifespan:
    """Tests for application startup/shutdown lifecycle."""

    def test_lifespan_starts_and_stops_consumer(self):
        """Lifespan should call start_consumer on startup and stop_consumer on shutdown."""
        with (
            patch("app.main.start_consumer") as mock_start,
            patch("app.main.stop_consumer") as mock_stop,
        ):
            with TestClient(app):
                mock_start.assert_called_once()
            mock_stop.assert_called_once()


class TestGetPaymentEndpoint:
    """Tests for GET /api/payments/{payment_id}."""

    def test_get_payment_not_found(self, client):
        """Should return 404 for unknown payment ID."""
        response = client.get("/api/payments/nonexistent-id")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_payment_success(self, client):
        """Should return payment record when it exists."""
        from app.consumer import payments

        test_payment = PaymentRecord(
            payment_id="test-pay-001",
            order_id="order-001",
            customer_id="cust-001",
            currency="USD",
            amount_minor=5000,
            amount_display=50.0,
            status=PaymentStatus.COMPLETED,
        )
        payments["test-pay-001"] = test_payment
        try:
            response = client.get("/api/payments/test-pay-001")
            assert response.status_code == 200
            data = response.json()
            assert data["payment_id"] == "test-pay-001"
            assert data["order_id"] == "order-001"
            assert data["status"] == "completed"
        finally:
            payments.pop("test-pay-001", None)

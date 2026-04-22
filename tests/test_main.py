"""Tests for the FastAPI application endpoints and lifespan."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.consumer import payments
from app.main import app
from app.models import PaymentRecord, PaymentStatus


@pytest.fixture(autouse=True)
def _clear_payments():
    """Ensure payments dict is clean for each test."""
    payments.clear()
    yield
    payments.clear()


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI application."""
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# GET /api/payments/{payment_id}
# ---------------------------------------------------------------------------
class TestGetPayment:
    """Tests for the GET /api/payments/{payment_id} endpoint."""

    def test_returns_404_when_not_found(self, client: TestClient):
        """Returns 404 when payment_id doesn't exist."""
        response = client.get("/api/payments/nonexistent-id")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_returns_payment_when_exists(self, client: TestClient):
        """Returns payment record when it exists."""
        record = PaymentRecord(
            payment_id="pay-123",
            order_id="order-abc",
            customer_id="cust-xyz",
            currency="USD",
            amount_minor=5000,
            amount_display=50.0,
            status=PaymentStatus.COMPLETED,
        )
        payments["pay-123"] = record

        response = client.get("/api/payments/pay-123")
        assert response.status_code == 200
        body = response.json()
        assert body["payment_id"] == "pay-123"
        assert body["order_id"] == "order-abc"
        assert body["status"] == "completed"


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
class TestLifespan:
    """Tests for the application lifespan manager."""

    def test_lifespan_calls_start_and_stop_consumer(self):
        """Startup calls start_consumer and shutdown calls stop_consumer."""
        with (
            patch("app.main.start_consumer") as mock_start,
            patch("app.main.stop_consumer") as mock_stop,
        ):
            with TestClient(app):
                mock_start.assert_called_once()
            mock_stop.assert_called_once()

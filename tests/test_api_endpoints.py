"""Tests for API endpoints in app/main.py.

Covers health/readiness probes and payment CRUD endpoints.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.consumer import payments
from app.main import app
from app.models import PaymentRecord, PaymentStatus


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI application."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_payments():
    """Clear the in-memory payments store between tests."""
    payments.clear()
    yield
    payments.clear()


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, client):
        """Health endpoint should return 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_service_name(self, client):
        """Health response should include service name."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "eventflow-payment-service"


class TestReadinessEndpoint:
    """Tests for GET /ready."""

    def test_readiness_degraded_without_servicebus(self, client):
        """Should report degraded when Service Bus is not connected."""
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["servicebus_connected"] is False

    @patch("app.main.check_servicebus_health", new_callable=AsyncMock)
    def test_readiness_ready_with_servicebus(self, mock_health, client):
        """Should report ready when Service Bus is connected."""
        mock_health.return_value = True
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["servicebus_connected"] is True


class TestListPayments:
    """Tests for GET /api/payments."""

    def test_empty_payments_list(self, client):
        """Should return empty list when no payments exist."""
        response = client.get("/api/payments")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_payments(self, client):
        """Should return all stored payments."""
        payment = PaymentRecord(
            payment_id="pay-001",
            order_id="order-001",
            customer_id="cust-001",
            currency="USD",
            amount_minor=5000,
            amount_display=50.00,
            status=PaymentStatus.COMPLETED,
            processed_at=datetime.now(UTC),
        )
        payments["pay-001"] = payment

        response = client.get("/api/payments")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["payment_id"] == "pay-001"
        assert data[0]["order_id"] == "order-001"

    def test_returns_multiple_payments_sorted(self, client):
        """Should return payments sorted by processed_at descending."""
        for i in range(3):
            payment = PaymentRecord(
                payment_id=f"pay-{i:03d}",
                order_id=f"order-{i:03d}",
                customer_id="cust-001",
                currency="USD",
                amount_minor=1000 * (i + 1),
                amount_display=10.00 * (i + 1),
                status=PaymentStatus.COMPLETED,
                processed_at=datetime(2024, 1, i + 1, tzinfo=UTC),
            )
            payments[f"pay-{i:03d}"] = payment

        response = client.get("/api/payments")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        # Most recent first
        assert data[0]["payment_id"] == "pay-002"
        assert data[2]["payment_id"] == "pay-000"

    def test_limit_parameter(self, client):
        """Should respect the limit query parameter."""
        for i in range(5):
            payment = PaymentRecord(
                payment_id=f"pay-lim-{i:03d}",
                order_id=f"order-lim-{i:03d}",
                customer_id="cust-001",
                currency="USD",
                amount_minor=1000,
                amount_display=10.00,
                status=PaymentStatus.COMPLETED,
                processed_at=datetime(2024, 1, i + 1, tzinfo=UTC),
            )
            payments[f"pay-lim-{i:03d}"] = payment

        response = client.get("/api/payments?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2


class TestGetPayment:
    """Tests for GET /api/payments/{payment_id}."""

    def test_get_existing_payment(self, client):
        """Should return payment details for existing ID."""
        payment = PaymentRecord(
            payment_id="pay-found-001",
            order_id="order-found-001",
            customer_id="cust-001",
            currency="EUR",
            amount_minor=8999,
            amount_display=89.99,
            status=PaymentStatus.COMPLETED,
            processed_at=datetime.now(UTC),
        )
        payments["pay-found-001"] = payment

        response = client.get("/api/payments/pay-found-001")
        assert response.status_code == 200
        data = response.json()
        assert data["payment_id"] == "pay-found-001"
        assert data["order_id"] == "order-found-001"
        assert data["currency"] == "EUR"
        assert data["amount_minor"] == 8999
        assert data["amount_display"] == 89.99
        assert data["status"] == "completed"

    def test_get_nonexistent_payment(self, client):
        """Should return 404 for non-existent payment ID."""
        response = client.get("/api/payments/pay-nonexistent-999")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_get_failed_payment(self, client):
        """Should return failed payment with error message."""
        payment = PaymentRecord(
            payment_id="pay-fail-001",
            order_id="order-fail-001",
            customer_id="cust-001",
            currency="USD",
            amount_minor=10,
            amount_display=0.10,
            status=PaymentStatus.FAILED,
            error_message="Below minimum threshold",
            processed_at=datetime.now(UTC),
        )
        payments["pay-fail-001"] = payment

        response = client.get("/api/payments/pay-fail-001")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["error_message"] == "Below minimum threshold"

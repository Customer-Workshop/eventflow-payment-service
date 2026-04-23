"""Tests for FastAPI payment API endpoints."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.consumer import payments
from app.main import app
from app.models import PaymentRecord, PaymentStatus


class TestGetPaymentById:
    """Tests for GET /api/payments/{payment_id}."""

    def test_nonexistent_payment_returns_404(self, client: TestClient):
        """Requesting a non-existent payment_id should return 404."""
        response = client.get("/api/payments/does-not-exist")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_existing_payment_returns_record(self, client: TestClient):
        """Requesting an existing payment should return its data."""
        record = PaymentRecord(
            payment_id="pay-test-001",
            order_id="order-test-001",
            customer_id="cust-test-001",
            currency="USD",
            amount_minor=5000,
            amount_display=50.00,
            status=PaymentStatus.COMPLETED,
        )
        payments["pay-test-001"] = record

        try:
            response = client.get("/api/payments/pay-test-001")
            assert response.status_code == 200
            data = response.json()
            assert data["payment_id"] == "pay-test-001"
            assert data["order_id"] == "order-test-001"
            assert data["currency"] == "USD"
            assert data["amount_minor"] == 5000
            assert data["amount_display"] == 50.00
            assert data["status"] == "completed"
        finally:
            payments.pop("pay-test-001", None)


class TestListPayments:
    """Tests for GET /api/payments."""

    def test_list_payments_with_limit(self, client: TestClient):
        """Limit parameter should cap the number of returned payments."""
        created = []
        for i in range(5):
            pid = f"pay-limit-{i}"
            payments[pid] = PaymentRecord(
                payment_id=pid,
                order_id=f"order-limit-{i}",
                customer_id="cust-limit",
                currency="USD",
                amount_minor=1000 * (i + 1),
                amount_display=10.0 * (i + 1),
                status=PaymentStatus.COMPLETED,
            )
            created.append(pid)

        try:
            response = client.get("/api/payments?limit=3")
            assert response.status_code == 200
            data = response.json()
            assert len(data) <= 3
        finally:
            for pid in created:
                payments.pop(pid, None)

    def test_list_payments_sorted_by_processed_at_descending(self, client: TestClient):
        """Payments should be sorted by processed_at descending (newest first)."""
        now = datetime.now(UTC)
        old_record = PaymentRecord(
            payment_id="pay-old",
            order_id="order-old",
            customer_id="cust-sort",
            currency="USD",
            amount_minor=1000,
            amount_display=10.00,
            status=PaymentStatus.COMPLETED,
            processed_at=now - timedelta(hours=2),
        )
        new_record = PaymentRecord(
            payment_id="pay-new",
            order_id="order-new",
            customer_id="cust-sort",
            currency="USD",
            amount_minor=2000,
            amount_display=20.00,
            status=PaymentStatus.COMPLETED,
            processed_at=now,
        )
        payments["pay-old"] = old_record
        payments["pay-new"] = new_record

        try:
            response = client.get("/api/payments")
            assert response.status_code == 200
            data = response.json()
            pay_ids = [p["payment_id"] for p in data]
            old_idx = pay_ids.index("pay-old")
            new_idx = pay_ids.index("pay-new")
            assert new_idx < old_idx
        finally:
            payments.pop("pay-old", None)
            payments.pop("pay-new", None)


class TestCORSHeaders:
    """Tests for CORS middleware."""

    def test_cors_headers_present(self):
        """Responses should include CORS headers for cross-origin requests."""
        client = TestClient(app)
        response = client.get(
            "/health",
            headers={"Origin": "http://example.com"},
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "*"

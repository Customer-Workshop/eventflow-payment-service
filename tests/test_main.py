"""Tests for the FastAPI application endpoints."""

import time
from datetime import UTC, datetime

from app.consumer import payments
from app.models import PaymentRecord, PaymentStatus


class TestGetPaymentEndpoint:
    """Tests for GET /api/payments/{payment_id}."""

    def test_nonexistent_payment_returns_404(self, client):
        """Requesting a nonexistent payment ID should return 404."""
        response = client.get("/api/payments/nonexistent-id-999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestListPaymentsEndpoint:
    """Tests for GET /api/payments with parameters."""

    def test_list_payments_with_limit(self, client):
        """Payments list should respect the limit parameter."""
        original = dict(payments)
        try:
            payments.clear()
            for i in range(5):
                record = PaymentRecord(
                    payment_id=f"pay-limit-{i}",
                    order_id=f"order-limit-{i}",
                    customer_id="cust-limit",
                    currency="USD",
                    amount_minor=1000 + i,
                    amount_display=10.00 + i,
                    status=PaymentStatus.COMPLETED,
                )
                payments[record.payment_id] = record

            response = client.get("/api/payments?limit=3")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 3
        finally:
            payments.clear()
            payments.update(original)

    def test_list_payments_sorted_by_processed_at_descending(self, client):
        """Payments should be returned sorted by processed_at descending (newest first)."""
        original = dict(payments)
        try:
            payments.clear()
            for i in range(3):
                record = PaymentRecord(
                    payment_id=f"pay-sort-{i}",
                    order_id=f"order-sort-{i}",
                    customer_id="cust-sort",
                    currency="USD",
                    amount_minor=1000,
                    amount_display=10.00,
                    status=PaymentStatus.COMPLETED,
                    processed_at=datetime(2025, 1, 1 + i, tzinfo=UTC),
                )
                payments[record.payment_id] = record
                time.sleep(0.01)

            response = client.get("/api/payments")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 3
            timestamps = [item["processed_at"] for item in data]
            assert timestamps == sorted(timestamps, reverse=True)
        finally:
            payments.clear()
            payments.update(original)

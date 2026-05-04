"""Tests for the payment processor.

NOTE: These tests only cover USD and EUR currencies.
The JPY/KRW zero-decimal currency bug is NOT covered by these tests,
which is why it passes CI but fails in production.
"""

from unittest.mock import patch

import pytest

from app.models import OrderEventData, PaymentStatus
from app.processor import (
    GatewayResponse,
    convert_to_display_amount,
    process_order_payment,
    validate_payment_amount,
)


class TestConvertToDisplayAmount:
    """Tests for currency amount conversion."""

    def test_convert_usd_amount(self):
        """USD amounts should be divided by 100 to get dollars."""
        assert convert_to_display_amount(10997, "USD") == 109.97

    def test_convert_eur_amount(self):
        """EUR amounts should be divided by 100 to get euros."""
        assert convert_to_display_amount(8999, "EUR") == 89.99

    def test_convert_gbp_amount(self):
        """GBP amounts should be divided by 100 to get pounds."""
        assert convert_to_display_amount(5000, "GBP") == 50.00

    def test_convert_zero_amount(self):
        """Zero amount should convert to zero."""
        assert convert_to_display_amount(0, "USD") == 0.0

    def test_convert_jpy_amount_buggy_behavior(self):
        """Document the intentional bug: JPY is incorrectly divided by 100.

        JPY is a zero-decimal currency so 15800 JPY should remain 15800,
        but the buggy implementation divides by 100 yielding 158.0.
        """
        assert convert_to_display_amount(15800, "JPY") == 158.0

    def test_convert_krw_amount_buggy_behavior(self):
        """Document the intentional bug: KRW is incorrectly divided by 100."""
        assert convert_to_display_amount(50000, "KRW") == 500.0


class TestProcessOrderPayment:
    """Tests for end-to-end payment processing."""

    def test_process_usd_order(self, usd_order_event_data: OrderEventData):
        """USD order should be processed successfully."""
        payment = process_order_payment(usd_order_event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.order_id == "order-usd-001"
        assert payment.currency == "USD"
        assert payment.amount_minor == 10997
        assert payment.amount_display == 109.97

    def test_process_eur_order(self, eur_order_event_data: OrderEventData):
        """EUR order should be processed successfully."""
        payment = process_order_payment(eur_order_event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.order_id == "order-eur-001"
        assert payment.currency == "EUR"
        assert payment.amount_minor == 8999
        assert payment.amount_display == 89.99

    def test_process_large_usd_order(self):
        """Large USD orders should process without issues."""
        event_data = OrderEventData(
            order_id="order-large-001",
            customer_id="cust-big",
            currency="USD",
            amount=999999,
            items=[
                {"product_id": "p1", "name": "Premium Item", "quantity": 1, "unit_price": 999999}
            ],
        )
        payment = process_order_payment(event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.amount_display == 9999.99


class TestValidatePaymentAmount:
    """Tests for validate_payment_amount."""

    def test_valid_usd_amount(self):
        """Should not raise for amount above threshold."""
        validate_payment_amount(10.00, "USD")

    def test_below_threshold_raises(self):
        """Should raise ValueError for amount below minimum threshold."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.10, "USD")

    def test_jpy_below_threshold_raises(self):
        """Should raise ValueError for JPY amount below 500 threshold.

        This documents the bug path: 15800 JPY / 100 = 158.0 < 500.
        """
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(158.0, "JPY")

    def test_unknown_currency_uses_default_threshold(self):
        """Unknown currencies should use default 0.50 threshold."""
        validate_payment_amount(1.00, "XYZ")


class TestProcessOrderPaymentFailedGateway:
    """Tests for gateway failure path in process_order_payment."""

    @patch("app.processor.process_payment_through_gateway")
    def test_payment_failed_gateway_response(self, mock_gateway):
        """Should return FAILED status when gateway returns success=False."""
        mock_gateway.return_value = GatewayResponse(
            success=False,
            error="Card declined",
        )
        event_data = OrderEventData(
            order_id="order-fail-001",
            customer_id="cust-fail",
            currency="USD",
            amount=5000,
            items=[
                {"product_id": "p1", "name": "Item", "quantity": 1, "unit_price": 5000}
            ],
        )
        payment = process_order_payment(event_data)

        assert payment.status == PaymentStatus.FAILED
        assert payment.error_message == "Card declined"
        assert payment.order_id == "order-fail-001"


class TestHealthEndpoints:
    """Tests for health and readiness endpoints."""

    def test_health_check(self, client):
        """Health endpoint should return healthy."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_readiness_no_servicebus(self, client):
        """Readiness should report degraded without Service Bus."""
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "degraded"

    def test_list_payments_empty(self, client):
        """Payments list should return empty list initially."""
        response = client.get("/api/payments")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

"""Tests for the payment processor.

NOTE: These tests only cover USD and EUR currencies.
The JPY/KRW zero-decimal currency bug is NOT covered by these tests,
which is why it passes CI but fails in production.
"""

import pytest

from app.models import OrderEventData, PaymentStatus
from app.processor import (
    convert_to_display_amount,
    process_order_payment,
    process_payment_through_gateway,
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

    def test_process_order_below_minimum_threshold_raises(self):
        """USD order with amount below minimum threshold should raise ValueError."""
        event_data = OrderEventData(
            order_id="order-tiny-001",
            customer_id="cust-tiny",
            currency="USD",
            amount=10,
            items=[
                {"product_id": "p1", "name": "Tiny Item", "quantity": 1, "unit_price": 10}
            ],
        )
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event_data)

    def test_process_order_full_flow_fields(self, usd_order_event_data: OrderEventData):
        """Verify all fields of the returned PaymentRecord."""
        payment = process_order_payment(usd_order_event_data)

        assert payment.payment_id  # non-empty UUID string
        assert payment.order_id == usd_order_event_data.order_id
        assert payment.customer_id == usd_order_event_data.customer_id
        assert payment.currency == usd_order_event_data.currency
        assert payment.amount_minor == usd_order_event_data.amount
        assert payment.amount_display == usd_order_event_data.amount / 100
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.processed_at is not None
        assert payment.error_message is None


class TestValidatePaymentAmount:
    """Tests for validate_payment_amount()."""

    def test_amount_exactly_at_threshold(self):
        """Amount exactly at threshold should pass validation."""
        validate_payment_amount(0.50, "USD")

    def test_amount_below_threshold_raises(self):
        """Amount below threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.10, "USD")

    def test_amount_above_threshold(self):
        """Amount above threshold should pass validation."""
        validate_payment_amount(1.00, "USD")

    def test_unknown_currency_uses_default_threshold(self):
        """Unknown currency should use the default 0.50 threshold."""
        validate_payment_amount(0.50, "XYZ")
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.10, "XYZ")

    def test_chf_threshold(self):
        """CHF should use its specific threshold of 0.50."""
        validate_payment_amount(0.50, "CHF")
        with pytest.raises(ValueError):
            validate_payment_amount(0.30, "CHF")

    def test_cad_threshold(self):
        """CAD should use its specific threshold of 0.50."""
        validate_payment_amount(0.50, "CAD")
        with pytest.raises(ValueError):
            validate_payment_amount(0.10, "CAD")

    def test_aud_threshold(self):
        """AUD should use its specific threshold of 0.50."""
        validate_payment_amount(0.50, "AUD")
        with pytest.raises(ValueError):
            validate_payment_amount(0.10, "AUD")

    def test_cny_threshold(self):
        """CNY should use its specific threshold of 3.00."""
        validate_payment_amount(3.00, "CNY")
        with pytest.raises(ValueError):
            validate_payment_amount(1.00, "CNY")

    def test_inr_threshold(self):
        """INR should use its specific threshold of 50.0."""
        validate_payment_amount(50.0, "INR")
        with pytest.raises(ValueError):
            validate_payment_amount(10.0, "INR")


class TestProcessPaymentThroughGateway:
    """Tests for process_payment_through_gateway()."""

    def test_successful_gateway_response(self):
        """Gateway should return success with a transaction_id for valid amounts."""
        response = process_payment_through_gateway(10.00, "USD", "order-gw-001")
        assert response.success is True
        assert response.transaction_id is not None
        assert response.transaction_id.startswith("txn-")

    def test_gateway_failure_below_threshold(self):
        """Gateway should raise ValueError when amount is below threshold."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_payment_through_gateway(0.10, "USD", "order-gw-002")


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

"""Tests for the payment processor."""

from unittest.mock import patch

import pytest

from app.models import OrderEventData, PaymentStatus
from app.processor import (
    GatewayResponse,
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

    def test_convert_jpy_amount(self):
        """JPY amounts are incorrectly divided by 100 due to the zero-decimal bug."""
        assert convert_to_display_amount(15800, "JPY") == 158.0

    def test_convert_krw_amount(self):
        """KRW 49900 is divided by 100 to 499.0, which falls below the 500 KRW threshold."""
        assert convert_to_display_amount(49900, "KRW") == 499.0


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


class TestValidatePaymentAmount:
    """Tests for payment amount threshold validation."""

    def test_valid_usd_amount(self):
        """USD amount above threshold should not raise."""
        validate_payment_amount(10.00, "USD")

    def test_valid_eur_amount(self):
        """EUR amount at exactly the threshold should not raise."""
        validate_payment_amount(0.50, "EUR")

    def test_below_threshold_raises(self):
        """Amount below the currency threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.10, "USD")

    def test_below_threshold_gbp(self):
        """GBP amount below 0.30 threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.20, "GBP")

    def test_unknown_currency_uses_default_threshold(self):
        """Unknown currency should fall back to 0.50 default threshold."""
        validate_payment_amount(1.00, "XYZ")

    def test_unknown_currency_below_default_raises(self):
        """Unknown currency below the default 0.50 threshold should raise."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.10, "XYZ")

    def test_jpy_below_threshold_due_to_bug(self):
        """JPY 158.00 (bug-converted from 15800) is below the 500 JPY threshold."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(158.00, "JPY")


class TestProcessPaymentThroughGateway:
    """Tests for the simulated payment gateway."""

    def test_successful_gateway_response(self):
        """Valid amount should produce a successful gateway response."""
        response = process_payment_through_gateway(50.00, "USD", "order-001")
        assert response.success is True
        assert response.transaction_id is not None
        assert response.transaction_id.startswith("txn-")

    def test_gateway_rejects_below_threshold(self):
        """Amount below the minimum threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_payment_through_gateway(0.10, "USD", "order-002")

    def test_jpy_order_fails_gateway_due_to_bug(self):
        """JPY display_amount of 158.00 (from the conversion bug) fails validation."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_payment_through_gateway(158.00, "JPY", "order-jpy-001")


class TestProcessOrderPaymentZeroDecimalBug:
    """Tests demonstrating the zero-decimal currency conversion bug.

    The ValueError raised inside the gateway propagates uncaught through
    process_order_payment — it never reaches the success/failure branch
    on lines 155-175.
    """

    def test_jpy_order_raises_due_to_conversion_bug(self):
        """JPY order triggers ValueError because the buggy conversion produces
        a display amount below the 500 JPY threshold."""
        event_data = OrderEventData(
            order_id="order-jpy-001",
            customer_id="cust-jpy",
            currency="JPY",
            amount=15800,
            items=[
                {"product_id": "p1", "name": "Bento Box", "quantity": 1, "unit_price": 15800}
            ],
        )
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event_data)

    def test_krw_order_raises_due_to_conversion_bug(self):
        """KRW order triggers ValueError because 49900 / 100 = 499.0,
        which is below the 500 KRW threshold."""
        event_data = OrderEventData(
            order_id="order-krw-001",
            customer_id="cust-krw",
            currency="KRW",
            amount=49900,
            items=[
                {"product_id": "p1", "name": "Korean Snack", "quantity": 1, "unit_price": 49900}
            ],
        )
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event_data)


class TestProcessOrderPaymentGatewayFailure:
    """Tests for the gateway failure return path (lines 170-175)."""

    def test_gateway_failure_returns_failed_record(self):
        """When the gateway returns success=False, the payment record should be FAILED."""
        event_data = OrderEventData(
            order_id="order-fail-001",
            customer_id="cust-fail",
            currency="USD",
            amount=5000,
            items=[
                {"product_id": "p1", "name": "Widget", "quantity": 1, "unit_price": 5000}
            ],
        )
        mock_response = GatewayResponse(
            success=False,
            error="Card declined",
        )
        with patch(
            "app.processor.process_payment_through_gateway",
            return_value=mock_response,
        ):
            payment = process_order_payment(event_data)

        assert payment.status == PaymentStatus.FAILED
        assert payment.error_message == "Card declined"
        assert payment.order_id == "order-fail-001"
        assert payment.amount_display == 50.00

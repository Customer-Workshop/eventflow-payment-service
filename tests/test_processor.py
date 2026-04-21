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

    def test_convert_jpy_amount_bug(self):
        """JPY amounts are incorrectly divided by 100 (documents the bug).

        15800 JPY should remain 15800 (zero-decimal currency) but the bug
        divides by 100 producing 158.0.
        """
        result = convert_to_display_amount(15800, "JPY")
        assert result == 158.0  # BUG: should be 15800

    def test_convert_krw_amount_bug(self):
        """KRW amounts are incorrectly divided by 100 (documents the bug).

        50000 KRW should remain 50000 (zero-decimal currency) but the bug
        divides by 100 producing 500.0.
        """
        result = convert_to_display_amount(50000, "KRW")
        assert result == 500.0  # BUG: should be 50000


class TestValidatePaymentAmount:
    """Tests for payment amount validation against minimum thresholds."""

    def test_usd_below_threshold_raises(self):
        """USD amount below $0.50 threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.30, "USD")

    def test_eur_below_threshold_raises(self):
        """EUR amount below €0.50 threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.49, "EUR")

    def test_gbp_below_threshold_raises(self):
        """GBP amount below £0.30 threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.20, "GBP")

    def test_jpy_below_threshold_raises(self):
        """JPY amount below ¥500 threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(499.0, "JPY")

    def test_usd_at_threshold_passes(self):
        """USD amount exactly at $0.50 threshold should pass."""
        validate_payment_amount(0.50, "USD")

    def test_jpy_at_threshold_passes(self):
        """JPY amount exactly at ¥500 threshold should pass."""
        validate_payment_amount(500.0, "JPY")

    def test_usd_above_threshold_passes(self):
        """USD amount above $0.50 threshold should pass."""
        validate_payment_amount(10.00, "USD")

    def test_unknown_currency_uses_default_threshold(self):
        """Unknown currency should use the default threshold of 0.50."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.30, "XYZ")

    def test_unknown_currency_above_default_passes(self):
        """Unknown currency above the default 0.50 threshold should pass."""
        validate_payment_amount(1.00, "XYZ")


class TestProcessPaymentThroughGateway:
    """Tests for the simulated payment gateway."""

    def test_successful_gateway_response(self):
        """Successful gateway call should return GatewayResponse with success and transaction_id."""
        response = process_payment_through_gateway(10.00, "USD", "order-gw-001")
        assert isinstance(response, GatewayResponse)
        assert response.success is True
        assert response.transaction_id is not None
        assert response.transaction_id.startswith("txn-")

    def test_gateway_rejects_below_threshold(self):
        """Gateway should raise ValueError when amount is below minimum threshold."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_payment_through_gateway(0.10, "USD", "order-gw-002")


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

    def test_process_jpy_order_raises_bug(self, jpy_order_event_data: OrderEventData):
        """JPY order should raise ValueError due to the conversion bug.

        15800 JPY is incorrectly converted to 158.0, which is below the
        500 JPY minimum threshold, causing a ValueError.
        """
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(jpy_order_event_data)

    def test_process_krw_order_raises_bug(self, krw_order_event_data: OrderEventData):
        """KRW order should raise ValueError due to the conversion bug.

        50000 KRW is incorrectly converted to 500.0, which is at the threshold
        but 500.0 >= 500.0 so this actually passes. Let's use a smaller amount.
        """
        small_krw = OrderEventData(
            order_id="order-krw-002",
            customer_id="cust-007",
            currency="KRW",
            amount=30000,
            items=[
                {"product_id": "p1", "name": "Item", "quantity": 1, "unit_price": 30000}
            ],
        )
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(small_krw)

    def test_process_jpy_order_passes_threshold_with_wrong_amount(
        self, jpy_order_event_data_passes_threshold: OrderEventData
    ):
        """A JPY order with amount=50000 passes threshold after wrong conversion.

        50000 / 100 = 500.0, which equals the JPY threshold of 500.
        The payment completes but with an incorrect display amount.
        """
        payment = process_order_payment(jpy_order_event_data_passes_threshold)
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.amount_display == 500.0  # BUG: should be 50000
        assert payment.amount_minor == 50000

    def test_payment_record_fields_populated(self, usd_order_event_data: OrderEventData):
        """PaymentRecord should have all fields correctly populated."""
        payment = process_order_payment(usd_order_event_data)

        assert len(payment.payment_id) > 0
        assert payment.processed_at is not None
        assert payment.order_id == "order-usd-001"
        assert payment.customer_id == "cust-001"
        assert payment.error_message is None

    def test_gateway_failure_returns_failed_payment(self, usd_order_event_data: OrderEventData):
        """When gateway returns failure, payment should have FAILED status."""
        mock_response = GatewayResponse(
            success=False,
            transaction_id=None,
            error="Gateway timeout",
        )
        with patch(
            "app.processor.process_payment_through_gateway", return_value=mock_response
        ):
            payment = process_order_payment(usd_order_event_data)

        assert payment.status == PaymentStatus.FAILED
        assert payment.error_message == "Gateway timeout"


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

"""Tests for the payment processor."""

import pytest

from app.models import OrderEventData, PaymentStatus
from app.processor import (
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

    def test_convert_jpy_amount(self):
        """JPY is zero-decimal: amount is already in base units."""
        assert convert_to_display_amount(15800, "JPY") == 15800.0

    def test_convert_krw_amount(self):
        """KRW is zero-decimal: amount is already in base units."""
        assert convert_to_display_amount(125000, "KRW") == 125000.0

    def test_convert_jpy_small_amount(self):
        """JPY small amount should not be divided."""
        assert convert_to_display_amount(500, "JPY") == 500.0

    def test_convert_bhd_amount(self):
        """BHD is three-decimal: amount should be divided by 1000."""
        assert convert_to_display_amount(15800, "BHD") == 15.8

    def test_convert_kwd_amount(self):
        """KWD is three-decimal: amount should be divided by 1000."""
        assert convert_to_display_amount(5250, "KWD") == 5.25

    def test_unknown_currency_defaults_to_two_decimals(self):
        """Unknown currency should default to 2 decimal places."""
        assert convert_to_display_amount(1999, "XYZ") == 19.99

    def test_convert_zero_amount(self):
        """Zero amount should convert to zero."""
        assert convert_to_display_amount(0, "USD") == 0.0

    def test_convert_zero_amount_jpy(self):
        """Zero JPY amount should convert to zero."""
        assert convert_to_display_amount(0, "JPY") == 0.0

    def test_currency_code_case_insensitive(self):
        """Currency code matching should be case-insensitive."""
        assert convert_to_display_amount(15800, "jpy") == 15800.0


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

    def test_process_jpy_order(self, jpy_order_event_data: OrderEventData):
        """JPY order should be processed with the correct display amount."""
        payment = process_order_payment(jpy_order_event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.order_id == "order-jpy-001"
        assert payment.currency == "JPY"
        assert payment.amount_minor == 15800
        assert payment.amount_display == 15800.0

    def test_process_krw_order(self, krw_order_event_data: OrderEventData):
        """KRW order should be processed with the correct display amount."""
        payment = process_order_payment(krw_order_event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.order_id == "order-krw-001"
        assert payment.currency == "KRW"
        assert payment.amount_minor == 125000
        assert payment.amount_display == 125000.0

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

    def test_jpy_below_threshold_fails(self):
        """JPY amount below 500 threshold should raise ValueError."""
        event_data = OrderEventData(
            order_id="order-jpy-low",
            customer_id="cust-low",
            currency="JPY",
            amount=100,
            items=[
                {"product_id": "p1", "name": "Sticker", "quantity": 1, "unit_price": 100}
            ],
        )
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event_data)


class TestValidatePaymentAmount:
    """Tests for minimum threshold validation."""

    def test_usd_above_threshold(self):
        validate_payment_amount(1.00, "USD")

    def test_usd_below_threshold(self):
        with pytest.raises(ValueError):
            validate_payment_amount(0.10, "USD")

    def test_jpy_above_threshold(self):
        validate_payment_amount(600.0, "JPY")

    def test_jpy_below_threshold(self):
        with pytest.raises(ValueError):
            validate_payment_amount(100.0, "JPY")

    def test_bhd_above_threshold(self):
        validate_payment_amount(1.00, "BHD")


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

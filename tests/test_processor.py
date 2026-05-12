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
        """JPY is a zero-decimal currency — amount is already in base units."""
        assert convert_to_display_amount(15800, "JPY") == 15800.0

    def test_convert_krw_amount(self):
        """KRW is a zero-decimal currency — amount is already in base units."""
        assert convert_to_display_amount(55000, "KRW") == 55000.0

    def test_convert_vnd_amount(self):
        """VND is a zero-decimal currency — amount is already in base units."""
        assert convert_to_display_amount(250000, "VND") == 250000.0

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

    def test_process_jpy_order(self):
        """JPY order should be processed successfully with correct display amount."""
        event_data = OrderEventData(
            order_id="order-jpy-001",
            customer_id="cust-jp",
            currency="JPY",
            amount=15800,
            items=[
                {"product_id": "p1", "name": "Bento Box", "quantity": 1, "unit_price": 15800}
            ],
        )
        payment = process_order_payment(event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.currency == "JPY"
        assert payment.amount_minor == 15800
        assert payment.amount_display == 15800.0

    def test_process_krw_order(self):
        """KRW order should be processed successfully with correct display amount."""
        event_data = OrderEventData(
            order_id="order-krw-001",
            customer_id="cust-kr",
            currency="KRW",
            amount=55000,
            items=[
                {"product_id": "p1", "name": "K-Pop Album", "quantity": 1, "unit_price": 55000}
            ],
        )
        payment = process_order_payment(event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.currency == "KRW"
        assert payment.amount_minor == 55000
        assert payment.amount_display == 55000.0

    def test_process_jpy_at_threshold_boundary(self):
        """JPY order exactly at the 500 threshold should succeed."""
        event_data = OrderEventData(
            order_id="order-jpy-boundary",
            customer_id="cust-jp",
            currency="JPY",
            amount=500,
            items=[
                {"product_id": "p1", "name": "Snack", "quantity": 1, "unit_price": 500}
            ],
        )
        payment = process_order_payment(event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.amount_display == 500.0

    def test_process_jpy_below_threshold_fails(self):
        """JPY order below 500 threshold should raise ValueError."""
        event_data = OrderEventData(
            order_id="order-jpy-low",
            customer_id="cust-jp",
            currency="JPY",
            amount=499,
            items=[
                {"product_id": "p1", "name": "Candy", "quantity": 1, "unit_price": 499}
            ],
        )
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event_data)

    def test_process_krw_below_threshold_fails(self):
        """KRW order below 500 threshold should raise ValueError."""
        event_data = OrderEventData(
            order_id="order-krw-low",
            customer_id="cust-kr",
            currency="KRW",
            amount=100,
            items=[
                {"product_id": "p1", "name": "Sticker", "quantity": 1, "unit_price": 100}
            ],
        )
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event_data)

    def test_process_usd_below_threshold_fails(self):
        """USD order below $0.50 threshold should raise ValueError."""
        event_data = OrderEventData(
            order_id="order-usd-low",
            customer_id="cust-us",
            currency="USD",
            amount=10,
            items=[
                {"product_id": "p1", "name": "Tiny Item", "quantity": 1, "unit_price": 10}
            ],
        )
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event_data)

    def test_process_vnd_order(self):
        """VND zero-decimal currency order should process correctly."""
        event_data = OrderEventData(
            order_id="order-vnd-001",
            customer_id="cust-vn",
            currency="VND",
            amount=250000,
            items=[
                {"product_id": "p1", "name": "Pho", "quantity": 1, "unit_price": 250000}
            ],
        )
        payment = process_order_payment(event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.amount_display == 250000.0

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
    """Tests for threshold validation."""

    def test_jpy_above_threshold_passes(self):
        """JPY amount above 500 should not raise."""
        validate_payment_amount(15800.0, "JPY")

    def test_jpy_at_threshold_passes(self):
        """JPY amount exactly at 500 should not raise."""
        validate_payment_amount(500.0, "JPY")

    def test_jpy_below_threshold_raises(self):
        """JPY amount below 500 should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(499.0, "JPY")

    def test_usd_below_threshold_raises(self):
        """USD amount below 0.50 should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.10, "USD")

    def test_unknown_currency_uses_default_threshold(self):
        """Unknown currency should use the default 0.50 threshold."""
        validate_payment_amount(0.50, "XYZ")
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.49, "XYZ")


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

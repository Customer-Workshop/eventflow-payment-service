"""Edge case tests for the payment processor.

Covers boundary conditions, large amounts, minimum thresholds,
and invalid/malformed input handling.
"""

import pytest

from app.models import OrderEventData, PaymentStatus
from app.processor import (
    GatewayResponse,
    convert_to_display_amount,
    process_order_payment,
    process_payment_through_gateway,
    validate_payment_amount,
)


class TestValidatePaymentAmount:
    """Tests for validate_payment_amount edge cases."""

    def test_exact_threshold_usd(self):
        """Amount exactly at threshold should pass."""
        # Should not raise
        validate_payment_amount(0.50, "USD")

    def test_below_threshold_usd(self):
        """Amount below threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.49, "USD")

    def test_above_threshold_usd(self):
        """Amount above threshold should pass."""
        validate_payment_amount(1.00, "USD")

    def test_below_threshold_jpy(self):
        """Amount below JPY threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(499.99, "JPY")

    def test_exact_threshold_jpy(self):
        """Amount exactly at JPY threshold should pass."""
        validate_payment_amount(500.0, "JPY")

    def test_below_threshold_krw(self):
        """Amount below KRW threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(499.0, "KRW")

    def test_unknown_currency_uses_default(self):
        """Unknown currency should use default threshold of 0.50."""
        # Above default threshold - should pass
        validate_payment_amount(0.50, "XYZ")

    def test_unknown_currency_below_default(self):
        """Unknown currency below default threshold should raise."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.49, "XYZ")


class TestProcessPaymentThroughGateway:
    """Tests for process_payment_through_gateway."""

    def test_successful_gateway_response(self):
        """Gateway should return success for valid amount."""
        response = process_payment_through_gateway(50.00, "USD", "order-001")
        assert response.success is True
        assert response.transaction_id is not None
        assert response.transaction_id.startswith("txn-")

    def test_gateway_below_threshold_raises(self):
        """Gateway should raise ValueError for amount below threshold."""
        with pytest.raises(ValueError):
            process_payment_through_gateway(0.10, "USD", "order-001")

    def test_gateway_jpy_valid_amount(self):
        """Gateway should succeed for valid JPY display amount."""
        response = process_payment_through_gateway(15800.0, "JPY", "order-jpy-001")
        assert response.success is True

    def test_gateway_jpy_below_threshold(self):
        """Gateway should raise for JPY display amount below 500."""
        with pytest.raises(ValueError):
            process_payment_through_gateway(158.0, "JPY", "order-jpy-001")


class TestConvertToDisplayAmountEdgeCases:
    """Edge cases for convert_to_display_amount."""

    def test_very_large_amount(self):
        """Very large amounts should convert correctly."""
        # 1 billion cents = 10 million dollars
        result = convert_to_display_amount(1_000_000_000, "USD")
        assert result == 10_000_000.0

    def test_single_cent(self):
        """Single cent should convert to 0.01."""
        result = convert_to_display_amount(1, "USD")
        assert result == 0.01

    def test_negative_amount(self):
        """Negative amounts (refunds) should convert correctly."""
        result = convert_to_display_amount(-5000, "USD")
        assert result == -50.0

    def test_maximum_int_amount(self):
        """Very large int amounts should not overflow."""
        result = convert_to_display_amount(2**31 - 1, "USD")
        assert result == (2**31 - 1) / 100


class TestProcessOrderPaymentEdgeCases:
    """Edge cases for process_order_payment."""

    def test_very_large_usd_payment(self):
        """Very large USD payments should process successfully."""
        event_data = OrderEventData(
            order_id="order-large-001",
            customer_id="cust-large",
            currency="USD",
            amount=50_000_000,  # $500,000
            items=[
                {
                    "product_id": "prod-luxury",
                    "name": "Luxury Item",
                    "quantity": 1,
                    "unit_price": 50_000_000,
                }
            ],
        )
        payment = process_order_payment(event_data)
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.amount_display == 500_000.0

    def test_minimum_valid_usd_payment(self):
        """Minimum valid USD payment (50 cents) should succeed."""
        event_data = OrderEventData(
            order_id="order-min-001",
            customer_id="cust-min",
            currency="USD",
            amount=50,  # 50 cents
            items=[
                {
                    "product_id": "prod-cheap",
                    "name": "Sticker",
                    "quantity": 1,
                    "unit_price": 50,
                }
            ],
        )
        payment = process_order_payment(event_data)
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.amount_display == 0.50

    def test_below_minimum_usd_payment(self):
        """USD payment below minimum threshold should raise ValueError."""
        event_data = OrderEventData(
            order_id="order-too-small",
            customer_id="cust-small",
            currency="USD",
            amount=10,  # 10 cents = $0.10 (below $0.50 threshold)
            items=[
                {
                    "product_id": "prod-tiny",
                    "name": "Nothing",
                    "quantity": 1,
                    "unit_price": 10,
                }
            ],
        )
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event_data)

    def test_gbp_minimum_threshold(self):
        """GBP payment at exactly 30 pence threshold should succeed."""
        event_data = OrderEventData(
            order_id="order-gbp-min",
            customer_id="cust-gbp",
            currency="GBP",
            amount=30,  # 30 pence
            items=[
                {
                    "product_id": "prod-uk",
                    "name": "Badge",
                    "quantity": 1,
                    "unit_price": 30,
                }
            ],
        )
        payment = process_order_payment(event_data)
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.amount_display == 0.30

    def test_payment_record_has_all_fields(self):
        """Completed payment should have all fields populated."""
        event_data = OrderEventData(
            order_id="order-fields-001",
            customer_id="cust-fields",
            currency="USD",
            amount=9999,
            items=[
                {
                    "product_id": "prod-f1",
                    "name": "Field Test Item",
                    "quantity": 1,
                    "unit_price": 9999,
                }
            ],
        )
        payment = process_order_payment(event_data)

        assert payment.payment_id is not None
        assert payment.order_id == "order-fields-001"
        assert payment.customer_id == "cust-fields"
        assert payment.currency == "USD"
        assert payment.amount_minor == 9999
        assert payment.amount_display == 99.99
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.processed_at is not None
        assert payment.error_message is None


class TestProcessOrderPaymentFailedGateway:
    """Tests for process_order_payment when gateway returns failure."""

    @pytest.fixture
    def _patch_gateway(self, monkeypatch):
        """Patch process_payment_through_gateway to return failure."""
        from app import processor

        def mock_gateway(display_amount, currency, order_id):
            return GatewayResponse(success=False, error="Gateway timeout")

        monkeypatch.setattr(processor, "process_payment_through_gateway", mock_gateway)

    def test_failed_gateway_returns_failed_record(self, _patch_gateway):
        """Payment should have FAILED status when gateway fails."""
        event_data = OrderEventData(
            order_id="order-gw-fail-001",
            customer_id="cust-gw",
            currency="USD",
            amount=5000,
            items=[
                {
                    "product_id": "prod-gw",
                    "name": "Gateway Fail Item",
                    "quantity": 1,
                    "unit_price": 5000,
                }
            ],
        )
        payment = process_order_payment(event_data)

        assert payment.status == PaymentStatus.FAILED
        assert payment.error_message == "Gateway timeout"
        assert payment.order_id == "order-gw-fail-001"
        assert payment.amount_display == 50.0


class TestGatewayResponse:
    """Tests for GatewayResponse dataclass."""

    def test_success_response(self):
        """Successful response should have transaction_id."""
        response = GatewayResponse(success=True, transaction_id="txn-abc123")
        assert response.success is True
        assert response.transaction_id == "txn-abc123"
        assert response.error is None

    def test_failure_response(self):
        """Failed response should have error message."""
        response = GatewayResponse(success=False, error="Insufficient funds")
        assert response.success is False
        assert response.transaction_id is None
        assert response.error == "Insufficient funds"

    def test_default_values(self):
        """Default values should be None."""
        response = GatewayResponse(success=True)
        assert response.transaction_id is None
        assert response.error is None

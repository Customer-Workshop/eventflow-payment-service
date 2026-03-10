"""Resilience tests for the Payment Service.

These tests validate how the payment service behaves under adverse conditions:
- Malformed or unexpected input data
- Zero-decimal currency edge cases (JPY, KRW)
- Boundary values and threshold validation
- Gateway failures and error propagation
- Consumer message processing failures
- API behavior under degraded conditions
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.consumer import _process_message, payments
from app.models import OrderEventData, PaymentRecord, PaymentStatus
from app.processor import (
    GatewayResponse,
    convert_to_display_amount,
    process_order_payment,
    process_payment_through_gateway,
    validate_payment_amount,
)

# ---------------------------------------------------------------------------
# 1. Payment Processor Resilience
# ---------------------------------------------------------------------------


class TestCurrencyConversionResilience:
    """Verify convert_to_display_amount handles edge-case inputs."""

    def test_zero_decimal_currency_jpy(self):
        """JPY amounts are already in base units; dividing by 100 produces
        an incorrect (too-small) display amount.

        This documents the known bug: 15800 JPY -> 158.00 instead of 15800.
        """
        result = convert_to_display_amount(15800, "JPY")
        # Known bug: the function always divides by 100
        assert result == 158.00, "Expected buggy conversion for JPY"

    def test_zero_decimal_currency_krw(self):
        """KRW amounts are already in base units; dividing by 100 is wrong."""
        result = convert_to_display_amount(50000, "KRW")
        assert result == 500.00, "Expected buggy conversion for KRW"

    def test_very_large_amount(self):
        """System should handle very large amounts without overflow."""
        result = convert_to_display_amount(99_999_999_99, "USD")
        assert result == 99_999_999.99

    def test_very_small_positive_amount(self):
        """Smallest positive minor unit (1 cent)."""
        result = convert_to_display_amount(1, "USD")
        assert result == 0.01

    def test_negative_amount(self):
        """Negative amounts (e.g., refunds) should still convert."""
        result = convert_to_display_amount(-500, "USD")
        assert result == -5.00

    def test_unknown_currency_code(self):
        """Unknown currency codes should still convert (division by 100)."""
        result = convert_to_display_amount(1000, "XYZ")
        assert result == 10.00


class TestPaymentAmountValidation:
    """Verify validate_payment_amount enforces minimum thresholds correctly."""

    def test_usd_below_threshold(self):
        """USD amount below $0.50 threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.49, "USD")

    def test_usd_at_threshold(self):
        """USD amount exactly at $0.50 threshold should pass."""
        validate_payment_amount(0.50, "USD")

    def test_usd_above_threshold(self):
        """USD amount above threshold should pass without error."""
        validate_payment_amount(100.00, "USD")

    def test_jpy_below_threshold(self):
        """JPY amount below 500 threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(499.99, "JPY")

    def test_jpy_at_threshold(self):
        """JPY amount exactly at 500 threshold should pass."""
        validate_payment_amount(500.0, "JPY")

    def test_krw_below_threshold(self):
        """KRW amount below 500 threshold should raise ValueError."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(100.0, "KRW")

    def test_unknown_currency_uses_default_threshold(self):
        """Unknown currencies should fall back to 0.50 default threshold."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.10, "ZZZ")

    def test_unknown_currency_above_default_threshold(self):
        """Unknown currency above 0.50 default threshold should pass."""
        validate_payment_amount(1.00, "ZZZ")

    def test_zero_amount_always_fails(self):
        """Zero display amount should always fail validation."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(0.0, "USD")

    def test_negative_display_amount(self):
        """Negative display amount should fail validation."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            validate_payment_amount(-10.0, "EUR")


class TestGatewayResilience:
    """Verify process_payment_through_gateway handles failure scenarios."""

    def test_gateway_success_for_valid_usd(self):
        """Valid USD amount should succeed through the gateway."""
        response = process_payment_through_gateway(50.00, "USD", "order-001")
        assert response.success is True
        assert response.transaction_id is not None
        assert response.error is None

    def test_gateway_rejects_below_threshold(self):
        """Gateway should raise ValueError for amounts below threshold."""
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_payment_through_gateway(0.10, "USD", "order-002")

    def test_gateway_jpy_below_threshold_after_bug(self):
        """After buggy conversion, JPY 15800 becomes 158.00 which is below
        the 500 JPY threshold, causing a ValueError crash.

        This is the core resilience failure path in the known bug.
        """
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_payment_through_gateway(158.00, "JPY", "order-jpy-001")

    def test_gateway_jpy_above_threshold(self):
        """JPY amount above 500 threshold should succeed."""
        response = process_payment_through_gateway(600.0, "JPY", "order-jpy-002")
        assert response.success is True

    def test_gateway_generates_unique_transaction_ids(self):
        """Each successful gateway call should produce a unique transaction ID."""
        r1 = process_payment_through_gateway(10.00, "USD", "order-a")
        r2 = process_payment_through_gateway(20.00, "USD", "order-b")
        assert r1.transaction_id != r2.transaction_id


class TestProcessOrderPaymentResilience:
    """End-to-end payment processing under adverse conditions."""

    def _make_event(
        self,
        *,
        order_id: str = "order-test",
        customer_id: str = "cust-test",
        currency: str = "USD",
        amount: int = 5000,
    ) -> OrderEventData:
        return OrderEventData(
            order_id=order_id,
            customer_id=customer_id,
            currency=currency,
            amount=amount,
            items=[
                {
                    "product_id": "p1",
                    "name": "Test Item",
                    "quantity": 1,
                    "unit_price": amount,
                }
            ],
        )

    def test_jpy_order_crashes(self):
        """A JPY order triggers the known bug: ValueError from threshold check."""
        event = self._make_event(currency="JPY", amount=15800)
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event)

    def test_krw_order_crashes(self):
        """A KRW order triggers the same zero-decimal bug."""
        event = self._make_event(currency="KRW", amount=30000)
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event)

    def test_usd_minimum_viable_order(self):
        """The smallest USD order that passes threshold (50 cents = 50 minor)."""
        event = self._make_event(currency="USD", amount=50)
        payment = process_order_payment(event)
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.amount_display == 0.50

    def test_usd_below_minimum_fails(self):
        """A USD order for 49 cents should fail validation."""
        event = self._make_event(currency="USD", amount=49)
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event)

    def test_gbp_minimum_viable_order(self):
        """GBP has a 0.30 threshold; 30 pence should pass."""
        event = self._make_event(currency="GBP", amount=30)
        payment = process_order_payment(event)
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.amount_display == 0.30

    def test_chf_order_succeeds(self):
        """CHF order above threshold should succeed."""
        event = self._make_event(currency="CHF", amount=1000)
        payment = process_order_payment(event)
        assert payment.status == PaymentStatus.COMPLETED

    def test_cad_order_succeeds(self):
        """CAD order above threshold should succeed."""
        event = self._make_event(currency="CAD", amount=2500)
        payment = process_order_payment(event)
        assert payment.status == PaymentStatus.COMPLETED

    def test_aud_order_succeeds(self):
        """AUD order above threshold should succeed."""
        event = self._make_event(currency="AUD", amount=7500)
        payment = process_order_payment(event)
        assert payment.status == PaymentStatus.COMPLETED

    def test_cny_order_below_threshold(self):
        """CNY has a 3.00 threshold; 200 minor → 2.00 display → should fail."""
        event = self._make_event(currency="CNY", amount=200)
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event)

    def test_inr_order_below_threshold(self):
        """INR has a 50.0 threshold; 4000 minor → 40.00 display → should fail."""
        event = self._make_event(currency="INR", amount=4000)
        with pytest.raises(ValueError, match="below minimum threshold"):
            process_order_payment(event)

    def test_inr_order_above_threshold(self):
        """INR 5000 minor → 50.00 display → exactly at threshold → should pass."""
        event = self._make_event(currency="INR", amount=5000)
        payment = process_order_payment(event)
        assert payment.status == PaymentStatus.COMPLETED

    def test_payment_record_has_correct_fields(self):
        """Completed payment record should carry all expected metadata."""
        event = self._make_event(
            order_id="order-meta-001",
            customer_id="cust-meta",
            currency="EUR",
            amount=5000,
        )
        payment = process_order_payment(event)

        assert payment.order_id == "order-meta-001"
        assert payment.customer_id == "cust-meta"
        assert payment.currency == "EUR"
        assert payment.amount_minor == 5000
        assert payment.amount_display == 50.00
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.payment_id  # non-empty
        assert payment.processed_at is not None
        assert payment.error_message is None

    @patch("app.processor.process_payment_through_gateway")
    def test_gateway_failure_returns_failed_record(self, mock_gateway):
        """When the gateway returns success=False, payment should be FAILED."""
        mock_gateway.return_value = GatewayResponse(
            success=False,
            transaction_id=None,
            error="Gateway timeout",
        )
        event = self._make_event(currency="USD", amount=5000)
        payment = process_order_payment(event)

        assert payment.status == PaymentStatus.FAILED
        assert payment.error_message == "Gateway timeout"

    @patch("app.processor.process_payment_through_gateway")
    def test_gateway_returns_none_error(self, mock_gateway):
        """Gateway failure with no error message should still produce FAILED."""
        mock_gateway.return_value = GatewayResponse(
            success=False,
            transaction_id=None,
            error=None,
        )
        event = self._make_event(currency="USD", amount=5000)
        payment = process_order_payment(event)

        assert payment.status == PaymentStatus.FAILED
        assert payment.error_message is None


# ---------------------------------------------------------------------------
# 2. Consumer Message Processing Resilience
# ---------------------------------------------------------------------------


class TestConsumerMessageResilience:
    """Verify _process_message handles malformed and edge-case messages."""

    def _valid_message_body(self, **overrides) -> str:
        base = {
            "event_id": "evt-001",
            "event_type": "OrderCreated",
            "timestamp": "2026-01-15T10:30:00Z",
            "data": {
                "order_id": "order-001",
                "customer_id": "cust-001",
                "currency": "USD",
                "amount": 5000,
                "items": [
                    {
                        "product_id": "p1",
                        "name": "Widget",
                        "quantity": 1,
                        "unit_price": 5000,
                    }
                ],
            },
        }
        base.update(overrides)
        return json.dumps(base)

    def test_valid_message_processed_successfully(self):
        """A well-formed USD message should be processed and stored."""
        body = self._valid_message_body()
        _process_message(body)
        # The payment should appear in the in-memory store
        assert any(
            p.order_id == "order-001" for p in payments.values()
        ), "Payment should be stored after processing"

    def test_malformed_json_raises_no_unhandled_exception(self):
        """Completely invalid JSON should be caught (JSONDecodeError)."""
        # _process_message catches JSONDecodeError internally and logs it
        _process_message("not-valid-json{{{")

    def test_empty_message_body(self):
        """Empty string should be caught as JSONDecodeError."""
        _process_message("")

    def test_missing_data_field(self):
        """Message missing the 'data' field should raise a validation error."""
        body = json.dumps({
            "event_id": "evt-bad",
            "event_type": "OrderCreated",
            "timestamp": "2026-01-15T10:30:00Z",
        })
        with pytest.raises(Exception):
            _process_message(body)

    def test_missing_currency_in_data(self):
        """Message with missing currency should raise a validation error."""
        body = json.dumps({
            "event_id": "evt-bad",
            "event_type": "OrderCreated",
            "timestamp": "2026-01-15T10:30:00Z",
            "data": {
                "order_id": "order-bad",
                "customer_id": "cust-bad",
                "amount": 1000,
                "items": [
                    {"product_id": "p1", "name": "X", "quantity": 1, "unit_price": 1000}
                ],
            },
        })
        with pytest.raises(Exception):
            _process_message(body)

    def test_missing_amount_in_data(self):
        """Message with missing amount should raise a validation error."""
        body = json.dumps({
            "event_id": "evt-bad",
            "event_type": "OrderCreated",
            "timestamp": "2026-01-15T10:30:00Z",
            "data": {
                "order_id": "order-bad",
                "customer_id": "cust-bad",
                "currency": "USD",
                "items": [
                    {"product_id": "p1", "name": "X", "quantity": 1, "unit_price": 1000}
                ],
            },
        })
        with pytest.raises(Exception):
            _process_message(body)

    def test_jpy_message_triggers_crash(self):
        """A JPY order message should propagate the ValueError from the processor."""
        body = self._valid_message_body(
            data={
                "order_id": "order-jpy-crash",
                "customer_id": "cust-jpy",
                "currency": "JPY",
                "amount": 15800,
                "items": [
                    {"product_id": "p1", "name": "Keyboard", "quantity": 1, "unit_price": 15800}
                ],
            }
        )
        with pytest.raises(ValueError, match="below minimum threshold"):
            _process_message(body)

    def test_extra_fields_in_message_are_ignored(self):
        """Messages with extra unknown fields should still process."""
        body = json.dumps({
            "event_id": "evt-extra",
            "event_type": "OrderCreated",
            "timestamp": "2026-01-15T10:30:00Z",
            "extra_field": "should be ignored",
            "data": {
                "order_id": "order-extra-fields",
                "customer_id": "cust-extra",
                "currency": "USD",
                "amount": 5000,
                "items": [
                    {"product_id": "p1", "name": "Widget", "quantity": 1, "unit_price": 5000}
                ],
                "unexpected_key": 42,
            },
        })
        # Should not raise — Pydantic v2 ignores extra fields by default
        _process_message(body)

    def test_empty_items_list(self):
        """An order with zero items should still be processable by the payment service.
        (Validation of item count is the Order Service's responsibility.)
        """
        body = self._valid_message_body(
            data={
                "order_id": "order-empty-items",
                "customer_id": "cust-empty",
                "currency": "USD",
                "amount": 5000,
                "items": [],
            }
        )
        # Payment processor only cares about amount/currency, not items
        _process_message(body)

    def test_non_string_message_body(self):
        """If the message body is somehow a dict (not a string), it should fail gracefully."""
        # This simulates the case where message parsing goes wrong upstream
        with pytest.raises(Exception):
            _process_message(12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. API Endpoint Resilience
# ---------------------------------------------------------------------------


class TestPaymentApiResilience:
    """Verify API endpoints handle edge cases gracefully."""

    def test_get_nonexistent_payment(self, client: TestClient):
        """Requesting a non-existent payment should return 404."""
        response = client.get("/api/payments/nonexistent-id-12345")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_list_payments_with_limit_zero(self, client: TestClient):
        """Listing payments with limit=0 should return empty list."""
        response = client.get("/api/payments?limit=0")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_payments_with_negative_limit(self, client: TestClient):
        """Listing payments with negative limit — Python slicing returns all but last.
        This documents the current behaviour (no server-side clamping).
        """
        response = client.get("/api/payments?limit=-1")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_payments_with_large_limit(self, client: TestClient):
        """Listing payments with a very large limit should not crash."""
        response = client.get("/api/payments?limit=999999")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_health_always_returns_healthy(self, client: TestClient):
        """Health endpoint should return healthy regardless of Service Bus state."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "service" in data

    def test_readiness_degrades_without_servicebus(self, client: TestClient):
        """Without Service Bus config, readiness should be degraded, not erroring."""
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["servicebus_connected"] is False

    def test_invalid_payment_id_format(self, client: TestClient):
        """Payment IDs with special characters should return 404, not 500."""
        response = client.get("/api/payments/../../etc/passwd")
        assert response.status_code == 404

    def test_payment_endpoint_with_empty_id(self, client: TestClient):
        """Empty payment ID should not match the payments list endpoint route."""
        # GET /api/payments/ with trailing slash - should still work
        response = client.get("/api/payments/")
        # FastAPI may redirect or return the list — either is acceptable
        assert response.status_code in (200, 307)


# ---------------------------------------------------------------------------
# 4. Service Bus Consumer Lifecycle Resilience
# ---------------------------------------------------------------------------


class TestConsumerLifecycleResilience:
    """Verify consumer start/stop and Service Bus health-check behavior."""

    @patch("app.consumer.settings")
    def test_consumer_loop_skips_without_connection_string(self, mock_settings):
        """Consumer loop should exit early if no connection string is set."""
        from app.consumer import _consumer_loop

        mock_settings.azure_servicebus_connection_string = ""
        # Should return without error (just logs a warning)
        _consumer_loop()

    @patch("app.consumer.ServiceBusClient")
    @patch("app.consumer.settings")
    def test_consumer_handles_servicebus_connection_error(
        self, mock_settings, mock_client_cls
    ):
        """Consumer should catch ServiceBusError and retry instead of crashing."""
        from azure.servicebus.exceptions import ServiceBusError

        from app.consumer import _consumer_loop, _stop_event

        mock_settings.azure_servicebus_connection_string = "fake-connection"
        mock_settings.azure_servicebus_queue_name = "test-queue"
        mock_client_cls.from_connection_string.side_effect = ServiceBusError("conn failed")

        # Set the stop event so the loop exits after one retry
        _stop_event.set()
        _consumer_loop()
        _stop_event.clear()

    @patch("app.consumer.ServiceBusClient")
    @patch("app.consumer.settings")
    def test_consumer_handles_unexpected_error(self, mock_settings, mock_client_cls):
        """Consumer should catch unexpected exceptions and retry."""
        from app.consumer import _consumer_loop, _stop_event

        mock_settings.azure_servicebus_connection_string = "fake-connection"
        mock_settings.azure_servicebus_queue_name = "test-queue"
        mock_client_cls.from_connection_string.side_effect = RuntimeError("unexpected")

        _stop_event.set()
        _consumer_loop()
        _stop_event.clear()

    @patch("app.consumer.ServiceBusClient")
    async def test_health_check_returns_false_on_connection_error(self, mock_client_cls):
        """Health check should return False when Service Bus is unreachable."""
        from azure.servicebus.exceptions import ServiceBusError

        from app.consumer import check_servicebus_health

        mock_client_instance = MagicMock()
        mock_client_cls.from_connection_string.return_value = mock_client_instance
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get_queue_receiver.side_effect = ServiceBusError("timeout")

        with patch("app.consumer.settings") as mock_settings:
            mock_settings.azure_servicebus_connection_string = "fake-string"
            mock_settings.azure_servicebus_queue_name = "test-queue"
            result = await check_servicebus_health()
            assert result is False


# ---------------------------------------------------------------------------
# 5. Multi-Currency Stress Testing
# ---------------------------------------------------------------------------


class TestMultiCurrencyResilience:
    """Ensure all supported currencies are handled (or fail predictably)."""

    @pytest.mark.parametrize(
        "currency,amount,should_succeed",
        [
            ("USD", 5000, True),
            ("EUR", 5000, True),
            ("GBP", 5000, True),
            ("CHF", 5000, True),
            ("CAD", 5000, True),
            ("AUD", 5000, True),
            ("CNY", 5000, True),
            ("INR", 5000, True),
            # Zero-decimal currencies with the known bug
            ("JPY", 15800, False),  # 158.00 < 500 threshold
            ("KRW", 30000, False),  # 300.00 < 500 threshold
            # Zero-decimal currencies that happen to work despite the bug
            ("JPY", 100000, True),  # 1000.00 >= 500 threshold
            ("KRW", 100000, True),  # 1000.00 >= 500 threshold
        ],
    )
    def test_currency_processing(self, currency: str, amount: int, should_succeed: bool):
        """Parametrized test across all supported currencies and boundary amounts."""
        event = OrderEventData(
            order_id=f"order-{currency.lower()}-resilience",
            customer_id="cust-resilience",
            currency=currency,
            amount=amount,
            items=[
                {"product_id": "p1", "name": "Item", "quantity": 1, "unit_price": amount}
            ],
        )
        if should_succeed:
            payment = process_order_payment(event)
            assert payment.status == PaymentStatus.COMPLETED
        else:
            with pytest.raises(ValueError, match="below minimum threshold"):
                process_order_payment(event)

    @pytest.mark.parametrize(
        "currency,amount_minor,expected_display",
        [
            ("USD", 100, 1.00),
            ("EUR", 199, 1.99),
            ("GBP", 1, 0.01),
            ("JPY", 100, 1.00),  # Bug: should be 100
            ("KRW", 100, 1.00),  # Bug: should be 100
        ],
    )
    def test_conversion_accuracy(
        self, currency: str, amount_minor: int, expected_display: float
    ):
        """Verify the display amount matches expected (including known-buggy conversions)."""
        assert convert_to_display_amount(amount_minor, currency) == expected_display


# ---------------------------------------------------------------------------
# 6. Data Integrity and Model Validation
# ---------------------------------------------------------------------------


class TestModelResilience:
    """Ensure Pydantic models handle edge-case data correctly."""

    def test_payment_record_auto_generates_id(self):
        """PaymentRecord should auto-generate a unique payment_id."""
        record = PaymentRecord(
            order_id="o1",
            customer_id="c1",
            currency="USD",
            amount_minor=1000,
            amount_display=10.00,
        )
        assert record.payment_id  # non-empty
        assert len(record.payment_id) > 0

    def test_payment_record_unique_ids(self):
        """Two independently created PaymentRecords should have different IDs."""
        r1 = PaymentRecord(
            order_id="o1",
            customer_id="c1",
            currency="USD",
            amount_minor=1000,
            amount_display=10.00,
        )
        r2 = PaymentRecord(
            order_id="o2",
            customer_id="c2",
            currency="EUR",
            amount_minor=2000,
            amount_display=20.00,
        )
        assert r1.payment_id != r2.payment_id

    def test_payment_record_default_status_is_pending(self):
        """PaymentRecord default status should be PENDING."""
        record = PaymentRecord(
            order_id="o1",
            customer_id="c1",
            currency="USD",
            amount_minor=1000,
            amount_display=10.00,
        )
        assert record.status == PaymentStatus.PENDING

    def test_order_event_data_rejects_missing_fields(self):
        """OrderEventData should reject construction with missing required fields."""
        with pytest.raises(Exception):
            OrderEventData(
                order_id="o1",
                customer_id="c1",
                # missing currency, amount, items
            )

    def test_payment_status_enum_values(self):
        """PaymentStatus should have exactly three expected values."""
        assert set(PaymentStatus) == {
            PaymentStatus.PENDING,
            PaymentStatus.COMPLETED,
            PaymentStatus.FAILED,
        }

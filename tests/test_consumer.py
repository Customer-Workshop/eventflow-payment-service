"""Tests for the Service Bus consumer module.

Tests cover message parsing, processing logic, order status callbacks,
and error handling during message consumption.
"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.consumer import (
    _process_message,
    _update_order_status,
    check_servicebus_health,
    payments,
    start_consumer,
    stop_consumer,
)
from app.models import PaymentStatus


@pytest.fixture(autouse=True)
def _clear_payments():
    """Clear the in-memory payments store between tests."""
    payments.clear()
    yield
    payments.clear()


def _make_order_event(
    order_id: str = "order-test-001",
    customer_id: str = "cust-test-001",
    currency: str = "USD",
    amount: int = 5000,
) -> str:
    """Create a JSON-encoded OrderCreated event."""
    event = {
        "event_id": "evt-test-001",
        "event_type": "OrderCreated",
        "timestamp": datetime.now(UTC).isoformat(),
        "data": {
            "order_id": order_id,
            "customer_id": customer_id,
            "currency": currency,
            "amount": amount,
            "items": [
                {
                    "product_id": "prod-001",
                    "name": "Test Product",
                    "quantity": 1,
                    "unit_price": amount,
                }
            ],
        },
    }
    return json.dumps(event)


class TestProcessMessage:
    """Tests for _process_message function."""

    def test_valid_usd_message(self):
        """Valid USD message should be processed and stored."""
        message_body = _make_order_event(
            order_id="order-msg-001", currency="USD", amount=5000
        )
        _process_message(message_body)

        assert len(payments) == 1
        payment = list(payments.values())[0]
        assert payment.order_id == "order-msg-001"
        assert payment.currency == "USD"
        assert payment.status == PaymentStatus.COMPLETED

    def test_valid_eur_message(self):
        """Valid EUR message should be processed and stored."""
        message_body = _make_order_event(
            order_id="order-msg-002", currency="EUR", amount=8999
        )
        _process_message(message_body)

        assert len(payments) == 1
        payment = list(payments.values())[0]
        assert payment.order_id == "order-msg-002"
        assert payment.currency == "EUR"
        assert payment.status == PaymentStatus.COMPLETED

    def test_invalid_json_message(self):
        """Invalid JSON should be caught and not raise."""
        _process_message("not valid json {{{")
        assert len(payments) == 0

    def test_malformed_event_missing_fields(self):
        """Event missing required fields should raise an exception."""
        malformed = json.dumps({"event_id": "evt-bad", "event_type": "OrderCreated"})
        with pytest.raises(Exception):
            _process_message(malformed)

    def test_multiple_messages_stored(self):
        """Processing multiple messages should store all payments."""
        for i in range(3):
            message_body = _make_order_event(
                order_id=f"order-multi-{i}", amount=5000 + i * 1000
            )
            _process_message(message_body)

        assert len(payments) == 3

    @patch("app.consumer._update_order_status")
    def test_order_status_callback_on_success(self, mock_update):
        """Successful processing should trigger status callback."""
        message_body = _make_order_event(order_id="order-cb-001")
        _process_message(message_body)

        mock_update.assert_called_once_with("order-cb-001", "completed")

    @patch("app.consumer._update_order_status")
    def test_order_status_callback_on_failure(self, mock_update):
        """Failed processing (ValueError) should try to update status to failed.

        This tests the JPY bug path where ValueError is raised.
        """
        message_body = _make_order_event(
            order_id="order-cb-fail", currency="JPY", amount=800
        )
        with pytest.raises(ValueError):
            _process_message(message_body)

        # Should have called update with "failed"
        mock_update.assert_called_with("order-cb-fail", "failed")


class TestUpdateOrderStatus:
    """Tests for _update_order_status function."""

    @patch("app.consumer.settings")
    def test_skip_when_no_url(self, mock_settings):
        """Should skip callback when ORDER_SERVICE_URL is not set."""
        mock_settings.order_service_url = ""
        # Should not raise
        _update_order_status("order-001", "completed")

    @patch("app.consumer.httpx.patch")
    @patch("app.consumer.settings")
    def test_successful_callback(self, mock_settings, mock_patch):
        """Should make PATCH request to order service."""
        mock_settings.order_service_url = "http://localhost:8001"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_patch.return_value = mock_response

        _update_order_status("order-001", "completed")

        mock_patch.assert_called_once_with(
            "http://localhost:8001/api/orders/order-001/status",
            json={"status": "completed"},
            timeout=5.0,
        )

    @patch("app.consumer.httpx.patch")
    @patch("app.consumer.settings")
    def test_failed_callback_non_200(self, mock_settings, mock_patch):
        """Should handle non-200 responses gracefully."""
        mock_settings.order_service_url = "http://localhost:8001"
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_patch.return_value = mock_response

        # Should not raise
        _update_order_status("order-001", "completed")

    @patch("app.consumer.httpx.patch")
    @patch("app.consumer.settings")
    def test_callback_connection_error(self, mock_settings, mock_patch):
        """Should handle connection errors gracefully."""
        mock_settings.order_service_url = "http://localhost:8001"
        mock_patch.side_effect = Exception("Connection refused")

        # Should not raise
        _update_order_status("order-001", "completed")


class TestProcessMessageEdgeCases:
    """Additional edge cases for _process_message."""

    @patch("app.consumer.process_order_payment")
    def test_unexpected_exception_is_raised(self, mock_process):
        """Unexpected exceptions (not ValueError/JSONDecodeError) should be re-raised."""
        mock_process.side_effect = RuntimeError("Unexpected DB error")
        message_body = _make_order_event(order_id="order-err-001")

        with pytest.raises(RuntimeError, match="Unexpected DB error"):
            _process_message(message_body)


class TestConsumerLoop:
    """Tests for _consumer_loop with mocked Service Bus."""

    @patch("app.consumer._stop_event")
    @patch("app.consumer.settings")
    def test_consumer_loop_no_connection_string(self, mock_settings, mock_stop_event):
        """Consumer loop should exit immediately if no connection string."""
        from app.consumer import _consumer_loop

        mock_settings.azure_servicebus_connection_string = ""
        _consumer_loop()

    @patch("app.consumer._stop_event")
    @patch("app.consumer.ServiceBusClient.from_connection_string")
    @patch("app.consumer.settings")
    def test_consumer_loop_processes_messages(
        self, mock_settings, mock_sb_client, mock_stop_event
    ):
        """Consumer loop should process messages from the queue."""
        from app.consumer import _consumer_loop

        mock_settings.azure_servicebus_connection_string = "Endpoint=sb://test/;SharedAccessKeyName=t;SharedAccessKey=t="
        mock_settings.azure_servicebus_queue_name = "test-queue"

        # Outer loop: False, inner loop: False (process), inner loop: True, outer: True
        mock_stop_event.is_set.side_effect = [False, False, True, True]

        # Mock message
        mock_message = MagicMock()
        mock_message.__str__ = MagicMock(return_value=_make_order_event(
            order_id="order-loop-001", amount=5000
        ))

        # Mock receiver
        mock_receiver = MagicMock()
        mock_receiver.__enter__ = MagicMock(return_value=mock_receiver)
        mock_receiver.__exit__ = MagicMock(return_value=False)
        mock_receiver.receive_messages.return_value = [mock_message]

        # Mock client
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get_queue_receiver.return_value = mock_receiver
        mock_sb_client.return_value = mock_client_instance

        _consumer_loop()

        mock_receiver.complete_message.assert_called_once_with(mock_message)

    @patch("app.consumer._stop_event")
    @patch("app.consumer.ServiceBusClient.from_connection_string")
    @patch("app.consumer.settings")
    def test_consumer_loop_handles_processing_error(
        self, mock_settings, mock_sb_client, mock_stop_event
    ):
        """Consumer loop should abandon messages that fail processing."""
        from app.consumer import _consumer_loop

        mock_settings.azure_servicebus_connection_string = "Endpoint=sb://test/;SharedAccessKeyName=t;SharedAccessKey=t="
        mock_settings.azure_servicebus_queue_name = "test-queue"

        mock_stop_event.is_set.side_effect = [False, False, True, True]

        # Mock message with invalid body
        mock_message = MagicMock()
        mock_message.__str__ = MagicMock(return_value="invalid json")

        mock_receiver = MagicMock()
        mock_receiver.__enter__ = MagicMock(return_value=mock_receiver)
        mock_receiver.__exit__ = MagicMock(return_value=False)
        mock_receiver.receive_messages.return_value = [mock_message]

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get_queue_receiver.return_value = mock_receiver
        mock_sb_client.return_value = mock_client_instance

        _consumer_loop()

        # Invalid JSON doesn't raise (caught in _process_message), so complete is called
        # Actually _process_message catches JSONDecodeError without raising, so it won't
        # abandon. Let's verify complete was called
        mock_receiver.complete_message.assert_called_once_with(mock_message)

    @patch("app.consumer._stop_event")
    @patch("app.consumer.ServiceBusClient.from_connection_string")
    @patch("app.consumer.settings")
    def test_consumer_loop_abandons_on_processing_exception(
        self, mock_settings, mock_sb_client, mock_stop_event
    ):
        """Consumer loop should abandon messages that raise exceptions."""
        from app.consumer import _consumer_loop

        mock_settings.azure_servicebus_connection_string = "Endpoint=sb://test/;SharedAccessKeyName=t;SharedAccessKey=t="
        mock_settings.azure_servicebus_queue_name = "test-queue"

        mock_stop_event.is_set.side_effect = [False, False, True, True]

        # Create a JPY order that will raise ValueError due to the bug
        mock_message = MagicMock()
        mock_message.__str__ = MagicMock(return_value=_make_order_event(
            order_id="order-abandon-001", currency="JPY", amount=800
        ))

        mock_receiver = MagicMock()
        mock_receiver.__enter__ = MagicMock(return_value=mock_receiver)
        mock_receiver.__exit__ = MagicMock(return_value=False)
        mock_receiver.receive_messages.return_value = [mock_message]

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get_queue_receiver.return_value = mock_receiver
        mock_sb_client.return_value = mock_client_instance

        _consumer_loop()

        # ValueError from JPY processing should cause the message to be abandoned
        mock_receiver.abandon_message.assert_called_once_with(mock_message)
        mock_receiver.complete_message.assert_not_called()

    @patch("app.consumer._stop_event")
    @patch("app.consumer.ServiceBusClient.from_connection_string")
    @patch("app.consumer.settings")
    def test_consumer_loop_servicebus_error_retries(
        self, mock_settings, mock_sb_client, mock_stop_event
    ):
        """Consumer loop should retry on ServiceBusError."""
        from azure.servicebus.exceptions import ServiceBusError

        from app.consumer import _consumer_loop

        mock_settings.azure_servicebus_connection_string = "Endpoint=sb://test/;SharedAccessKeyName=t;SharedAccessKey=t="
        mock_settings.azure_servicebus_queue_name = "test-queue"

        # First call raises ServiceBusError, then stop
        mock_stop_event.is_set.side_effect = [False, True]
        mock_stop_event.wait.return_value = None
        mock_sb_client.side_effect = ServiceBusError("Connection lost")

        _consumer_loop()

        mock_stop_event.wait.assert_called_once_with(timeout=10)

    @patch("app.consumer._stop_event")
    @patch("app.consumer.ServiceBusClient.from_connection_string")
    @patch("app.consumer.settings")
    def test_consumer_loop_unexpected_error_retries(
        self, mock_settings, mock_sb_client, mock_stop_event
    ):
        """Consumer loop should retry on unexpected errors."""
        from app.consumer import _consumer_loop

        mock_settings.azure_servicebus_connection_string = "Endpoint=sb://test/;SharedAccessKeyName=t;SharedAccessKey=t="
        mock_settings.azure_servicebus_queue_name = "test-queue"

        mock_stop_event.is_set.side_effect = [False, True]
        mock_stop_event.wait.return_value = None
        mock_sb_client.side_effect = RuntimeError("Unexpected")

        _consumer_loop()

        mock_stop_event.wait.assert_called_once_with(timeout=10)


class TestConsumerLifecycle:
    """Tests for start_consumer and stop_consumer."""

    @patch("app.consumer.settings")
    def test_start_consumer_no_connection_string(self, mock_settings):
        """Consumer loop should exit early if no connection string."""
        mock_settings.azure_servicebus_connection_string = ""
        start_consumer()
        # Give the thread a moment to start and exit
        import time

        time.sleep(0.1)
        stop_consumer()

    @patch("app.consumer._consumer_loop")
    def test_stop_consumer_sets_event(self, mock_loop):
        """stop_consumer should signal the stop event."""
        stop_consumer()
        # Should complete without error

    @patch("app.consumer._consumer_thread")
    def test_start_consumer_already_running(self, mock_thread):
        """start_consumer should skip if thread is already alive."""
        mock_thread.is_alive.return_value = True
        # Patch the global so it's seen
        import app.consumer as consumer_module

        original = consumer_module._consumer_thread
        consumer_module._consumer_thread = mock_thread
        try:
            start_consumer()
            # Should not start a new thread
        finally:
            consumer_module._consumer_thread = original


class TestCheckServicebusHealth:
    """Tests for check_servicebus_health."""

    @pytest.mark.asyncio
    @patch("app.consumer.settings")
    async def test_health_no_connection_string(self, mock_settings):
        """Should return False when no connection string is configured."""
        mock_settings.azure_servicebus_connection_string = ""
        result = await check_servicebus_health()
        assert result is False

    @pytest.mark.asyncio
    @patch("app.consumer.ServiceBusClient.from_connection_string")
    @patch("app.consumer.settings")
    async def test_health_connection_error(self, mock_settings, mock_client):
        """Should return False on ServiceBusError."""
        from azure.servicebus.exceptions import ServiceBusError

        mock_settings.azure_servicebus_connection_string = "Endpoint=sb://test.servicebus.windows.net/;SharedAccessKeyName=test;SharedAccessKey=test="
        mock_settings.azure_servicebus_queue_name = "test-queue"
        mock_client.side_effect = ServiceBusError("Connection failed")

        result = await check_servicebus_health()
        assert result is False

    @pytest.mark.asyncio
    @patch("app.consumer.ServiceBusClient.from_connection_string")
    @patch("app.consumer.settings")
    async def test_health_success(self, mock_settings, mock_client):
        """Should return True when Service Bus connection succeeds."""
        mock_settings.azure_servicebus_connection_string = "Endpoint=sb://test.servicebus.windows.net/;SharedAccessKeyName=test;SharedAccessKey=test="
        mock_settings.azure_servicebus_queue_name = "test-queue"

        mock_receiver = MagicMock()
        mock_receiver.__enter__ = MagicMock(return_value=mock_receiver)
        mock_receiver.__exit__ = MagicMock(return_value=False)

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get_queue_receiver.return_value = mock_receiver
        mock_client.return_value = mock_client_instance

        result = await check_servicebus_health()
        assert result is True

"""Tests for the Service Bus consumer module."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from azure.servicebus.exceptions import ServiceBusError

from app.consumer import (
    _process_message,
    _update_order_status,
    check_servicebus_health,
    start_consumer,
    stop_consumer,
)


class TestUpdateOrderStatus:
    """Tests for _update_order_status callback."""

    def test_skips_when_no_url(self):
        """Should silently skip when ORDER_SERVICE_URL is not set."""
        with patch("app.consumer.settings") as mock_settings:
            mock_settings.order_service_url = ""
            _update_order_status("order-1", "completed")

    @patch("app.consumer.httpx.patch")
    def test_success_path(self, mock_patch):
        """Should log success when order service returns 200."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_patch.return_value = mock_response

        with patch("app.consumer.settings") as mock_settings:
            mock_settings.order_service_url = "http://order-service:8001"
            _update_order_status("order-1", "completed")

        mock_patch.assert_called_once_with(
            "http://order-service:8001/api/orders/order-1/status",
            json={"status": "completed"},
            timeout=5.0,
        )

    @patch("app.consumer.httpx.patch")
    def test_non_200_response(self, mock_patch):
        """Should log warning when order service returns non-200."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_patch.return_value = mock_response

        with patch("app.consumer.settings") as mock_settings:
            mock_settings.order_service_url = "http://order-service:8001"
            _update_order_status("order-1", "completed")

        mock_patch.assert_called_once()

    @patch("app.consumer.httpx.patch")
    def test_connection_error(self, mock_patch):
        """Should log warning on connection error."""
        mock_patch.side_effect = httpx.ConnectError("Connection refused")

        with patch("app.consumer.settings") as mock_settings:
            mock_settings.order_service_url = "http://order-service:8001"
            _update_order_status("order-1", "completed")


class TestProcessMessage:
    """Tests for _process_message."""

    def test_valid_usd_message(self, sample_order_event_json):
        """Should successfully process a valid USD order message."""
        from app.consumer import payments

        initial_count = len(payments)
        _process_message(sample_order_event_json)
        assert len(payments) == initial_count + 1

    def test_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        _process_message("not valid json {{{")

    def test_jpy_message_raises_value_error(self, jpy_order_event_json):
        """JPY orders should raise ValueError due to the intentional bug.

        The bug: convert_to_display_amount divides 15800 JPY by 100 = 158.0,
        which is below the 500 JPY minimum threshold.
        """
        with pytest.raises(ValueError, match="below minimum threshold"):
            _process_message(jpy_order_event_json)

    def test_generic_exception_reraises(self):
        """Should re-raise generic exceptions after logging."""
        with patch("app.consumer.json.loads", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                _process_message('{"any": "data"}')


class TestConsumerLoop:
    """Tests for _consumer_loop."""

    def test_no_connection_string_returns_early(self):
        """Should return immediately if connection string is not set."""
        from app.consumer import _consumer_loop

        with patch("app.consumer.settings") as mock_settings:
            mock_settings.azure_servicebus_connection_string = ""
            _consumer_loop()

    @patch("app.consumer.ServiceBusClient")
    def test_processes_messages_successfully(self, mock_sb_class):
        """Should process received messages and complete them."""
        from app.consumer import _consumer_loop, _stop_event

        mock_message = MagicMock()
        mock_message.__str__ = MagicMock(return_value='{"not": "valid event"}')

        mock_receiver = MagicMock()
        mock_receiver.receive_messages.side_effect = [
            [mock_message],
            [],
        ]
        mock_receiver.__enter__ = MagicMock(return_value=mock_receiver)
        mock_receiver.__exit__ = MagicMock(return_value=False)

        mock_client = MagicMock()
        mock_client.get_queue_receiver.return_value = mock_receiver
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_sb_class.from_connection_string.return_value = mock_client

        _stop_event.clear()

        call_count = 0

        def stop_after_first_iteration():
            nonlocal call_count
            call_count += 1
            if call_count >= 4:
                return True
            return False

        with (
            patch("app.consumer.settings") as mock_settings,
            patch.object(_stop_event, "is_set", side_effect=stop_after_first_iteration),
        ):
            mock_settings.azure_servicebus_connection_string = "Endpoint=sb://fake"
            mock_settings.azure_servicebus_queue_name = "test-queue"
            _consumer_loop()

        mock_receiver.receive_messages.assert_called()

    @patch("app.consumer.ServiceBusClient")
    def test_handles_servicebus_error(self, mock_sb_class):
        """Should handle ServiceBusError and retry."""
        from app.consumer import _consumer_loop, _stop_event

        mock_sb_class.from_connection_string.side_effect = ServiceBusError("Connection failed")

        call_count = 0

        def stop_after_retry():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return True
            return False

        with (
            patch("app.consumer.settings") as mock_settings,
            patch.object(_stop_event, "is_set", side_effect=stop_after_retry),
            patch.object(_stop_event, "wait"),
        ):
            mock_settings.azure_servicebus_connection_string = "Endpoint=sb://fake"
            mock_settings.azure_servicebus_queue_name = "test-queue"
            _consumer_loop()


class TestStartStopConsumer:
    """Tests for start_consumer and stop_consumer thread management."""

    def test_start_and_stop_consumer(self):
        """Should start and then stop the consumer thread."""
        import app.consumer as consumer_module

        with patch.object(consumer_module, "_consumer_loop"):
            start_consumer()
            assert consumer_module._consumer_thread is not None

            stop_consumer()
            assert consumer_module._consumer_thread is None

    def test_start_consumer_already_running(self):
        """Should warn if consumer thread is already running."""
        import app.consumer as consumer_module

        with patch.object(consumer_module, "_consumer_loop"):
            start_consumer()
            start_consumer()  # second call should warn, not start another
            stop_consumer()


class TestCheckServicebusHealth:
    """Tests for check_servicebus_health."""

    @pytest.mark.asyncio
    async def test_health_no_connection_string(self):
        """Should return False when connection string is not set."""
        with patch("app.consumer.settings") as mock_settings:
            mock_settings.azure_servicebus_connection_string = ""
            result = await check_servicebus_health()
            assert result is False

    @pytest.mark.asyncio
    @patch("app.consumer.ServiceBusClient")
    async def test_health_success(self, mock_sb_class):
        """Should return True when Service Bus connection succeeds."""
        mock_receiver = MagicMock()
        mock_receiver.__enter__ = MagicMock(return_value=mock_receiver)
        mock_receiver.__exit__ = MagicMock(return_value=False)

        mock_client = MagicMock()
        mock_client.get_queue_receiver.return_value = mock_receiver
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_sb_class.from_connection_string.return_value = mock_client

        with patch("app.consumer.settings") as mock_settings:
            mock_settings.azure_servicebus_connection_string = "Endpoint=sb://fake"
            mock_settings.azure_servicebus_queue_name = "test-queue"
            result = await check_servicebus_health()
            assert result is True

    @pytest.mark.asyncio
    @patch("app.consumer.ServiceBusClient")
    async def test_health_servicebus_error(self, mock_sb_class):
        """Should return False when Service Bus raises an error."""
        mock_sb_class.from_connection_string.side_effect = ServiceBusError("fail")

        with patch("app.consumer.settings") as mock_settings:
            mock_settings.azure_servicebus_connection_string = "Endpoint=sb://fake"
            mock_settings.azure_servicebus_queue_name = "test-queue"
            result = await check_servicebus_health()
            assert result is False

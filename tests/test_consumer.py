"""Tests for the Service Bus consumer module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.consumer import _process_message, _update_order_status, start_consumer, stop_consumer
from app.models import PaymentStatus


class TestProcessMessage:
    """Tests for _process_message()."""

    @patch("app.consumer._update_order_status")
    @patch("app.consumer.process_order_payment")
    def test_successful_message_processing(self, mock_process, mock_update):
        """Valid JSON message should be processed and stored."""
        from app.consumer import payments

        mock_payment = MagicMock()
        mock_payment.payment_id = "pay-001"
        mock_payment.order_id = "order-001"
        mock_payment.status = PaymentStatus.COMPLETED
        mock_process.return_value = mock_payment

        message = json.dumps(
            {
                "event_id": "evt-001",
                "event_type": "OrderCreated",
                "timestamp": "2025-01-01T00:00:00Z",
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
        )

        _process_message(message)

        mock_process.assert_called_once()
        assert "pay-001" in payments
        mock_update.assert_called_once_with("order-001", "completed")

        # Cleanup
        payments.pop("pay-001", None)

    def test_invalid_json_does_not_crash(self):
        """Invalid JSON should log error but not raise."""
        _process_message("not valid json {{{")

    @patch("app.consumer._update_order_status")
    @patch(
        "app.consumer.process_order_payment",
        side_effect=ValueError("Amount 0.10 USD is below minimum threshold 0.50 USD"),
    )
    def test_value_error_from_processor_raises(self, mock_process, mock_update):
        """ValueError from processor should be re-raised after attempting status update."""
        message = json.dumps(
            {
                "event_id": "evt-002",
                "event_type": "OrderCreated",
                "timestamp": "2025-01-01T00:00:00Z",
                "data": {
                    "order_id": "order-002",
                    "customer_id": "cust-002",
                    "currency": "USD",
                    "amount": 10,
                    "items": [
                        {
                            "product_id": "p1",
                            "name": "Tiny",
                            "quantity": 1,
                            "unit_price": 10,
                        }
                    ],
                },
            }
        )

        with pytest.raises(ValueError, match="below minimum threshold"):
            _process_message(message)

        mock_update.assert_called_once_with("order-002", "failed")


class TestUpdateOrderStatus:
    """Tests for _update_order_status()."""

    @patch("app.consumer.settings")
    def test_returns_early_when_url_not_set(self, mock_settings):
        """Should return early without making HTTP call when URL is not set."""
        mock_settings.order_service_url = ""
        with patch("app.consumer.httpx.patch") as mock_patch:
            _update_order_status("order-001", "completed")
            mock_patch.assert_not_called()

    @patch("app.consumer.settings")
    @patch("app.consumer.httpx.patch")
    def test_successful_http_patch(self, mock_patch, mock_settings):
        """Successful HTTP PATCH should log info."""
        mock_settings.order_service_url = "http://order-service:8001"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_patch.return_value = mock_response

        _update_order_status("order-001", "completed")

        mock_patch.assert_called_once_with(
            "http://order-service:8001/api/orders/order-001/status",
            json={"status": "completed"},
            timeout=5.0,
        )

    @patch("app.consumer.settings")
    @patch("app.consumer.httpx.patch")
    def test_failed_http_patch_non_200(self, mock_patch, mock_settings):
        """Non-200 response should log warning but not raise."""
        mock_settings.order_service_url = "http://order-service:8001"
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_patch.return_value = mock_response

        _update_order_status("order-001", "completed")

        mock_patch.assert_called_once()

    @patch("app.consumer.settings")
    @patch("app.consumer.httpx.patch", side_effect=Exception("Connection refused"))
    def test_http_patch_network_error(self, mock_patch, mock_settings):
        """Network error should be caught and logged, not raised."""
        mock_settings.order_service_url = "http://order-service:8001"

        _update_order_status("order-001", "completed")

        mock_patch.assert_called_once()


class TestStartStopConsumer:
    """Tests for start_consumer() and stop_consumer()."""

    @patch("app.consumer._consumer_loop")
    def test_start_consumer_already_running(self, mock_loop):
        """Starting consumer when already running should warn and return."""
        import app.consumer as consumer_mod

        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        original_thread = consumer_mod._consumer_thread
        consumer_mod._consumer_thread = mock_thread

        try:
            start_consumer()
            mock_loop.assert_not_called()
        finally:
            consumer_mod._consumer_thread = original_thread

    def test_stop_consumer_sets_event_and_joins(self):
        """stop_consumer should set the stop event and join the thread."""
        import app.consumer as consumer_mod

        mock_thread = MagicMock()
        original_thread = consumer_mod._consumer_thread
        consumer_mod._consumer_thread = mock_thread

        try:
            stop_consumer()
            assert consumer_mod._stop_event.is_set()
            mock_thread.join.assert_called_once_with(timeout=15)
            assert consumer_mod._consumer_thread is None
        finally:
            consumer_mod._stop_event.clear()
            consumer_mod._consumer_thread = original_thread

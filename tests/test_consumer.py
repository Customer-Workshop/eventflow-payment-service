"""Tests for the Service Bus consumer module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.consumer import _process_message, _update_order_status, payments


class TestProcessMessage:
    """Tests for _process_message handling of Service Bus messages."""

    @patch("app.consumer._update_order_status")
    @patch("app.consumer.process_order_payment")
    def test_valid_json_order_event(self, mock_process, mock_update):
        """A valid JSON OrderCreatedEvent should be processed and stored."""
        mock_payment = MagicMock()
        mock_payment.payment_id = "pay-001"
        mock_payment.order_id = "order-001"
        mock_payment.status.value = "completed"
        mock_process.return_value = mock_payment

        event = {
            "event_id": "evt-001",
            "event_type": "OrderCreated",
            "timestamp": "2025-01-01T00:00:00Z",
            "data": {
                "order_id": "order-001",
                "customer_id": "cust-001",
                "currency": "USD",
                "amount": 5000,
                "items": [
                    {"product_id": "p1", "name": "Item", "quantity": 1, "unit_price": 5000}
                ],
            },
        }
        _process_message(json.dumps(event))

        mock_process.assert_called_once()
        mock_update.assert_called_once_with("order-001", "completed")
        payments.pop("pay-001", None)

    def test_invalid_json_does_not_raise(self):
        """Invalid JSON should log an error but not raise."""
        _process_message("this is not valid json {{{")

    @patch("app.consumer._update_order_status")
    @patch("app.consumer.process_order_payment", side_effect=ValueError("below minimum threshold"))
    def test_value_error_is_reraised(self, mock_process, mock_update):
        """ValueError from process_order_payment should be logged and re-raised."""
        event = {
            "event_id": "evt-002",
            "event_type": "OrderCreated",
            "timestamp": "2025-01-01T00:00:00Z",
            "data": {
                "order_id": "order-002",
                "customer_id": "cust-002",
                "currency": "JPY",
                "amount": 15800,
                "items": [
                    {"product_id": "p1", "name": "Item", "quantity": 1, "unit_price": 15800}
                ],
            },
        }
        with pytest.raises(ValueError, match="below minimum threshold"):
            _process_message(json.dumps(event))

        mock_update.assert_called_once_with("order-002", "failed")


class TestUpdateOrderStatus:
    """Tests for _update_order_status HTTP callback."""

    @patch("app.consumer.settings")
    def test_no_order_service_url_returns_silently(self, mock_settings):
        """When ORDER_SERVICE_URL is not set, the function should return without error."""
        mock_settings.order_service_url = ""
        _update_order_status("order-001", "completed")

    @patch("app.consumer.httpx.patch")
    @patch("app.consumer.settings")
    def test_successful_http_response(self, mock_settings, mock_httpx_patch):
        """A successful HTTP response should log the status update."""
        mock_settings.order_service_url = "http://order-service:8001"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_httpx_patch.return_value = mock_response

        _update_order_status("order-001", "completed")

        mock_httpx_patch.assert_called_once_with(
            "http://order-service:8001/api/orders/order-001/status",
            json={"status": "completed"},
            timeout=5.0,
        )

    @patch("app.consumer.httpx.patch", side_effect=Exception("Connection refused"))
    @patch("app.consumer.settings")
    def test_http_failure_does_not_raise(self, mock_settings, mock_httpx_patch):
        """HTTP call failure should log a warning but not raise."""
        mock_settings.order_service_url = "http://order-service:8001"
        _update_order_status("order-001", "completed")

    @patch("app.consumer.httpx.patch")
    @patch("app.consumer.settings")
    def test_non_200_response_logs_warning(self, mock_settings, mock_httpx_patch):
        """Non-200 HTTP response should log a warning but not raise."""
        mock_settings.order_service_url = "http://order-service:8001"
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_httpx_patch.return_value = mock_response

        _update_order_status("order-001", "completed")

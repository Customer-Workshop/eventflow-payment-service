"""Tests for the Azure Service Bus consumer module."""

import json
import threading
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
    """Ensure the payments dict is clean for each test."""
    payments.clear()
    yield
    payments.clear()


@pytest.fixture(autouse=True)
def _reset_consumer_globals():
    """Reset consumer thread globals between tests."""
    import app.consumer as mod

    mod._consumer_thread = None
    mod._stop_event.clear()
    yield
    mod._stop_event.set()
    if mod._consumer_thread is not None and mod._consumer_thread.is_alive():
        mod._consumer_thread.join(timeout=2)
    mod._consumer_thread = None
    mod._stop_event.clear()


def _make_order_event_json(
    order_id: str = "order-001",
    customer_id: str = "cust-001",
    currency: str = "USD",
    amount: int = 5000,
) -> str:
    """Build a valid OrderCreatedEvent JSON string."""
    return json.dumps(
        {
            "event_id": "evt-001",
            "event_type": "OrderCreated",
            "timestamp": "2025-01-01T00:00:00Z",
            "data": {
                "order_id": order_id,
                "customer_id": customer_id,
                "currency": currency,
                "amount": amount,
                "items": [
                    {
                        "product_id": "prod-1",
                        "name": "Widget",
                        "quantity": 1,
                        "unit_price": amount,
                    }
                ],
            },
        }
    )


# ---------------------------------------------------------------------------
# _update_order_status
# ---------------------------------------------------------------------------
class TestUpdateOrderStatus:
    """Tests for _update_order_status."""

    def test_noop_when_url_not_set(self):
        """Does nothing when ORDER_SERVICE_URL is empty (default)."""
        with patch("app.consumer.settings") as mock_settings:
            mock_settings.order_service_url = ""
            _update_order_status("order-1", "completed")
            # No exception, no HTTP call

    def test_patch_request_on_success(self):
        """Makes PATCH request to order service on success."""
        with (
            patch("app.consumer.settings") as mock_settings,
            patch("app.consumer.httpx.patch") as mock_patch,
        ):
            mock_settings.order_service_url = "http://order-svc"
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_patch.return_value = mock_response

            _update_order_status("order-1", "completed")

            mock_patch.assert_called_once_with(
                "http://order-svc/api/orders/order-1/status",
                json={"status": "completed"},
                timeout=5.0,
            )

    def test_logs_warning_on_non_200(self):
        """Logs warning on non-200 response."""
        with (
            patch("app.consumer.settings") as mock_settings,
            patch("app.consumer.httpx.patch") as mock_patch,
            patch("app.consumer.logger") as mock_logger,
        ):
            mock_settings.order_service_url = "http://order-svc"
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_patch.return_value = mock_response

            _update_order_status("order-1", "completed")

            mock_logger.warning.assert_called()

    def test_handles_exception_when_unreachable(self):
        """Handles exception when order service is unreachable."""
        with (
            patch("app.consumer.settings") as mock_settings,
            patch("app.consumer.httpx.patch", side_effect=Exception("conn refused")),
            patch("app.consumer.logger") as mock_logger,
        ):
            mock_settings.order_service_url = "http://order-svc"

            _update_order_status("order-1", "completed")

            mock_logger.warning.assert_called()


# ---------------------------------------------------------------------------
# _process_message
# ---------------------------------------------------------------------------
class TestProcessMessage:
    """Tests for _process_message."""

    def test_valid_json_processes_payment(self):
        """Successfully parses valid JSON and processes payment."""
        body = _make_order_event_json()

        with patch("app.consumer._update_order_status") as mock_update:
            _process_message(body)

        assert len(payments) == 1
        record = list(payments.values())[0]
        assert record.order_id == "order-001"
        assert record.status == PaymentStatus.COMPLETED
        mock_update.assert_called_once_with("order-001", "completed")

    def test_invalid_json(self):
        """Handles invalid JSON gracefully (no exception propagated)."""
        _process_message("not-valid-json{{{")
        assert len(payments) == 0

    def test_value_error_propagates(self):
        """ValueError from processor propagates after updating order status."""
        body = _make_order_event_json(currency="JPY", amount=15800)

        with (
            patch("app.consumer._update_order_status") as mock_update,
            pytest.raises(ValueError),
        ):
            _process_message(body)

        mock_update.assert_called_with("order-001", "failed")

    def test_generic_exception_propagates(self):
        """Generic exceptions propagate."""
        body = _make_order_event_json()

        with (
            patch(
                "app.consumer.process_order_payment",
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(RuntimeError),
        ):
            _process_message(body)


# ---------------------------------------------------------------------------
# start_consumer / stop_consumer
# ---------------------------------------------------------------------------
class TestStartStopConsumer:
    """Tests for start_consumer and stop_consumer."""

    def test_start_consumer_creates_daemon_thread(self):
        """start_consumer starts a daemon thread."""
        with patch("app.consumer._consumer_loop"):
            start_consumer()

        import app.consumer as mod

        assert mod._consumer_thread is not None
        assert mod._consumer_thread.daemon is True
        assert mod._consumer_thread.name == "sb-consumer"

        mod._stop_event.set()
        mod._consumer_thread.join(timeout=2)

    def test_start_consumer_no_duplicate(self):
        """Does not start a second thread if one is already running."""
        sentinel = threading.Event()

        def _fake_loop():
            sentinel.wait(timeout=5)

        with patch("app.consumer._consumer_loop", side_effect=_fake_loop):
            start_consumer()
            start_consumer()

        import app.consumer as mod

        assert mod._consumer_thread is not None
        sentinel.set()
        mod._consumer_thread.join(timeout=2)

    def test_stop_consumer_sets_event_and_joins(self):
        """stop_consumer sets stop event and joins thread."""
        sentinel = threading.Event()

        def _fake_loop():
            sentinel.wait(timeout=5)

        with patch("app.consumer._consumer_loop", side_effect=_fake_loop):
            start_consumer()

        import app.consumer as mod

        assert mod._consumer_thread is not None
        sentinel.set()
        stop_consumer()
        assert mod._consumer_thread is None

    def test_stop_consumer_when_no_thread(self):
        """stop_consumer works fine when no thread is running."""
        stop_consumer()


# ---------------------------------------------------------------------------
# check_servicebus_health
# ---------------------------------------------------------------------------
class TestCheckServicebusHealth:
    """Tests for check_servicebus_health."""

    @pytest.mark.asyncio
    async def test_returns_false_when_connection_string_empty(self):
        """Returns False when connection string is empty."""
        with patch("app.consumer.settings") as mock_settings:
            mock_settings.azure_servicebus_connection_string = ""
            result = await check_servicebus_health()

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        """Returns True when Service Bus connection succeeds."""
        mock_receiver = MagicMock()
        mock_receiver.__enter__ = MagicMock(return_value=mock_receiver)
        mock_receiver.__exit__ = MagicMock(return_value=False)

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get_queue_receiver.return_value = mock_receiver

        with (
            patch("app.consumer.settings") as mock_settings,
            patch("app.consumer.ServiceBusClient") as mock_sb_cls,
        ):
            mock_settings.azure_servicebus_connection_string = "Endpoint=sb://fake"
            mock_settings.azure_servicebus_queue_name = "test-queue"
            mock_sb_cls.from_connection_string.return_value = mock_client_instance

            result = await check_servicebus_health()

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_servicebus_error(self):
        """Returns False when ServiceBusError occurs."""
        from azure.servicebus.exceptions import ServiceBusError

        with (
            patch("app.consumer.settings") as mock_settings,
            patch("app.consumer.ServiceBusClient") as mock_sb_cls,
        ):
            mock_settings.azure_servicebus_connection_string = "Endpoint=sb://fake"
            mock_sb_cls.from_connection_string.side_effect = ServiceBusError("fail")

            result = await check_servicebus_health()

        assert result is False

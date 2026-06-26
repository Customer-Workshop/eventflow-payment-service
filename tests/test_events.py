"""Tests for the payment event publisher."""

from unittest.mock import MagicMock, patch

from azure.servicebus.exceptions import ServiceBusError

from app.events import publish_payment_processed
from app.models import PaymentRecord, PaymentStatus


def _make_payment(**overrides) -> PaymentRecord:
    defaults = {
        "order_id": "order-001",
        "customer_id": "cust-001",
        "currency": "USD",
        "amount_minor": 10997,
        "amount_display": 109.97,
        "status": PaymentStatus.COMPLETED,
    }
    defaults.update(overrides)
    return PaymentRecord(**defaults)


class TestPublishPaymentProcessed:
    """Tests for publish_payment_processed."""

    def test_returns_false_when_no_connection_string(self):
        """Should return False when Service Bus is not configured."""
        with patch("app.events.settings") as mock_settings:
            mock_settings.azure_servicebus_connection_string = ""
            # Reset the cached client
            with patch("app.events._client", None):
                result = publish_payment_processed(_make_payment())
        assert result is False

    @patch("app.events._get_servicebus_client")
    def test_returns_false_when_client_is_none(self, mock_get_client):
        """Should return False when the client cannot be created."""
        mock_get_client.return_value = None
        result = publish_payment_processed(_make_payment())
        assert result is False

    @patch("app.events._get_servicebus_client")
    def test_publishes_completed_payment(self, mock_get_client):
        """Should publish a completed payment event successfully."""
        mock_client = MagicMock()
        mock_sender = MagicMock()
        mock_sender.__enter__ = MagicMock(return_value=mock_sender)
        mock_sender.__exit__ = MagicMock(return_value=False)
        mock_client.get_queue_sender.return_value = mock_sender
        mock_get_client.return_value = mock_client

        payment = _make_payment()
        result = publish_payment_processed(payment)

        assert result is True
        mock_sender.send_messages.assert_called_once()

    @patch("app.events._get_servicebus_client")
    def test_publishes_failed_payment(self, mock_get_client):
        """Should publish a failed payment event successfully."""
        mock_client = MagicMock()
        mock_sender = MagicMock()
        mock_sender.__enter__ = MagicMock(return_value=mock_sender)
        mock_sender.__exit__ = MagicMock(return_value=False)
        mock_client.get_queue_sender.return_value = mock_sender
        mock_get_client.return_value = mock_client

        payment = _make_payment(
            status=PaymentStatus.FAILED,
            error_message="Insufficient funds",
        )
        result = publish_payment_processed(payment)

        assert result is True
        mock_sender.send_messages.assert_called_once()

    @patch("app.events._get_servicebus_client")
    def test_returns_false_on_servicebus_error(self, mock_get_client):
        """Should catch ServiceBusError and return False."""
        mock_client = MagicMock()
        mock_sender = MagicMock()
        mock_sender.__enter__ = MagicMock(return_value=mock_sender)
        mock_sender.__exit__ = MagicMock(return_value=False)
        mock_sender.send_messages.side_effect = ServiceBusError("connection lost")
        mock_client.get_queue_sender.return_value = mock_sender
        mock_get_client.return_value = mock_client

        result = publish_payment_processed(_make_payment())
        assert result is False

    @patch("app.events._get_servicebus_client")
    def test_returns_false_on_unexpected_exception(self, mock_get_client):
        """Non-ServiceBusError exceptions must be caught to prevent duplicate payments."""
        mock_client = MagicMock()
        mock_sender = MagicMock()
        mock_sender.__enter__ = MagicMock(return_value=mock_sender)
        mock_sender.__exit__ = MagicMock(return_value=False)
        mock_sender.send_messages.side_effect = OSError("network unreachable")
        mock_client.get_queue_sender.return_value = mock_sender
        mock_get_client.return_value = mock_client

        result = publish_payment_processed(_make_payment())
        assert result is False

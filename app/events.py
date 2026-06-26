"""Azure Service Bus event publisher for payment outcomes."""

import json
import logging

from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.servicebus.exceptions import ServiceBusError

from app.config import settings
from app.models import PaymentRecord

logger = logging.getLogger(__name__)

_client: ServiceBusClient | None = None


def _get_servicebus_client() -> ServiceBusClient | None:
    """Get or create the Service Bus client singleton."""
    global _client
    if _client is None and settings.azure_servicebus_connection_string:
        try:
            _client = ServiceBusClient.from_connection_string(
                settings.azure_servicebus_connection_string
            )
            logger.info("Payment events: Service Bus client initialized")
        except Exception:
            logger.exception("Failed to initialize Service Bus client for payment events")
            _client = None
    return _client


def publish_payment_processed(payment: PaymentRecord) -> bool:
    """Publish a PaymentProcessed event to Azure Service Bus.

    Args:
        payment: The payment record to publish.

    Returns:
        True if the event was published successfully, False otherwise.
    """
    client = _get_servicebus_client()
    if client is None:
        logger.warning(
            "Service Bus client not available — payment event will not be published",
            extra={"payment_id": payment.payment_id},
        )
        return False

    try:
        sender = client.get_queue_sender(
            queue_name=settings.azure_servicebus_payment_queue_name,
        )
        message_body = json.dumps(
            {
                "event_type": "PaymentProcessed",
                "payment_id": payment.payment_id,
                "order_id": payment.order_id,
                "customer_id": payment.customer_id,
                "currency": payment.currency,
                "amount_minor": payment.amount_minor,
                "amount_display": payment.amount_display,
                "status": payment.status.value,
                "processed_at": payment.processed_at.isoformat(),
                "error_message": payment.error_message,
            },
            default=str,
        )
        message = ServiceBusMessage(
            body=message_body,
            content_type="application/json",
            subject="PaymentProcessed",
            application_properties={
                "event_type": "PaymentProcessed",
                "payment_id": payment.payment_id,
                "order_id": payment.order_id,
                "status": payment.status.value,
            },
        )

        with sender:
            sender.send_messages(message)

        logger.info(
            "Published PaymentProcessed event",
            extra={
                "payment_id": payment.payment_id,
                "order_id": payment.order_id,
                "status": payment.status.value,
            },
        )
        return True

    except ServiceBusError:
        logger.exception(
            "Failed to publish payment event to Service Bus",
            extra={"payment_id": payment.payment_id},
        )
        return False


def close_payment_publisher() -> None:
    """Close the Service Bus client used for publishing."""
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            logger.exception("Error closing payment publisher Service Bus client")
        finally:
            _client = None

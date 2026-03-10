"""Azure Service Bus consumer for order events."""

import json
import logging
import threading

import httpx
from azure.servicebus import ServiceBusClient
from azure.servicebus.exceptions import ServiceBusError

from app.config import settings
from app.models import OrderCreatedEvent, PaymentRecord
from app.processor import process_order_payment

logger = logging.getLogger(__name__)

# In-memory store for processed payments (demo purposes)
payments: dict[str, PaymentRecord] = {}

_consumer_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _update_order_status(order_id: str, status: str) -> None:
    """Callback to order service to update order status after payment processing."""
    if not settings.order_service_url:
        logger.debug("ORDER_SERVICE_URL not set — skipping status callback")
        return
    url = f"{settings.order_service_url}/api/orders/{order_id}/status"
    try:
        response = httpx.patch(url, json={"status": status}, timeout=5.0)
        if response.status_code == 200:
            logger.info("Order %s status updated to %s", order_id, status)
        else:
            logger.warning(
                "Failed to update order %s status: HTTP %d",
                order_id,
                response.status_code,
            )
    except Exception:
        logger.warning("Could not reach order service to update order %s", order_id)


def _process_message(message_body: str) -> None:
    """Parse and process a single Service Bus message.

    Args:
        message_body: JSON string of the OrderCreated event.
    """
    try:
        event_dict = json.loads(message_body)
        event = OrderCreatedEvent(**event_dict)

        logger.info(
            "Received OrderCreated event: order_id=%s, currency=%s, amount=%d",
            event.data.order_id,
            event.data.currency,
            event.data.amount,
        )

        # Process the payment
        payment = process_order_payment(event.data)
        payments[payment.payment_id] = payment

        logger.info(
            "Payment %s for order %s: status=%s",
            payment.payment_id,
            payment.order_id,
            payment.status.value,
        )

        # Callback to order service to update order status
        _update_order_status(event.data.order_id, payment.status.value)

    except json.JSONDecodeError:
        logger.exception("Failed to parse message body as JSON")
    except ValueError:
        logger.exception(
            "Payment processing failed — validation error"
        )
        # Try to update order status to failed before re-raising
        try:
            _update_order_status(event.data.order_id, "failed")
        except Exception:
            logger.warning("Could not update order status to failed")
        raise
    except Exception:
        logger.exception("Unexpected error processing message")
        raise


def _consumer_loop() -> None:
    """Background loop that consumes messages from Service Bus."""
    if not settings.azure_servicebus_connection_string:
        logger.warning("Service Bus connection string not set — consumer not started")
        return

    logger.info(
        "Starting Service Bus consumer on queue: %s",
        settings.azure_servicebus_queue_name,
    )

    while not _stop_event.is_set():
        try:
            client = ServiceBusClient.from_connection_string(
                settings.azure_servicebus_connection_string
            )
            with client:
                receiver = client.get_queue_receiver(
                    queue_name=settings.azure_servicebus_queue_name,
                    max_wait_time=5,
                )
                with receiver:
                    while not _stop_event.is_set():
                        messages = receiver.receive_messages(
                            max_message_count=10,
                            max_wait_time=5,
                        )
                        for message in messages:
                            try:
                                body = str(message)
                                _process_message(body)
                                receiver.complete_message(message)
                            except Exception:
                                logger.exception(
                                    "Failed to process message — abandoning"
                                )
                                receiver.abandon_message(message)

        except ServiceBusError:
            logger.exception("Service Bus connection error — retrying in 10s")
            _stop_event.wait(timeout=10)
        except Exception:
            logger.exception("Unexpected consumer error — retrying in 10s")
            _stop_event.wait(timeout=10)

    logger.info("Service Bus consumer stopped")


def start_consumer() -> None:
    """Start the background consumer thread."""
    global _consumer_thread
    if _consumer_thread is not None and _consumer_thread.is_alive():
        logger.warning("Consumer thread already running")
        return

    _stop_event.clear()
    _consumer_thread = threading.Thread(target=_consumer_loop, daemon=True, name="sb-consumer")
    _consumer_thread.start()
    logger.info("Consumer thread started")


def stop_consumer() -> None:
    """Stop the background consumer thread."""
    global _consumer_thread
    _stop_event.set()
    if _consumer_thread is not None:
        _consumer_thread.join(timeout=15)
        _consumer_thread = None
    logger.info("Consumer thread stopped")


async def check_servicebus_health() -> bool:
    """Check if Service Bus connection is healthy."""
    if not settings.azure_servicebus_connection_string:
        return False
    try:
        client = ServiceBusClient.from_connection_string(
            settings.azure_servicebus_connection_string
        )
        with client:
            receiver = client.get_queue_receiver(
                queue_name=settings.azure_servicebus_queue_name,
                max_wait_time=1,
            )
            with receiver:
                pass
        return True
    except ServiceBusError:
        logger.exception("Service Bus health check failed")
        return False

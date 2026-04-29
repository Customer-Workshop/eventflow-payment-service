"""Azure Service Bus consumer for order events."""

import json
import threading
import time

import httpx
import structlog
from azure.servicebus import ServiceBusClient
from azure.servicebus.exceptions import ServiceBusError

from app.config import settings
from app.models import OrderCreatedEvent, PaymentRecord
from app.processor import process_order_payment

logger = structlog.stdlib.get_logger(__name__)

# In-memory store for processed payments (demo purposes)
payments: dict[str, PaymentRecord] = {}

_consumer_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _update_order_status(order_id: str, status: str) -> None:
    """Callback to order service to update order status after payment processing."""
    if not settings.order_service_url:
        logger.debug(
            "order_status_callback_skipped",
            order_id=order_id,
            reason="ORDER_SERVICE_URL not set",
        )
        return
    url = f"{settings.order_service_url}/api/orders/{order_id}/status"
    try:
        response = httpx.patch(url, json={"status": status}, timeout=5.0)
        if response.status_code == 200:
            logger.info(
                "order_status_updated",
                order_id=order_id,
                new_status=status,
                callback_url=url,
                http_status=response.status_code,
            )
        else:
            logger.warning(
                "order_status_update_failed",
                order_id=order_id,
                new_status=status,
                callback_url=url,
                http_status=response.status_code,
            )
    except Exception:
        logger.warning(
            "order_status_callback_error",
            order_id=order_id,
            callback_url=url,
            exc_info=True,
        )


def _process_message(message_body: str, message_id: str | None = None,
                      enqueued_time: str | None = None,
                      delivery_count: int | None = None) -> None:
    """Parse and process a single Service Bus message.

    Args:
        message_body: JSON string of the OrderCreated event.
        message_id: Service Bus message ID.
        enqueued_time: Time the message was enqueued.
        delivery_count: Number of delivery attempts.
    """
    start = time.perf_counter()
    try:
        event_dict = json.loads(message_body)
        event = OrderCreatedEvent(**event_dict)

        logger.info(
            "event_received",
            event_id=event.event_id,
            event_type=event.event_type,
            order_id=event.data.order_id,
            currency=event.data.currency,
            amount=event.data.amount,
            queue_name=settings.azure_servicebus_queue_name,
            message_id=message_id,
            enqueued_time=enqueued_time,
            delivery_count=delivery_count,
        )

        # Set correlation ID from event data for downstream log correlation
        from app.middleware import set_correlation_id
        set_correlation_id(event.event_id)

        logger.info(
            "payment_processing_start",
            order_id=event.data.order_id,
            event_id=event.event_id,
        )

        # Process the payment — this is where JPY orders will crash
        payment = process_order_payment(event.data)
        payments[payment.payment_id] = payment

        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "payment_processing_complete",
            payment_id=payment.payment_id,
            order_id=payment.order_id,
            payment_status=payment.status.value,
            processing_duration_ms=duration_ms,
            event_id=event.event_id,
        )

        # Record metrics
        if settings.metrics_enabled:
            from app.metrics import metrics_collector
            metrics_collector.record_payment(payment.status.value, payment.currency)
            metrics_collector.record_event("success", duration_ms / 1000)

        # Callback to order service to update order status
        _update_order_status(event.data.order_id, payment.status.value)

    except json.JSONDecodeError:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.exception(
            "event_parse_failed",
            raw_body=message_body[:500],
            message_id=message_id,
            processing_duration_ms=duration_ms,
        )
        if settings.metrics_enabled:
            from app.metrics import metrics_collector
            metrics_collector.record_event("failure", duration_ms / 1000)
    except ValueError:
        # This is the unhandled exception path for JPY orders
        # The ValueError from validate_payment_amount propagates up uncaught
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.exception(
            "payment_validation_error",
            order_id=event.data.order_id,
            currency=event.data.currency,
            amount=event.data.amount,
            event_id=event.event_id,
            message_id=message_id,
            processing_duration_ms=duration_ms,
        )
        if settings.metrics_enabled:
            from app.metrics import metrics_collector
            metrics_collector.record_payment("failed", event.data.currency)
            metrics_collector.record_event("failure", duration_ms / 1000)
        # Try to update order status to failed before re-raising
        try:
            _update_order_status(event.data.order_id, "failed")
        except Exception:
            logger.warning(
                "order_status_update_after_failure_error",
                order_id=event.data.order_id,
            )
        raise
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.exception(
            "event_processing_unexpected_error",
            message_id=message_id,
            processing_duration_ms=duration_ms,
        )
        if settings.metrics_enabled:
            from app.metrics import metrics_collector
            metrics_collector.record_event("failure", duration_ms / 1000)
        raise


def _consumer_loop() -> None:
    """Background loop that consumes messages from Service Bus."""
    if not settings.azure_servicebus_connection_string:
        logger.warning(
            "consumer_not_started",
            reason="Service Bus connection string not set",
        )
        return

    logger.info(
        "servicebus_consumer_starting",
        queue_name=settings.azure_servicebus_queue_name,
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
                                msg_id = getattr(message, "message_id", None)
                                enq_time = getattr(message, "enqueued_time_utc", None)
                                enqueued = str(enq_time) if enq_time else None
                                delivery = getattr(message, "delivery_count", None)

                                logger.info(
                                    "servicebus_message_received",
                                    message_id=msg_id,
                                    enqueued_time=enqueued,
                                    delivery_count=delivery,
                                    queue_name=settings.azure_servicebus_queue_name,
                                )

                                _process_message(
                                    body,
                                    message_id=msg_id,
                                    enqueued_time=enqueued,
                                    delivery_count=delivery,
                                )
                                receiver.complete_message(message)
                            except Exception:
                                logger.exception(
                                    "message_processing_failed",
                                    message_id=msg_id if 'msg_id' in dir() else None,
                                    action="abandon",
                                )
                                receiver.abandon_message(message)

        except ServiceBusError:
            logger.exception(
                "servicebus_connection_error",
                queue_name=settings.azure_servicebus_queue_name,
                retry_in_seconds=10,
            )
            _stop_event.wait(timeout=10)
        except Exception:
            logger.exception(
                "consumer_unexpected_error",
                retry_in_seconds=10,
            )
            _stop_event.wait(timeout=10)

    logger.info("servicebus_consumer_stopped")


def start_consumer() -> None:
    """Start the background consumer thread."""
    global _consumer_thread
    if _consumer_thread is not None and _consumer_thread.is_alive():
        logger.warning("consumer_already_running")
        return

    _stop_event.clear()
    _consumer_thread = threading.Thread(target=_consumer_loop, daemon=True, name="sb-consumer")
    _consumer_thread.start()
    logger.info("consumer_thread_started")


def stop_consumer() -> None:
    """Stop the background consumer thread."""
    global _consumer_thread
    _stop_event.set()
    if _consumer_thread is not None:
        _consumer_thread.join(timeout=15)
        _consumer_thread = None
    logger.info("consumer_thread_stopped")


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
        logger.exception(
            "servicebus_health_check_failed",
            queue_name=settings.azure_servicebus_queue_name,
        )
        return False

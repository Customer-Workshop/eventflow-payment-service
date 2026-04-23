"""Tests for Pydantic data models."""

import uuid
from datetime import UTC, datetime

from app.models import (
    OrderCreatedEvent,
    OrderEventData,
    OrderItem,
    PaymentRecord,
    PaymentStatus,
)


class TestPaymentStatus:
    """Tests for PaymentStatus enum."""

    def test_pending_value(self):
        assert PaymentStatus.PENDING.value == "pending"

    def test_completed_value(self):
        assert PaymentStatus.COMPLETED.value == "completed"

    def test_failed_value(self):
        assert PaymentStatus.FAILED.value == "failed"


class TestPaymentRecord:
    """Tests for PaymentRecord default field generation."""

    def test_default_payment_id_is_uuid(self):
        """payment_id should default to a valid UUID string."""
        record = PaymentRecord(
            order_id="order-001",
            customer_id="cust-001",
            currency="USD",
            amount_minor=5000,
            amount_display=50.00,
        )
        uuid.UUID(record.payment_id)

    def test_default_processed_at_is_recent(self):
        """processed_at should default to approximately now."""
        before = datetime.now(UTC)
        record = PaymentRecord(
            order_id="order-001",
            customer_id="cust-001",
            currency="USD",
            amount_minor=5000,
            amount_display=50.00,
        )
        after = datetime.now(UTC)
        assert before <= record.processed_at <= after

    def test_default_status_is_pending(self):
        """Default status should be PENDING."""
        record = PaymentRecord(
            order_id="order-001",
            customer_id="cust-001",
            currency="USD",
            amount_minor=5000,
            amount_display=50.00,
        )
        assert record.status == PaymentStatus.PENDING

    def test_error_message_defaults_to_none(self):
        """error_message should default to None."""
        record = PaymentRecord(
            order_id="order-001",
            customer_id="cust-001",
            currency="USD",
            amount_minor=5000,
            amount_display=50.00,
        )
        assert record.error_message is None


class TestOrderCreatedEvent:
    """Tests for OrderCreatedEvent parsing from dict."""

    def test_parse_from_dict(self):
        """OrderCreatedEvent should parse correctly from a dictionary."""
        event_dict = {
            "event_id": "evt-001",
            "event_type": "OrderCreated",
            "timestamp": "2025-06-15T10:30:00Z",
            "data": {
                "order_id": "order-parse-001",
                "customer_id": "cust-parse-001",
                "currency": "EUR",
                "amount": 8999,
                "items": [
                    {
                        "product_id": "prod-301",
                        "name": "Monitor Stand",
                        "quantity": 1,
                        "unit_price": 8999,
                    }
                ],
            },
        }
        event = OrderCreatedEvent(**event_dict)

        assert event.event_id == "evt-001"
        assert event.event_type == "OrderCreated"
        assert isinstance(event.data, OrderEventData)
        assert event.data.order_id == "order-parse-001"
        assert event.data.currency == "EUR"
        assert event.data.amount == 8999
        assert len(event.data.items) == 1
        assert isinstance(event.data.items[0], OrderItem)
        assert event.data.items[0].name == "Monitor Stand"

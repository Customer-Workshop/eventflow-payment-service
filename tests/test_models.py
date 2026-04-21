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


class TestPaymentStatusEnum:
    """Tests for the PaymentStatus enum values."""

    def test_pending_value(self):
        """PENDING enum should have string value 'pending'."""
        assert PaymentStatus.PENDING.value == "pending"

    def test_completed_value(self):
        """COMPLETED enum should have string value 'completed'."""
        assert PaymentStatus.COMPLETED.value == "completed"

    def test_failed_value(self):
        """FAILED enum should have string value 'failed'."""
        assert PaymentStatus.FAILED.value == "failed"


class TestPaymentRecord:
    """Tests for PaymentRecord model defaults and field generation."""

    def test_payment_id_auto_generated(self):
        """payment_id should be automatically generated as a valid UUID."""
        record = PaymentRecord(
            order_id="order-001",
            customer_id="cust-001",
            currency="USD",
            amount_minor=5000,
            amount_display=50.0,
        )
        uuid.UUID(record.payment_id)

    def test_processed_at_auto_set(self):
        """processed_at should be automatically set to the current time."""
        before = datetime.now(UTC)
        record = PaymentRecord(
            order_id="order-001",
            customer_id="cust-001",
            currency="USD",
            amount_minor=5000,
            amount_display=50.0,
        )
        after = datetime.now(UTC)
        assert before <= record.processed_at <= after

    def test_status_defaults_to_pending(self):
        """status should default to PENDING."""
        record = PaymentRecord(
            order_id="order-001",
            customer_id="cust-001",
            currency="USD",
            amount_minor=5000,
            amount_display=50.0,
        )
        assert record.status == PaymentStatus.PENDING

    def test_error_message_defaults_to_none(self):
        """error_message should default to None."""
        record = PaymentRecord(
            order_id="order-001",
            customer_id="cust-001",
            currency="USD",
            amount_minor=5000,
            amount_display=50.0,
        )
        assert record.error_message is None


class TestOrderCreatedEvent:
    """Tests for OrderCreatedEvent deserialization."""

    def test_deserialize_from_dict(self):
        """OrderCreatedEvent should correctly deserialize from a dictionary."""
        event_dict = {
            "event_id": "evt-001",
            "event_type": "OrderCreated",
            "timestamp": "2025-01-15T10:30:00Z",
            "data": {
                "order_id": "order-001",
                "customer_id": "cust-001",
                "currency": "USD",
                "amount": 5000,
                "items": [
                    {"product_id": "p1", "name": "Widget", "quantity": 2, "unit_price": 2500}
                ],
            },
        }
        event = OrderCreatedEvent(**event_dict)

        assert event.event_id == "evt-001"
        assert event.event_type == "OrderCreated"
        assert event.data.order_id == "order-001"
        assert event.data.currency == "USD"
        assert event.data.amount == 5000
        assert len(event.data.items) == 1


class TestOrderEventData:
    """Tests for OrderEventData construction and field access."""

    def test_field_access(self):
        """OrderEventData fields should be accessible after construction."""
        data = OrderEventData(
            order_id="order-001",
            customer_id="cust-001",
            currency="EUR",
            amount=8999,
            items=[
                OrderItem(product_id="p1", name="Thing", quantity=1, unit_price=8999),
            ],
        )
        assert data.order_id == "order-001"
        assert data.customer_id == "cust-001"
        assert data.currency == "EUR"
        assert data.amount == 8999
        assert len(data.items) == 1
        assert data.items[0].product_id == "p1"
        assert data.items[0].name == "Thing"
        assert data.items[0].quantity == 1
        assert data.items[0].unit_price == 8999

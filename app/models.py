"""Pydantic models for payment processing."""

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class PaymentStatus(str, Enum):
    """Payment processing status."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class OrderItem(BaseModel):
    """A single item from the order event."""

    product_id: str
    name: str
    quantity: int
    unit_price: int


class OrderCreatedEvent(BaseModel):
    """Inbound event from the Order Service."""

    event_id: str
    event_type: str
    timestamp: datetime
    data: "OrderEventData"


class OrderEventData(BaseModel):
    """Data payload of the OrderCreated event."""

    order_id: str
    customer_id: str
    currency: str
    amount: int
    items: list[OrderItem]


class PaymentRecord(BaseModel):
    """A processed payment record."""

    payment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str
    customer_id: str
    currency: str
    amount_minor: int = Field(description="Amount in smallest currency unit")
    amount_display: float = Field(description="Amount in display format")
    status: PaymentStatus = PaymentStatus.PENDING
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: str | None = None

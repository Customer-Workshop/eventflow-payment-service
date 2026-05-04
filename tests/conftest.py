"""Shared test fixtures for the Payment Service."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import OrderEventData


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI application."""
    return TestClient(app)


@pytest.fixture
def usd_order_event_data() -> OrderEventData:
    """An OrderCreated event payload for a USD order."""
    return OrderEventData(
        order_id="order-usd-001",
        customer_id="cust-001",
        currency="USD",
        amount=10997,
        items=[
            {
                "product_id": "prod-101",
                "name": "Wireless Mouse",
                "quantity": 2,
                "unit_price": 2999,
            },
            {
                "product_id": "prod-102",
                "name": "USB-C Hub",
                "quantity": 1,
                "unit_price": 4999,
            },
        ],
    )


@pytest.fixture
def eur_order_event_data() -> OrderEventData:
    """An OrderCreated event payload for a EUR order."""
    return OrderEventData(
        order_id="order-eur-001",
        customer_id="cust-003",
        currency="EUR",
        amount=8999,
        items=[
            {
                "product_id": "prod-301",
                "name": "Monitor Stand",
                "quantity": 1,
                "unit_price": 8999,
            },
        ],
    )


@pytest.fixture
def sample_order_event_json() -> str:
    """A valid OrderCreated event as a JSON string."""
    return json.dumps(
        {
            "event_id": "evt-test-001",
            "event_type": "OrderCreated",
            "timestamp": "2025-01-15T10:30:00Z",
            "data": {
                "order_id": "order-test-001",
                "customer_id": "cust-test-001",
                "currency": "USD",
                "amount": 5000,
                "items": [
                    {
                        "product_id": "prod-001",
                        "name": "Test Item",
                        "quantity": 1,
                        "unit_price": 5000,
                    }
                ],
            },
        }
    )


@pytest.fixture
def jpy_order_event_json() -> str:
    """A JPY OrderCreated event that triggers the intentional bug."""
    return json.dumps(
        {
            "event_id": "evt-jpy-001",
            "event_type": "OrderCreated",
            "timestamp": "2025-01-15T10:30:00Z",
            "data": {
                "order_id": "order-jpy-001",
                "customer_id": "cust-jp-001",
                "currency": "JPY",
                "amount": 15800,
                "items": [
                    {
                        "product_id": "prod-jp-001",
                        "name": "Japanese Item",
                        "quantity": 1,
                        "unit_price": 15800,
                    }
                ],
            },
        }
    )

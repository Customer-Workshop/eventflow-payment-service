"""Shared test fixtures for the Payment Service."""

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
def jpy_order_event_data() -> OrderEventData:
    """An OrderCreated event payload for a JPY (zero-decimal) order."""
    return OrderEventData(
        order_id="order-jpy-001",
        customer_id="cust-005",
        currency="JPY",
        amount=15800,
        items=[
            {
                "product_id": "prod-501",
                "name": "Mechanical Keyboard",
                "quantity": 1,
                "unit_price": 8900,
            },
            {
                "product_id": "prod-502",
                "name": "Wrist Rest",
                "quantity": 1,
                "unit_price": 6900,
            },
        ],
    )

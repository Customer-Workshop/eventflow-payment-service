"""EventFlow Payment Service — FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.consumer import (
    check_servicebus_health,
    payments,
    start_consumer,
    stop_consumer,
)
from app.models import PaymentRecord

# Configure structured logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown."""
    logger.info(
        "Starting %s v%s (env=%s)",
        settings.service_name,
        settings.service_version,
        settings.environment,
    )
    start_consumer()
    yield
    logger.info("Shutting down %s", settings.service_name)
    stop_consumer()


app = FastAPI(
    title="EventFlow Payment Service",
    description="Consumes OrderCreated events from Azure Service Bus and processes payments.",
    version=settings.service_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Basic liveness probe."""
    return {"status": "healthy", "service": settings.service_name}


@app.get("/ready", tags=["health"])
async def readiness_check() -> dict[str, str | bool]:
    """Readiness probe — verifies downstream dependencies."""
    servicebus_ok = await check_servicebus_health()
    overall = "ready" if servicebus_ok else "degraded"
    return {
        "status": overall,
        "service": settings.service_name,
        "servicebus_connected": servicebus_ok,
    }


@app.get("/api/payments", tags=["payments"], response_model=list[PaymentRecord])
async def list_payments(limit: int = 50) -> list[PaymentRecord]:
    """List processed payments."""
    records = list(payments.values())
    records.sort(key=lambda p: p.processed_at, reverse=True)
    return records[:limit]


@app.get("/api/payments/{payment_id}", tags=["payments"], response_model=PaymentRecord)
async def get_payment(payment_id: str) -> PaymentRecord:
    """Get a payment record by ID."""
    from fastapi import HTTPException, status

    record = payments.get(payment_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment {payment_id} not found",
        )
    return record

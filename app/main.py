"""EventFlow Payment Service — FastAPI application entry point.

This module is the main entry point for the EventFlow Payment Service, a
FastAPI-based microservice within the EventFlow event-driven architecture.
It is the **second system** in the pipeline: the upstream Order Service
publishes ``OrderCreated`` events to an Azure Service Bus queue, and this
service consumes those events, validates/processes the payment amounts
through a simulated gateway, and stores the resulting payment records
in memory.

Responsibilities handled here:
    * FastAPI application instantiation and metadata configuration.
    * Application lifespan management — starting the background Azure
      Service Bus consumer on startup and gracefully stopping it on
      shutdown.
    * CORS middleware registration (permissive, for cross-origin demo
      frontends).
    * Root-level structured logging configuration.
    * HTTP endpoints:
        - ``GET /health``  — Kubernetes/container **liveness** probe.
        - ``GET /ready``   — Kubernetes/container **readiness** probe
          (checks Service Bus connectivity).
        - ``GET /api/payments``           — List processed payments.
        - ``GET /api/payments/{id}``      — Retrieve a single payment.

The service is started with **uvicorn**::

    poetry run uvicorn app.main:app --reload --port 8002

Key design decisions:
    * **Dual-plane architecture** — The Service Bus consumer runs on a
      background daemon thread (see ``app.consumer``) so it does not
      block the ASGI event loop, while the HTTP API runs on the main
      async loop.
    * **In-memory storage** — Payment records are kept in a plain
      ``dict`` (``app.consumer.payments``).  This is intentional for
      demo/prototype purposes and is *not* production-ready.
    * **Lifespan context manager** — FastAPI's ``lifespan`` parameter
      replaces the deprecated ``on_event("startup")`` /
      ``on_event("shutdown")`` hooks, ensuring deterministic resource
      cleanup even under abnormal shutdown.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
# Uses the stdlib logging module with a simple timestamped format.
# The level is driven by the ``LOG_LEVEL`` env var (default ``INFO``)
# via ``app.config.settings``.  ``getattr`` provides a safe fallback to
# ``INFO`` if the configured value does not map to a valid logging level.
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Manage the startup and shutdown lifecycle of the FastAPI application.

    This async context manager is passed to ``FastAPI(lifespan=...)`` and is
    invoked automatically by the ASGI server (uvicorn).

    **Startup** (before ``yield``):
        1. Logs the service identity (name, version, environment) for
           operational visibility in aggregated log streams.
        2. Calls ``start_consumer()`` which spawns a daemon thread that
           connects to Azure Service Bus and begins polling the
           ``order-events`` queue for ``OrderCreated`` messages.

    **Shutdown** (after ``yield``):
        1. Logs the shutdown event.
        2. Calls ``stop_consumer()`` which signals the daemon thread to
           stop via a ``threading.Event`` and joins it with a 15-second
           timeout, allowing in-flight messages to be completed or
           abandoned gracefully.

    Args:
        application: The FastAPI application instance (unused directly,
            but required by the lifespan protocol signature).

    Yields:
        Control to the ASGI server for the lifetime of the application.
    """
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


# ---------------------------------------------------------------------------
# FastAPI application instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="EventFlow Payment Service",
    description="Consumes OrderCreated events from Azure Service Bus and processes payments.",
    version=settings.service_version,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------
# Configured with fully permissive defaults (allow all origins, methods,
# and headers) so that any demo frontend or developer tool can interact
# with the API without cross-origin restrictions.  In a production
# deployment these values should be scoped to known origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health / readiness endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Kubernetes **liveness** probe endpoint.

    Returns a minimal JSON payload indicating the process is alive and
    able to serve HTTP traffic.  This endpoint performs **no** dependency
    checks — it only confirms that the ASGI server and FastAPI routing
    layer are functional.  Container orchestrators (e.g. Kubernetes,
    Azure Container Apps) call this periodically; repeated failures
    trigger a container restart.

    Returns:
        A dict with ``status`` (``"healthy"``) and the ``service`` name.
    """
    return {"status": "healthy", "service": settings.service_name}


@app.get("/ready", tags=["health"])
async def readiness_check() -> dict[str, str | bool]:
    """Kubernetes **readiness** probe endpoint.

    Unlike the liveness probe, this endpoint verifies that the service's
    critical downstream dependency — Azure Service Bus — is reachable.
    If the Service Bus connection cannot be established, the status is
    reported as ``"degraded"`` and the orchestrator should stop routing
    new traffic to this instance until connectivity is restored.

    Returns:
        A dict with ``status`` (``"ready"`` or ``"degraded"``), the
        ``service`` name, and a ``servicebus_connected`` boolean flag.
    """
    servicebus_ok = await check_servicebus_health()
    overall = "ready" if servicebus_ok else "degraded"
    return {
        "status": overall,
        "service": settings.service_name,
        "servicebus_connected": servicebus_ok,
    }


# ---------------------------------------------------------------------------
# Payment retrieval endpoints
# ---------------------------------------------------------------------------


@app.get("/api/payments", tags=["payments"], response_model=list[PaymentRecord])
async def list_payments(limit: int = 50) -> list[PaymentRecord]:
    """List processed payment records, most recent first.

    Retrieves payment records from the in-memory store populated by the
    background Service Bus consumer as it processes ``OrderCreated``
    events.  Results are sorted by ``processed_at`` in descending order.

    Args:
        limit: Maximum number of records to return (default 50).

    Returns:
        A list of ``PaymentRecord`` objects, truncated to *limit*.
    """
    records = list(payments.values())
    records.sort(key=lambda p: p.processed_at, reverse=True)
    return records[:limit]


@app.get("/api/payments/{payment_id}", tags=["payments"], response_model=PaymentRecord)
async def get_payment(payment_id: str) -> PaymentRecord:
    """Retrieve a single payment record by its unique identifier.

    Looks up the payment in the in-memory store.  Returns a 404 response
    if no record matches the given *payment_id*.

    Args:
        payment_id: UUID string assigned during payment processing.

    Returns:
        The matching ``PaymentRecord``.

    Raises:
        HTTPException: 404 if the payment ID is not found.
    """
    from fastapi import HTTPException, status

    record = payments.get(payment_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment {payment_id} not found",
        )
    return record

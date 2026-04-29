"""Global exception handlers for structured error logging."""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.middleware import get_correlation_id

logger = structlog.stdlib.get_logger(__name__)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions.

    Logs the full traceback in structured format and returns a generic
    JSON error response without leaking internal details.
    """
    cid = get_correlation_id()
    logger.error(
        "unhandled_exception",
        http_method=request.method,
        http_path=request.url.path,
        correlation_id=cid,
        exception_type=type(exc).__name__,
        exception_message=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "correlation_id": cid,
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach global exception handlers to the FastAPI application."""
    app.add_exception_handler(Exception, unhandled_exception_handler)

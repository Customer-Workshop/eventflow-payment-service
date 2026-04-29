"""HTTP middleware for correlation IDs, request/response logging, and metrics."""

from __future__ import annotations

import contextvars
import time
import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import settings

logger = structlog.stdlib.get_logger(__name__)

# ---------------------------------------------------------------------------
# Correlation ID
# ---------------------------------------------------------------------------

_correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)

CORRELATION_HEADER = "X-Correlation-ID"

# Paths excluded from request/response logging by default
_SKIP_LOG_PATHS: set[str] = {"/health", "/ready"}


def get_correlation_id() -> str | None:
    """Return the current correlation ID (if any)."""
    return _correlation_id_ctx.get()


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID for the current context."""
    _correlation_id_ctx.set(cid)


# ---------------------------------------------------------------------------
# Correlation-ID + Request/Response Logging Middleware
# ---------------------------------------------------------------------------


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Generates correlation IDs and logs HTTP requests/responses."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Resolve or generate correlation ID
        cid = request.headers.get(CORRELATION_HEADER) or str(uuid.uuid4())
        set_correlation_id(cid)

        start = time.perf_counter()

        # Determine if this path should be logged
        skip_logging = request.url.path in _SKIP_LOG_PATHS

        if not skip_logging:
            logger.info(
                "http_request_started",
                http_method=request.method,
                http_path=request.url.path,
                http_query=str(request.url.query),
                client_ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                correlation_id=cid,
            )

        response: Response | None = None
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            if not skip_logging:
                logger.error(
                    "http_request_error",
                    http_method=request.method,
                    http_path=request.url.path,
                    response_time_ms=duration_ms,
                    correlation_id=cid,
                    exc_info=True,
                )
            raise
        finally:
            # Clear contextvars to avoid leaking across requests
            _correlation_id_ctx.set(None)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        status_code = response.status_code

        response.headers[CORRELATION_HEADER] = cid

        if not skip_logging:
            log_level = "info"
            if 400 <= status_code < 500:
                log_level = "warning"
            elif status_code >= 500:
                log_level = "error"

            getattr(logger, log_level)(
                "http_request_completed",
                http_method=request.method,
                http_path=request.url.path,
                http_status=status_code,
                response_time_ms=duration_ms,
                correlation_id=cid,
            )

        # Slow-request warning
        if duration_ms > settings.slow_request_threshold_ms and not skip_logging:
            logger.warning(
                "slow_request_detected",
                http_method=request.method,
                http_path=request.url.path,
                response_time_ms=duration_ms,
                threshold_ms=settings.slow_request_threshold_ms,
                correlation_id=cid,
            )

        # Collect metrics (import here to avoid circular import at module level)
        if settings.metrics_enabled:
            from app.metrics import metrics_collector

            metrics_collector.record_request(
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_seconds=duration_ms / 1000,
            )

        return response

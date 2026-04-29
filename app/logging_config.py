"""Structured logging configuration for ELK-compatible JSON output.

Configures structlog with ECS (Elastic Common Schema) compatible field names
and bridges stdlib logging so all log calls produce structured JSON.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config import settings


def _add_service_context(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add service metadata to every log entry (ECS fields)."""
    event_dict["service.name"] = settings.service_name
    event_dict["service.version"] = settings.service_version
    event_dict["service.environment"] = settings.environment
    return event_dict


def _rename_event_to_message(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Rename structlog's 'event' key to 'message' for ECS compatibility."""
    event_dict["message"] = event_dict.pop("event", "")
    return event_dict


def _rename_level_to_ecs(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Rename 'level' to 'log.level' for ECS compatibility."""
    level = event_dict.pop("level", None)
    if level is not None:
        event_dict["log.level"] = level
    return event_dict


def _add_logger_name(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Ensure 'logger' field is present."""
    if "logger" not in event_dict:
        if isinstance(logger, str):
            event_dict["logger"] = event_dict.get("_record", {}).get("name", logger)
        else:
            event_dict["logger"] = getattr(logger, "name", "root")
    return event_dict


def _add_correlation_id(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Inject correlation_id from contextvars into every log entry."""
    from app.middleware import get_correlation_id

    cid = get_correlation_id()
    if cid:
        event_dict["correlation_id"] = cid
        event_dict["trace.id"] = cid
    return event_dict


def configure_logging() -> None:
    """Set up structlog and stdlib logging bridge.

    Reads ``settings.log_format`` to choose between JSON (for ELK/Filebeat)
    and console (human-readable) output.
    """
    log_format = settings.log_format.lower()
    log_level_name = settings.log_level.upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="@timestamp"),
        _add_service_context,
        _add_correlation_id,
        _add_logger_name,
        structlog.stdlib.add_logger_name,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "console":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        shared_processors.append(_rename_event_to_message)
        shared_processors.append(_rename_level_to_ecs)
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    handler: logging.Handler
    if settings.log_output.lower() == "stdout" or settings.log_output == "":
        handler = logging.StreamHandler(sys.stdout)
    else:
        handler = logging.FileHandler(settings.log_output)

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Quiet noisy third-party loggers
    for noisy in ("azure", "uamqp", "urllib3", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

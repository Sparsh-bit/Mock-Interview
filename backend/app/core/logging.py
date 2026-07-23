"""
Structured Logging — core/logging.py

Configures structlog for the entire application.
All logs are emitted as structured JSON in production and as colored console output in development.

Usage:
    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("event_name", key="value", other_key=123)

Never use:
    print()
    logging.info()  # Use structlog everywhere
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor


def _add_app_info(
    logger: Any, method_name: str, event_dict: EventDict
) -> EventDict:
    """Inject static application metadata into every log record."""
    from app.core.config import settings  # noqa: PLC0415

    event_dict.setdefault("app", settings.APP_NAME)
    event_dict.setdefault("version", settings.APP_VERSION)
    event_dict.setdefault("env", settings.ENVIRONMENT)
    return event_dict


def _drop_color_message_key(
    logger: Any, method_name: str, event_dict: EventDict
) -> EventDict:
    """Remove the color_message key added by uvicorn — not needed in structured logs."""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(log_level: str = "INFO", log_format: str = "console") -> None:
    """
    Configure structlog + stdlib logging.

    Call this ONCE at application startup in main.py.
    After this, all `logging.getLogger()` calls are also captured by structlog.
    """

    # Common processors applied to every log record
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _add_app_info,
        _drop_color_message_key,
    ]

    if log_format == "json":
        # Production: structured JSON (ingested by Datadog / Loki / CloudWatch)
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        # Development: colored console output for readability
        renderer = structlog.dev.ConsoleRenderer(
            exception_formatter=structlog.dev.plain_traceback,
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging through structlog so uvicorn, SQLAlchemy, etc.
    # all emit structured logs
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # Silence noisy libraries
    for lib in ("asyncio", "httpx", "httpcore", "hpack"):
        logging.getLogger(lib).setLevel(logging.WARNING)

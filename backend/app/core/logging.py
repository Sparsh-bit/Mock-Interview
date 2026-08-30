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


#: Fields that carry no personal data and MUST survive redaction, whatever their name
#: suggests. Without this, `request_id` — a UUID — would be replaced by a one-way handle
#: while the `X-Request-ID` response header still carried the raw value, so the one thing
#: a person can quote from a failed request would no longer find anything in the logs.
_NEVER_REDACT: frozenset[str] = frozenset({"request_id", "event", "level", "logger", "timestamp"})


def _redact_pii(
    logger: Any, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    Take the candidate out of the log line.

    WHY THIS IS A PROCESSOR AND NOT A REVIEW OF EVERY CALL SITE. An audit of the 300-odd
    logger calls in this codebase found four real leaks — 120 characters of a resume on a
    parse failure, 400 characters of raw model output on a JSON failure, the parsed response
    on a validation failure, and e-mail addresses on three auth paths. Fixing those four and
    stopping would leave the next one to whoever writes it, and the failure is silent: a log
    line with somebody's CV in it looks exactly like a log line without one.

    So it is enforced here, once, on the way out. The call sites were fixed too — a redacted
    field is safe but useless, and the useful version is usually a length or a reason — but
    this is what makes the guarantee hold for code that does not exist yet.

    IT SHARES ITS DENYLIST AND ITS REGISTRY WITH THE SENTRY SCRUBBER
    (`core/observability.py`) rather than keeping a second copy. Two lists of "what counts as
    personal data here" would drift, and the drift would be invisible on both sides.
    `register_sensitive_text()` is already called where resume text is extracted and where an
    answer is submitted, so those exact strings are removed from log lines as well.

    WHAT IS DELIBERATELY NOT REDACTED: UUIDs. `user_id` and `session_id` stay readable, and
    that is a judgement rather than an oversight. They are pseudonymous, they are the entire
    mechanism for triaging an incident, and hashing them would buy little against an operator
    who can also read the database — while making the logs unusable for the person the logs
    exist for. E-mail addresses ARE redacted, because those identify a person directly and a
    `user_id` in the same line already answers "who".

    THE MOMENT LOGS LEAVE THE HOST THIS BALANCE CHANGES. A drain to a third party makes that
    party a processor, which is a §5 disclosure question, not a logging question — see
    docs/OBSERVABILITY.md.
    """
    from app.core.observability import redact_log_value  # noqa: PLC0415

    for key in list(event_dict):
        if key in _NEVER_REDACT:
            continue
        event_dict[key] = redact_log_value(key, event_dict[key])
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
        # LAST OF THE SHARED PROCESSORS, so it sees everything the ones above added and
        # everything the caller passed. Before the renderer, so it applies identically to
        # JSON in production and to the console in development — a leak that only exists on
        # a developer's machine is still a leak, and it is the one people copy into a ticket.
        _redact_pii,
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

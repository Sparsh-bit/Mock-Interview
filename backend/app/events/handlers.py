"""
Event Handlers — events/handlers.py

Default event handlers registered on the EventBus at startup.

Rules:
  - Handlers MUST be async.
  - Handlers MUST NOT raise exceptions (the bus catches them, but clean code
    should handle failures internally and log them).
  - Handlers MUST complete quickly — no blocking I/O in the hot path.
    For slow operations (e.g., sending emails), spawn a background task.
  - Handlers MUST NOT call business logic — they are observers only.
"""

from __future__ import annotations

import structlog

from .base import BaseEvent

logger = structlog.get_logger(__name__)


async def log_event_handler(event: BaseEvent) -> None:
    """
    Writes every platform event to the structured log.

    This is the primary debugging and observability tool.
    Log entries can be shipped to Datadog, Loki, or CloudWatch.
    Zero external dependencies — always safe and fast.
    """
    logger.info(
        "platform_event",
        event_type=str(event.event_type),
        event_id=str(event.event_id),
        user_id=str(event.user_id) if event.user_id else None,
        session_id=str(event.session_id) if event.session_id else None,
        occurred_at=event.occurred_at.isoformat(),
        version=event.version,
    )


async def persist_event_handler(event: BaseEvent) -> None:
    """
    Persists every platform event to the audit_logs table.

    This table is the source of truth for analytics, debugging, and
    future recruiter dashboard queries. It is append-only — records are
    never updated or deleted.

    A short-lived DB session is acquired per-event from the connection pool.
    Failures are logged; the event bus will catch any exception that escapes.
    """
    try:
        # Deferred imports to avoid circular dependency at module load time
        from app.db.session import get_db_session  # noqa: PLC0415
        from app.models.system import AuditLog  # noqa: PLC0415

        async with get_db_session() as db:
            log_entry = AuditLog(
                user_id=event.user_id,
                action=str(event.event_type),
                entity_type=_entity_type(event),
                entity_id=event.session_id,
                payload=_safe_payload(event),
            )
            db.add(log_entry)
            await db.commit()

    except Exception:
        logger.exception(
            "event_persist_failed",
            event_type=str(event.event_type),
            event_id=str(event.event_id),
        )


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _entity_type(event: BaseEvent) -> str | None:
    """Map event domain prefix to the primary entity type for the audit log."""
    domain = str(event.event_type).split(".")[0]
    return {
        "interview": "interview_session",
        "report": "report",
        "resume": "resume_file",
        "user": "user",
        "system": None,
    }.get(domain)


def _safe_payload(event: BaseEvent) -> dict:
    """
    Serialize the event to a dict for JSONB storage.
    Removes top-level fields that are already stored as dedicated columns.
    Falls back to empty dict on any serialization error.
    """
    try:
        data = event.model_dump(mode="json")
        # These are already in dedicated audit_log columns — skip them in payload
        for key in ("event_id", "event_type", "occurred_at", "user_id", "session_id"):
            data.pop(key, None)
        return data
    except Exception:
        logger.exception(
            "event_payload_serialization_failed",
            event_type=str(event.event_type),
        )
        return {}

"""
Activity logging — services/activity.py

Small best-effort helper to record a completed activity (interview, group
discussion, communication round, quiz) into activity_logs so the reports /
history surface can show everything a candidate has done in one feed.

Logging must never break the actual feature, so failures are swallowed and
logged at warning level.
"""

from __future__ import annotations

import contextlib
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityLog

logger = structlog.get_logger(__name__)


async def log_activity(
    db: AsyncSession,
    user_id: uuid.UUID,
    activity_type: str,
    title: str,
    score: float = 0.0,
    details: dict | None = None,
) -> None:
    """Record one completed activity. Best-effort — never raises."""
    try:
        db.add(
            ActivityLog(
                id=uuid.uuid4(),
                user_id=user_id,
                activity_type=activity_type,
                title=title[:255],
                score=round(float(score), 1),
                details=details,
            )
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — logging must not break the feature
        logger.warning("activity_log_failed", activity_type=activity_type, error=str(exc))
        with contextlib.suppress(Exception):
            await db.rollback()

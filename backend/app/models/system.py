"""
System models — models/system.py

Tables: audit_logs, system_prompts

audit_logs — immutable event log written by the event system.
system_prompts — admin-managed prompt overrides (DB takes precedence over .md files).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """
    Immutable platform event log.

    Written by event handlers (events/handlers.py::persist_event_handler).
    Never updated or deleted — append-only by design.
    No TimestampMixin: only has created_at (no updated_at, by design).

    This table powers:
    - Debugging: trace exactly what happened in a session
    - Analytics: aggregate event counts, latencies, score trends
    - Future recruiter dashboard: filter sessions by outcome
    """

    __tablename__ = "audit_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    # Dot-notation event identifier, e.g. "interview.started", "report.generated"
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # Primary entity type this event relates to
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    # HTTP request metadata for security audit
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    # Full event payload for debugging and replay
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


class SystemPrompt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Admin-managed AI prompt overrides.

    The PromptLoader checks this table AFTER the filesystem.
    If a SystemPrompt with name="interviewer" and is_active=True exists,
    it overrides backend/app/prompts/interviewer.md.

    This enables production prompt updates without code deployments.
    Prompt history is preserved in audit_logs via event emission.
    """

    __tablename__ = "system_prompts"

    # Matches the .md filename without extension (e.g., "interviewer")
    name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Monotonically increasing; incremented on each admin edit
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

"""
Activity model — models/activity.py

Table: activity_logs

A single unified feed of everything a candidate has done on the platform —
interviews, group discussions, communication rounds, and quizzes — so the
reports/history surface can show the full picture in one place. Each row is a
completed activity with a headline score and a JSON blob of the details
specific to that activity type.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ActivityLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One completed activity (interview / gd / communication / quiz)."""

    __tablename__ = "activity_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # "interview" | "group_discussion" | "communication" | "quiz"
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # 0-100 headline score for the activity (0 if not applicable)
    score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    # Type-specific detail: topic, per-dimension scores, feedback, etc.
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_activity_logs_user_created", "user_id", "created_at"),
    )

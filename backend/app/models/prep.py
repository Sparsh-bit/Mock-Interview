"""
Preparation progress — models/prep.py

One row per subtopic a candidate has ticked off. See migration 009 for why this is
server-side rather than in localStorage, and why the key is a derived string
rather than an index.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PrepProgress(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A subtopic the candidate has marked complete."""

    __tablename__ = "prep_progress"
    __table_args__ = (
        # Completion is idempotent: a subtopic is done or not, never done twice.
        UniqueConstraint("user_id", "subtopic_id", name="uq_prep_progress_user_subtopic"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    #: Context only. Progress is keyed on the subtopic, so ticking "Trees & BST"
    #: while preparing for Amazon also shows as done on the TCS plan — which is
    #: correct: you learned it once.
    company_slug: Mapped[str | None] = mapped_column(String(64))
    subtopic_id: Mapped[str] = mapped_column(String(128), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

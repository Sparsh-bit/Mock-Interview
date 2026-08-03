"""
The rating ledger — models/progress.py

APPEND-ONLY, ONE ROW PER RATED ROUND. There is deliberately no `user_rating` table
holding a current value, because a rating is path-dependent: it is the result of a
sequence, not of a set. Two stores of the same fact drift, and the one that drifts
here is the number a candidate is being asked to trust.

So the current rating is the newest event's `rating_after`, and the cleared-round
credential is a COUNT over these rows. Both are derived, both are recomputable by
replaying the ledger in order, and neither can disagree with the other.

`rating_after` is denormalised onto each row anyway — that is not redundancy with
the derived value, it is the audit trail. A candidate who asks "why did that round
only give me two points" can be answered exactly, and a change to the formula can be
verified against what was actually shown at the time.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RatingEvent(Base):
    """One rated round: what it was, how it went, and what it did to the rating."""

    __tablename__ = "rating_events"
    __table_args__ = (
        # ONE event per session. The writer runs when a report is generated, and a
        # report can be regenerated — without this, a candidate could re-request
        # their report to bank the same gain twice, which is the cheapest possible
        # exploit against the whole credential.
        UniqueConstraint("session_id", name="uq_rating_events_session"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Nullable on delete rather than cascading: if a session is removed the round
    #: still happened, and silently deleting rating history would let a candidate
    #: erase a bad round by deleting the session.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="SET NULL")
    )

    #: "interview" | "gd". Both feed one rating, because a candidate who can hold a
    #: technical round but not a group discussion is not placement-ready, and two
    #: separate numbers would let them ignore the half they are worse at.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    #: Tier.value — foundation | core | panel. Derived from the round, never chosen.
    tier: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    #: Did this round meet its tier's bar? The monotonic credential counts these.
    cleared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    rating_after: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The inputs and intermediates behind `delta` — expected, actual, the damper
    #: scale, the topic overlap that produced it. Kept so the UI can explain a small
    #: gain instead of leaving the candidate to assume it is broken, and so a
    #: formula change can be audited against what was displayed.
    detail: Mapped[dict | None] = mapped_column(JSONB)

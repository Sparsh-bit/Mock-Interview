"""
Per-utterance speech cost — models/tts_usage.py

THE TABLE THAT DID NOT EXIST, AND WHAT ITS ABSENCE COST. Speech was tracked in exactly one
place: `services/tts/spend.py`, a Redis float keyed by UTC day with a 48-hour TTL. That is
the right shape for what it was built for — a circuit breaker that must keep working when
the database is slow — and it is unusable for anything else:

  * ONE NUMBER FOR EVERYBODY. No user, no session, no feature, no vendor. "Which feature is
    the speech bill" has no answer.
  * TWO DAYS OF HISTORY. Any window longer than that reads as zero, so a monthly margin
    could not include speech even in principle.
  * NOT A LEDGER. `INCRBYFLOAT` on a key that expires is a gauge. There is nothing to audit,
    nothing to reconcile against the vendor's invoice, and nothing to re-derive if the
    estimate per character turns out to be wrong.

So `/admin/revenue` reported gross and `plans.py` priced against AI cost alone, and the
second variable cost of the product — the one that can be TWELVE TIMES the AI cost on the
wrong vendor, see services/tts/base.py — appeared in no figure anybody could look at.

DELIBERATELY SHAPED LIKE `ai_usage`, down to the best-effort writer and the SET NULL on
user. They answer the same question about two different vendors, and two answers to one
question that are shaped differently are two things a report has to reconcile before it can
add them up.

THE REDIS COUNTER STAYS. It is the budget guard on the hot path and it must not acquire a
database dependency: `_budget_room` runs before every synthesis, and a money guard that
fails open because Postgres is slow is a money guard that does not exist. This table is the
record; that counter is the brake.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TTSUsage(Base):
    """One synthesised utterance, and what it cost."""

    __tablename__ = "tts_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    #: "fish" | "elevenlabs". THE COLUMN THE WHOLE TABLE EXISTS FOR, next to `cost_usd`:
    #: the vendor choice is a ten-fold difference in the speech bill and it is a deployment
    #: setting, so a window that spans a vendor switch has to be able to show both.
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Which panelist or interviewer spoke. A roster name from api/v1/gd.py or panel.py —
    #: product data, never the candidate. It is here because "which voice costs the most"
    #: is answerable from it and from nothing else, and because a voice that is being
    #: synthesised far more than the others is usually a bug in the turn logic.
    speaker: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    #: The unit these vendors bill in. Tokens are meaningless here.
    characters: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: A CACHE HIT IS RECORDED, AT ZERO. It is the single most valuable number in this table.
    #: `scripts/item_margin.py` shows the whole GD-versus-interview margin gap comes from the
    #: interview's questions being identical for every candidate and a GD's turns never
    #: being — so the hit rate IS the speech economics, and a table that only recorded misses
    #: could measure the bill but never the thing that reduces it.
    cached: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )

    #: NUMERIC, not float, for the reason models/ai_usage.py gives: so a SUM is exactly the
    #: sum of the rows and does not vary between runs when Postgres picks a parallel plan.
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("0")
    )

    #: SET NULL on user delete: removing an account must not erase the fact that money was
    #: spent. Same rule, and the same reason, as `ai_usage.user_id`.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_tts_usage_user_id"),
        nullable=True,
        index=True,
    )

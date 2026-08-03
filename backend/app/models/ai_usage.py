"""
TEMPORARY — per-call AI cost ledger. models/ai_usage.py

Scheduled for deletion once credits and subscriptions land. See
`TEMPORARY-token-counter.md` at the repo root for the removal checklist, and
migration 011 for why it exists and why it is not meant to survive.

One row per billed provider call, written from the single seam every AI feature
already goes through (services/ai/generate.py). Nothing else should write here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AIUsage(Base):
    """A single billed call to an AI provider."""

    __tablename__ = "ai_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    #: The `context=` label from the generate_structured call site — "report_
    #: generation", "cross_question", "interview_plan". This IS the feature name;
    #: it is not derived or mapped, so the ledger cannot drift from the code.
    feature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    cost_tier: Mapped[str] = mapped_column(String(16), nullable=False)

    #: "ok" when the result was used, "discarded" when the call was billed and
    #: the result thrown away — malformed JSON, or a failed is_valid predicate.
    #: Discarded spend is real spend and is the most actionable number here.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Read from the prompt cache at ~0.1x input price.
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Written to the prompt cache at ~1.25x input price.
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: NUMERIC, not float — for exactness and determinism rather than because
    #: float "loses money"; the error at this scale is ~1e-15. It means a SUM is
    #: exactly the sum of the rows, and does not vary between runs when Postgres
    #: picks a parallel aggregate plan.
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("0")
    )

    #: Who the call was made for, when known. SET NULL on user delete: removing
    #: an account must not erase the fact that money was spent.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ai_usage_user_id"),
        nullable=True,
    )

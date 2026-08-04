"""
pgvector-backed cache for reusable AI generations — models/ai_cache.py

See migration 014 for the full rationale: why hashed lexical vectors rather than a
paid embeddings API, why Postgres rather than the existing Redis plan cache, and — the
part that matters most — which generations may and may not be cached here.

THE ONE RULE. Only generations whose input is public, topic-level data may be stored
with scope='global'. Anything derived from a specific candidate's ANSWERS must carry
their user id in `scope` and must never be served to anyone else. This app has already
shipped a bug that quoted one candidate's words at another; `scope` exists so that
constraint lives in the data rather than only in a reviewer's head.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

#: Value of `scope` for entries safe to share across every user.
GLOBAL_SCOPE = "global"

#: Dimensions of the hashed lexical vector. MUST match migration 014 and `embed()` in
#: services/ai/vector_cache.py — a mismatch is a runtime error from Postgres on every
#: insert, which is at least loud.
EMBEDDING_DIM = 512


class AICache(Base):
    """One cached AI generation, retrievable by near-match on its key."""

    __tablename__ = "ai_cache"
    __table_args__ = (
        # The vector search finds NEAR matches; this stops the degenerate case where
        # concurrent requests for the identical key each insert their own row.
        UniqueConstraint("feature", "key_hash", name="uq_ai_cache_feature_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    #: The `context=` label from the generate_structured call site — the same string
    #: the cost ledger uses, so hit rate and cost per feature join without a mapping.
    feature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    #: Human-readable key, kept for debugging a surprising hit. Bounded because it is
    #: user-influenced text.
    cache_key: Mapped[str] = mapped_column(String(500), nullable=False)
    #: SHA-256 of the normalised key: the exact-match fast path, and the uniqueness
    #: guarantee. The vector handles everything else.
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    #: GLOBAL_SCOPE, or a user id. See the rule in this module's docstring.
    scope: Mapped[str] = mapped_column(
        String(64), nullable=False, default=GLOBAL_SCOPE, server_default=GLOBAL_SCOPE
    )

    #: The generation, as the JSON the caller's Pydantic schema parses.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    #: Bumped on every hit. This is the "updates whenever anyone uses it" half: the
    #: cache warms itself from real traffic instead of needing a seed job, LRU
    #: eviction has something honest to sort on, and a table full of hit_count=1 rows
    #: is the signal that a feature was not worth caching.
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # NOTE: the `embedding vector(512)` column is created in migration 014 and is
    # deliberately NOT mapped here. SQLAlchemy has no native pgvector type without the
    # pgvector package, and every query that touches it needs raw SQL for the `<=>`
    # operator anyway. Mapping it as an opaque type would invite someone to SELECT it
    # by accident and ship 512 floats per row to Python for nothing.

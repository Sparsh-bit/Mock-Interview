"""
Where an account is being used from — models/security.py

Table: user_sessions

One row per (user, network prefix, browser fingerprint), upserted on every authenticated
request. The credential-sharing detector reads it; nothing else does.

WHY THIS IS A TABLE AND NOT REDIS. A ban is a moderation decision with an appeal attached,
and the evidence has to outlive a cache eviction and a restart. "We suspended you, and we no
longer have the record of why" is not a position to defend to somebody who has paid. Redis
still fronts the hot path — see services/security/sharing.py, which only touches Postgres
when something has actually changed — but the durable record lives here.

WHY A PREFIX AND NOT AN IP ADDRESS. Storing the exact address would be both more invasive
and less accurate. A phone moving between cell towers changes its address constantly inside
the same carrier range, and that single fact is the largest source of false positives in
any detector of this kind. The whole /24 (or /48 for IPv6) belongs to one network, so
comparing prefixes keeps the real signal — two different networks at once — and drops the
noise.

WHY THE USER AGENT IS HASHED. It is a browser fingerprint and it identifies a person.
Storing it in the clear buys nothing the hash does not: the detector only ever asks whether
two agents are the same, never what they are.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UUIDPrimaryKeyMixin


class UserSession(Base, UUIDPrimaryKeyMixin):
    """One place an account has been seen from."""

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    #: /24 for IPv4, /48 for IPv6. See the note above on why this is not the full address.
    ip_prefix: Mapped[str] = mapped_column(String(64), nullable=False)

    #: SHA-256 of the User-Agent header, truncated. Never the raw value.
    agent_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Upserted on every authenticated request, so without this the table would grow by
        # one row per request rather than one row per place.
        UniqueConstraint("user_id", "ip_prefix", "agent_hash", name="uq_user_sessions_identity"),
        # The detector's only read: this user's rows, most recent first.
        Index("ix_user_sessions_user_last_seen", "user_id", last_seen_at.desc()),
    )

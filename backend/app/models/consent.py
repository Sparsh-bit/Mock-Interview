"""
Consent — models/consent.py

An APPEND-ONLY LEDGER, deliberately shaped like `credit_events` rather than like a
set of boolean columns on `users`, for three reasons and one hard constraint.

The reasons:

  1. DPDP §6 asks for consent that is *specific* and *informed*, and §6(4)–(6) makes
     withdrawal as easy as giving. A boolean cannot answer "what exactly did they
     agree to, when, and against which version of the notice" — and consent you
     cannot evidence is consent you do not have. Every row here carries the purpose,
     the notice version and the timestamp.
  2. Withdrawal is a NEW ROW with `granted=False`, never an update. The history is
     the evidence; overwriting it destroys the only proof that the processing which
     already happened was lawful at the time.
  3. Age confirmation is just another purpose. §9 turns the under-18 question into a
     hard prohibition on behavioural monitoring, and this product measures speech
     pace, fillers, pauses and presence — so the answer has to be recorded, not
     inferred.

THE HARD CONSTRAINT, and the reason none of this is a column on `users`: the note in
models/user.py records that adding a mapped column before its migration has run took
the whole backend down, because SQLAlchemy names every mapped column in its SELECT
and `get_current_user` reads that table on every authenticated request. A new TABLE
has no such blast radius — nothing selects it until the code that uses it runs — so
the ledger is additive in the way that cannot break anything else.

`user_id` IS `ON DELETE SET NULL`, NOT CASCADE. See `services/legal/retention.py`:
erasure must not destroy the evidence that processing was consented to, any more
than it may destroy the financial ledger. The row survives de-identified, joined to
its siblings by `retained_subject`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin

#: The purposes consent is asked for. A closed set rather than free text, because a
#: typo'd purpose is a consent record that no query will ever find.
PURPOSE_TERMS = "terms"
PURPOSE_PRIVACY_NOTICE = "privacy_notice"
PURPOSE_AGE_18_PLUS = "age_18_plus"
PURPOSE_RESUME_PROCESSING = "resume_processing"
PURPOSE_CROSS_BORDER = "cross_border_transfer"

CONSENT_PURPOSES: frozenset[str] = frozenset(
    {
        PURPOSE_TERMS,
        PURPOSE_PRIVACY_NOTICE,
        PURPOSE_AGE_18_PLUS,
        PURPOSE_RESUME_PROCESSING,
        PURPOSE_CROSS_BORDER,
    }
)

#: Where the answer was given. Useful when a person asks "when did I agree to this?"
SOURCE_SIGNUP = "signup"
SOURCE_RESUME_UPLOAD = "resume_upload"
SOURCE_SETTINGS = "settings"


class ConsentEvent(Base, UUIDPrimaryKeyMixin):
    """One recorded answer to one consent question, at one moment."""

    __tablename__ = "consent_events"

    #: SET NULL rather than CASCADE — see the module docstring.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: Set only when the account is erased: a one-way digest of the user id, so the
    #: retained rows stay joinable to each other and to the retained financial
    #: ledger, and to nobody. Never populated for a live account.
    retained_subject: Mapped[str | None] = mapped_column(String(64), index=True)

    #: One of CONSENT_PURPOSES.
    purpose: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    #: False is a real, meaningful value — it is how withdrawal is recorded.
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)

    #: Which version of the notice this answer was given against. Without it, a
    #: later rewrite of the notice silently re-characterises what everybody agreed
    #: to, which is the precise thing §6 is trying to prevent.
    notice_version: Mapped[str] = mapped_column(String(32), nullable=False)

    #: SOURCE_* — the screen the answer was given on.
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )

    #: Room for what a later dispute needs without a migration. DELIBERATELY NOT an
    #: IP address or user agent: those are personal data in their own right, they are
    #: already in `audit_logs` with a defined retention, and duplicating them into a
    #: record that outlives the account would make erasure incomplete.
    detail: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        # The hot read: "what is this person's current answer for this purpose?",
        # which is the newest row for the pair. Runs on the resume-upload path.
        Index("ix_consent_events_user_purpose", "user_id", "purpose", "created_at"),
    )

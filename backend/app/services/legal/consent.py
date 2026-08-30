"""
Recording and reading consent — services/legal/consent.py

The only place consent is written or interpreted. Two functions matter:

  `record()` appends a row. It never updates one, because the history IS the
  evidence — a withdrawal that overwrote the grant would destroy the proof that the
  processing which already happened was lawful when it happened.

  `current()` answers "what does this person's newest row for this purpose say?".
  That is a different question from "is there a row", and getting it wrong in the
  easy direction — treating any row as consent — would make withdrawal do nothing.

WHAT THIS MODULE DOES NOT DO: decide whether an absent record blocks an action. That
is the caller's, because the answer differs by purpose. Missing resume consent stops
the upload; missing age confirmation on an account that predates this feature must
not lock a paying customer out of a product they already bought. See
`api/v1/legal.py` and the note on `require_consent`.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import CONSENT_PURPOSES, ConsentEvent
from app.services.legal.disclosure import NOTICE_VERSION

logger = structlog.get_logger(__name__)


class UnknownPurpose(ValueError):
    """A purpose outside CONSENT_PURPOSES. A typo here is a record nothing will find."""


async def record(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    purpose: str,
    granted: bool,
    source: str,
    notice_version: str = NOTICE_VERSION,
    detail: dict | None = None,
) -> ConsentEvent:
    """
    Append one consent answer.

    DOES NOT COMMIT. `get_db` commits on success and rolls back on any exception, so
    consent recorded alongside an action that then fails is rolled back with it —
    the same rule `credits.consume` follows, and for the same reason: a consent row
    for something that did not happen is a record that is not true.
    """
    if purpose not in CONSENT_PURPOSES:
        raise UnknownPurpose(f"{purpose!r} is not a known consent purpose")

    event = ConsentEvent(
        user_id=user_id,
        purpose=purpose,
        granted=granted,
        notice_version=notice_version,
        source=source,
        detail=detail,
    )
    db.add(event)
    await db.flush()

    logger.info(
        "consent_recorded",
        purpose=purpose,
        granted=granted,
        source=source,
        notice_version=notice_version,
    )
    return event


async def current(db: AsyncSession, user_id: uuid.UUID, purpose: str) -> ConsentEvent | None:
    """
    The newest answer for one purpose, or None if never asked.

    NEWEST, NOT ANY. Withdrawal is a later row with `granted=False`, so a query that
    returned the first match would report consent that has since been withdrawn —
    which is the failure mode §6(4)–(6) exists to prevent.
    """
    return await db.scalar(
        select(ConsentEvent)
        .where(ConsentEvent.user_id == user_id, ConsentEvent.purpose == purpose)
        .order_by(ConsentEvent.created_at.desc(), ConsentEvent.id.desc())
        .limit(1)
    )


async def has_granted(db: AsyncSession, user_id: uuid.UUID, purpose: str) -> bool:
    """True only when the newest answer is a grant. Never asked is not consent."""
    event = await current(db, user_id, purpose)
    return bool(event and event.granted)


async def summary(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """
    Every purpose and where it stands. Feeds both the settings screen and the export.

    Returns a row per KNOWN PURPOSE rather than per stored record, so a purpose that
    has never been asked appears as `null` instead of being absent — "we never asked
    you" and "you said no" are different answers and the UI must be able to tell
    them apart.
    """
    out: list[dict] = []
    for purpose in sorted(CONSENT_PURPOSES):
        event = await current(db, user_id, purpose)
        out.append(
            {
                "purpose": purpose,
                "granted": None if event is None else event.granted,
                "at": event.created_at.isoformat() if event else None,
                "notice_version": event.notice_version if event else None,
                "source": event.source if event else None,
            }
        )
    return out

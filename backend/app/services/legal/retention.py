"""
What survives erasure, and why — services/legal/retention.py

THE BUG THIS FIXES IS THAT DELETION WAS TOO COMPLETE.

`POST /users/me/delete` issued a core `DELETE FROM users`, and the database's
`ON DELETE CASCADE` took `credit_events` and `offer_redemptions` with it. Both are
financial records. The Companies Act, 2013 §128(5) requires books of account to be
kept for eight financial years, and a person exercising a right to erasure does not
switch that off — DPDP §8(7) is explicit that erasure yields to a retention
obligation under another law. So the previous behaviour destroyed records the
business is required to hold, and it did so silently, on a path a user can trigger
themselves.

DESTROYING THEM ALSO BREAKS THINGS THAT ARE NOT LEGAL AT ALL. `offer_redemptions`
carries the unique index that enforces one redemption per account; deleting the row
is a way to make a single-use code reusable. And a refund dispute six months later
has nothing left to reconcile against.

THE ANSWER IS NOT "KEEP EVERYTHING". Retaining a financial row that still names the
person is not erasure, it is a rename of the problem. So the rows are kept and the
identity is removed: `user_id` becomes NULL, and `retained_subject` gets a one-way
digest that keeps the surviving rows joinable to each other and to nothing else.
The amounts, dates and features remain — which is what the Companies Act asks for —
and the person does not.

`subject_digest` IS DELIBERATELY SALTED WITH A SERVER SECRET. An unsalted digest of
a UUID is reversible by anybody who has the id, which includes anyone holding an old
export, so it would be pseudonymisation in name only.

WHAT IS *NOT* RETAINED, and this is the more important half: the resume, its
extracted text, the stored file, every answer, every transcript, every score and
every report. Those are the sensitive data, they have no statutory retention, and
they go. `audit_logs` already had `ON DELETE SET NULL`, so it de-identifies itself
and keeps the 180 days CERT-In asks for.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, cast

import structlog
from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

#: Companies Act, 2013 §128(5) — eight financial years. Recorded as a constant so the
#: number appears once, and so the disclosure a candidate reads and the code that
#: enforces it cannot disagree. Nothing purges on this clock yet; see the note below.
FINANCIAL_RETENTION_YEARS = 8

#: CERT-In Directions, April 2022 — 180 days of logs.
SECURITY_LOG_RETENTION_DAYS = 180


def subject_digest(user_id: uuid.UUID) -> str:
    """
    A one-way handle for a deleted account.

    Salted with the JWT secret, which is server-side only and already required to
    exist. Without a salt, anybody holding the user id — an old data export, a stale
    log line — could confirm which retained rows were that person's, and the
    pseudonymisation would be decorative.
    """
    from app.core.config import settings  # noqa: PLC0415

    salt = settings.SUPABASE_JWT_SECRET or "unsalted"
    return hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()

#: Tables whose rows outlive the account, de-identified. Each entry is
#: (model import path attribute, human reason) and the reason is not decoration — it
#: is what a reviewer needs to judge whether the retention is justified.
RETAINED_TABLES: list[tuple[str, str]] = [
    ("credit_events", "Financial ledger — Companies Act §128(5), 8 financial years"),
    ("offer_redemptions", "Financial ledger, and the one-redemption-per-account record"),
    ("consent_events", "Evidence that the processing which already happened was consented to"),
]


async def deidentify_retained_records(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """
    Stamp the retained rows with a one-way subject handle, before the account goes.

    MUST RUN BEFORE THE `DELETE FROM users`, not after: once the row is gone the
    `ON DELETE SET NULL` has already fired, `user_id` is NULL, and there is nothing
    left to match on. Running it in the same transaction as the delete is what makes
    that ordering safe — `get_db` commits both or neither.

    Returns a count per table, which the caller logs. A zero is normal (a user who
    never paid); a count that changes when nothing else did is worth noticing.
    """
    from app.models.billing import CreditEvent, OfferRedemption  # noqa: PLC0415
    from app.models.consent import ConsentEvent  # noqa: PLC0415

    digest = subject_digest(user_id)
    counts: dict[str, int] = {}

    for model in (CreditEvent, OfferRedemption, ConsentEvent):
        result = await db.execute(
            update(model)
            .where(model.user_id == user_id)
            .values(retained_subject=digest)
            # `rowcount` is on CursorResult, and `execute` is typed as returning the
            # base Result. It is a CursorResult for a DML statement; the cast says so
            # rather than the count being dropped, because the count is the only
            # evidence in the log that the retention actually ran.
            .execution_options(synchronize_session=False)
        )
        counts[model.__tablename__] = cast("CursorResult[Any]", result).rowcount or 0

    logger.info("retained_records_deidentified", **counts)
    return counts

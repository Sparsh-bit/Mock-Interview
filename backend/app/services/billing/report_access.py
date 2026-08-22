"""
Who has to pay to read their report — services/billing/report_access.py

THE RULE, as the owner set it: "the free interview that we are giving do it for all that the
report is payable ... after that the candidate can purchase interviews from the software as it
was done before, the purchased interviews will not have the payment for the report generation."

So: a FREE interview produces a report that costs ₹49. A PURCHASED interview produces a report
that is included. The interview is never gated — only the report.

WHY THAT IS THE RIGHT SHAPE COMMERCIALLY, recorded because it is the thing a future change is
most likely to break. The free interview is the demo, and a demo has to be complete enough to
want more of. Gating the interview means nobody sees the product; gating the REPORT means
everybody sees the product and pays at the exact moment they most want the answer — having just
answered twelve questions and having no idea how they did. It also makes re-registering with a
new email pointless: it buys another free interview and still no report, which is a stronger
anti-abuse measure than anything in services/security/sharing.py.

────────────────────────────────────────────────────────────────────────────────────────────
IT FAILS OPEN. EVERYWHERE. WITHOUT EXCEPTION.
────────────────────────────────────────────────────────────────────────────────────────────

Every function here returns "not locked" when it cannot be certain. Missing session, missing
ledger row, unparseable metadata, a database error, an exception from anywhere — the report is
DELIVERED.

That is not defensive habit, it is the risk calculation. Locking a report that somebody has
already paid for is unrecoverable in the moment that matters: they finished an interview, they
are looking at a paywall for something they own, and the only person who can fix it is an
operator who is asleep. Failing the other way costs one report's revenue and nobody notices.
The asymmetry is enormous and it points one way.

This matters most for HISTORY. Every interview taken before `consume` began recording
`paid_with` has no marker at all, and reading absence as "free, therefore charge" would put a
paywall in front of every report already earned, retroactively, on deploy. It is the single
most likely way this feature could go badly wrong, and it is the case the code checks first.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.billing.plans import REPORT_UNLOCK_FEATURE, REPORT_UNLOCK_PRICE_PAISE

logger = structlog.get_logger(__name__)

#: What `consume` writes into `credit_events.detail` when a consumption came out of the free
#: trial allowance rather than purchased credit. See services/billing/credits.py.
_PAID_WITH_TRIAL = "trial"


@dataclass(frozen=True, slots=True)
class ReportAccess:
    """Whether this candidate may read this report, and what it costs if not."""

    locked: bool
    price_paise: int = REPORT_UNLOCK_PRICE_PAISE
    #: Why, for the log and for a support conversation. Never shown to the candidate.
    reason: str = ""


UNLOCKED = ReportAccess(locked=False, reason="delivered")


async def evaluate(
    db: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> ReportAccess:
    """
    May this user read this session's report?

    Never raises. Every failure path returns UNLOCKED — see the module note.

    THE TWO QUESTIONS, in the order that makes the cheap one first:

      1. Was this interview free? Read from the consumption row `consume` wrote for this
         session. No row, or no `paid_with` marker, means we cannot tell, which means we
         deliver. Only an explicit "trial" locks anything.
      2. Have they already unlocked it? A grant of REPORT_UNLOCK_FEATURE against this session.

    Both are queries over `credit_events`, which is the same ledger entitlement, receipts and
    the balance are all computed from — so a report's lock state cannot disagree with what the
    candidate's payment history says they bought.
    """
    from app.models.billing import CreditEvent  # noqa: PLC0415
    from app.services.billing.credits import (  # noqa: PLC0415
        KIND_CONSUME,
        KIND_GRANT,
        KIND_PURCHASE,
    )

    try:
        # 1. How was the interview itself paid for?
        detail = await db.scalar(
            select(CreditEvent.detail)
            .where(
                CreditEvent.user_id == user_id,
                CreditEvent.session_id == session_id,
                CreditEvent.kind == KIND_CONSUME,
                CreditEvent.feature == "interview",
            )
            .limit(1)
        )
        paid_with = (detail or {}).get("paid_with")

        if paid_with != _PAID_WITH_TRIAL:
            # Covers three cases and all three deliver: purchased credit, no consumption row at
            # all, and — the important one — a session from before `paid_with` existed.
            return ReportAccess(
                locked=False,
                reason=f"interview was not a free trial (paid_with={paid_with!r})",
            )

        # 2. It was free, so the report is payable — unless they have already bought it.
        unlocked = await db.scalar(
            select(CreditEvent.id)
            .where(
                CreditEvent.user_id == user_id,
                CreditEvent.session_id == session_id,
                CreditEvent.feature == REPORT_UNLOCK_FEATURE,
                CreditEvent.kind.in_([KIND_PURCHASE, KIND_GRANT]),
            )
            .limit(1)
        )
        if unlocked is not None:
            return ReportAccess(locked=False, reason="already unlocked")

        return ReportAccess(locked=True, reason="free interview, report not yet unlocked")

    except Exception as exc:  # noqa: BLE001
        # DELIVERED. A database hiccup must never present a paywall for something somebody may
        # already own. Logged with its reason, because a rising rate here means the lock is
        # silently not being applied and revenue is leaking — which is the failure worth
        # knowing about, and the one this direction chooses on purpose.
        logger.warning(
            "report_access_undetermined",
            user_id=str(user_id),
            session_id=str(session_id),
            error_type=type(exc).__name__,
            error=str(exc) or type(exc).__name__,
            consequence="report delivered unlocked",
        )
        return UNLOCKED

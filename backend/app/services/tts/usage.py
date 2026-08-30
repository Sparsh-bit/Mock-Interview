"""
Recording what speech costs — services/tts/usage.py

The TTS counterpart to `services/ai/usage.py`, deliberately the same shape and following the
same three rules, because the two feed one margin figure and a report should not have to
reconcile two different accounting styles before it can add them together.

THE THREE RULES, restated because they are what make this safe to put on the speech path:

1. IT NEVER BREAKS A REQUEST. Every path is wrapped. A missing table, an unreachable
   database, a bad column — none of it may turn a working group discussion into a 503.
   Accounting is strictly less important than the thing being accounted for, and speech is
   already the one feature in this product designed to degrade silently to browser voices.

2. IT WRITES ON ITS OWN CONNECTION. The characters were billed the moment the vendor
   answered. If the surrounding request later fails, the spend still happened and the row
   must survive.

3. IT RECORDS THE FREE ONES TOO. A cache hit costs nothing and is written at zero, because
   the hit rate is the entire speech economics of this product — `scripts/item_margin.py`
   shows the gap between an interview's margin and a group discussion's is exactly that an
   interview reads the same twelve questions to every candidate and a GD's turns are unique.
   A ledger of misses alone can measure the bill and can never measure what reduces it.

ONE SEAM, LIKE THE AI LEDGER. Every synthesised utterance in the product goes through
`POST /tts/speak`, so this is called from one place and instruments the whole feature.

WHY NOT JUST QUERY REDIS. `spend.py` is a per-UTC-day float with a 48-hour TTL and no
attribution at all. It is the budget brake and it must stay a brake — `_budget_room` runs
before every synthesis and must not acquire a database dependency. This is the record.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


def _enabled() -> bool:
    return bool(getattr(settings, "TTS_USAGE_LEDGER_ENABLED", False))


async def record_synthesis(
    *,
    provider: str,
    model: str,
    speaker: str,
    characters: int,
    cost_usd: float,
    cached: bool,
    user_id: uuid.UUID | None,
) -> None:
    """
    Write one utterance to the speech ledger. Best-effort, always.

    `cached=True` rows carry `cost_usd=0` and are the point of the table as much as the paid
    ones are — see rule 3 above.
    """
    if not _enabled():
        return

    # Deliberately broad, for the reason services/ai/usage.py gives: there is no failure mode
    # here worth propagating to somebody mid-interview, and enumerating every way a write can
    # fail would still miss one.
    try:
        from app.db.session import get_db_session  # noqa: PLC0415
        from app.models.tts_usage import TTSUsage  # noqa: PLC0415

        async with get_db_session() as db:
            db.add(
                TTSUsage(
                    provider=(provider or "unknown")[:32],
                    model=(model or "unknown")[:64],
                    speaker=(speaker or "")[:64],
                    characters=max(0, int(characters)),
                    cached=cached,
                    # str() before Decimal, not float(): Decimal(0.000123) carries the
                    # float's binary error into the stored value; Decimal("0.000123")
                    # stores the number that was meant.
                    cost_usd=Decimal(str(cost_usd or 0)),
                    user_id=user_id,
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — see rule 1
        logger.warning(
            "tts_usage_record_failed",
            provider=provider,
            error=type(exc).__name__,
            hint="ledger write only; the synthesis itself succeeded",
        )

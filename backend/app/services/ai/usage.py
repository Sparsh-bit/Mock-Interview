"""
TEMPORARY — recording what each AI feature costs. services/ai/usage.py

Scheduled for deletion once credits and subscriptions land; see
`TEMPORARY-token-counter.md` at the repo root.

ONE SEAM. Every AI-backed feature in the product already routes through
`generate_structured`, and that function already receives the two things a
ledger needs: a `context` label naming the feature, and a ProviderResponse
carrying token counts and an estimated cost. So this module is called from
exactly one place and instruments all twelve features without touching a single
call site.

THREE RULES THIS MODULE FOLLOWS.

1. It never breaks a request. Every path is wrapped: a missing table, an
   unreachable database, a bad column — none of it may turn a working interview
   into a 500. Accounting is strictly less important than the feature being
   accounted for, and a ledger that can take the product down is worse than no
   ledger.

2. It writes on its own connection, not the caller's session. The money was
   spent the moment the provider answered; if the surrounding request later
   rolls back — a validation error, a failed commit — the spend still happened
   and the row must survive. Sharing the caller's transaction would silently
   discard exactly the calls most worth recording.

3. It records discarded calls. A provider call that returned unparseable JSON was
   billed in full. Success-only accounting hides that, and it is the number that
   tells you a prompt is wrong rather than a feature being popular.
"""

from __future__ import annotations

import contextlib
import uuid
from contextvars import ContextVar
from decimal import Decimal

import structlog

from app.core.config import settings

from .base_provider import ProviderResponse

logger = structlog.get_logger(__name__)

#: The user the current request is being served for.
#:
#: A ContextVar rather than a parameter threaded through the call chain, because
#: `generate_structured` sits four or five frames below the endpoint and none of
#: the layers in between have any business knowing about a user. Set once in the
#: auth dependency, read once here. If it is unset — a background task, a cron
#: job, a test — the row is still written with a NULL user, which is honest: the
#: cost was real and unattributed.
current_user_id: ContextVar[uuid.UUID | None] = ContextVar("ai_usage_user_id", default=None)


def _enabled() -> bool:
    return bool(getattr(settings, "AI_USAGE_LEDGER_ENABLED", False))


async def record_call(
    *,
    feature: str,
    provider: str,
    response: ProviderResponse,
    cost_tier: str,
    outcome: str,
) -> None:
    """
    Write one billed provider call to the ledger. Best-effort, always.

    `outcome` is "ok" when the result was used and "discarded" when it was billed
    and thrown away.
    """
    if not _enabled():
        return

    # Deliberately broad. There is no failure mode here worth propagating to a
    # candidate mid-interview, and the alternative — enumerating every way a
    # write can fail — would still miss one.
    try:  # noqa: PLR1702
        from app.db.session import get_db_session  # noqa: PLC0415
        from app.models.ai_usage import AIUsage  # noqa: PLC0415

        cost = response.estimated_cost_usd
        async with get_db_session() as db:
            db.add(
                AIUsage(
                    feature=feature[:64],
                    provider=provider[:32],
                    model=(response.model or "unknown")[:64],
                    cost_tier=cost_tier[:16],
                    outcome=outcome[:16],
                    input_tokens=response.prompt_tokens or 0,
                    cached_input_tokens=response.cached_input_tokens or 0,
                    cache_write_tokens=response.cache_write_tokens or 0,
                    output_tokens=response.completion_tokens or 0,
                    # str() before Decimal, not float(): Decimal(0.000123)
                    # carries the float's binary error into the stored value,
                    # Decimal("0.000123") stores the number that was meant.
                    cost_usd=Decimal(str(cost)) if cost is not None else Decimal("0"),
                    user_id=current_user_id.get(),
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — see the docstring's rule 1
        logger.warning(
            "ai_usage_record_failed",
            feature=feature,
            error=type(exc).__name__,
            hint="ledger write only; the AI call itself succeeded",
        )


@contextlib.contextmanager
def attributed_to(user_id: uuid.UUID | None):
    """
    Attribute AI spend inside this block to `user_id`.

    Used by the auth dependency so every AI call made while serving a request is
    tagged with whoever made it, and by tests. Restores the previous value on
    exit so nested or concurrent requests cannot leak attribution into each
    other — a ContextVar is per-task, but resetting is what makes that true when
    the same task handles work for more than one user.
    """
    token = current_user_id.set(user_id)
    try:
        yield
    finally:
        current_user_id.reset(token)

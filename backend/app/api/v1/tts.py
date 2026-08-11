"""
Neural speech for the panel and the interviewer — api/v1/tts.py

Proxies one utterance to a TTS vendor and returns the audio. The browser plays it instead of
speechSynthesis, which is the single biggest change available to how this product feels.

THREE THINGS THIS ENDPOINT EXISTS TO DO, none of which the frontend could do alone:

  * KEEP THE KEY SERVER-SIDE. A browser calling ElevenLabs directly ships the API key in the
    bundle, where anyone can spend it.
  * METER IT. TTS is priced per CHARACTER, and on the Creator tier a GD round of neural
    speech costs about twelve times every AI call in that round put together (see the table
    in services/tts/base.py). It gets its own budget rather than sharing the AI one, because
    a character budget and a token budget are not interchangeable and one silently eating the
    other is how a bill becomes a surprise.
  * CACHE IT. The interview reads questions from a FIXED BANK — the same ~37 questions for
    every candidate — so after the first user, interview speech is nearly free. That is the
    single highest-value cache in the product and it only works server-side. GD panel turns
    are unique text and will never hit; that is expected, not a failure.

AND THE RULE FOR CALLERS: this is an enhancement. Every response that is not a 200 means
"use speechSynthesis instead", including 402 (budget spent) and 503 (vendor down). A TTS
outage must not be able to break a group discussion.
"""

from __future__ import annotations

import hashlib

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys, cache_get_bytes, cache_set_bytes
from app.services.tts.base import TONE_PROSODY, TTSBudgetExceededError, TTSError
from app.services.tts.factory import get_tts_provider, panel_voice_id
from app.services.tts.spend import record_tts_spend, tts_spend_today

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/tts", tags=["Speech"])

#: Per-user ceiling on synthesis requests. One GD round is up to ~40 utterances and an
#: interview ~16, so 200/hour covers several rounds and still stops a loop from spending a
#: month's character allowance in an afternoon.
_tts_rate_limit = rate_limiter(
    limit=settings.TTS_RATE_LIMIT_PER_HOUR,
    window_seconds=3600,
    key_builder=lambda user_id: CacheKeys.rate_limit_tts(user_id),
    action="generating speech",
)

#: Longest utterance accepted. A panel contribution is one to three sentences by prompt
#: rule; anything far past that is a caller bug or an attempt to burn the budget, and at
#: per-character pricing the difference is money rather than milliseconds.
_MAX_CHARS = 600


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=_MAX_CHARS)
    #: A panelist name ("Riya") or "interviewer". Resolved to a vendor voice id SERVER-side,
    #: so a client cannot select an arbitrary voice — which on a metered vendor is both a
    #: cost and a correctness question, since it is what keeps Meera female.
    speaker: str = Field(min_length=1, max_length=64)
    #: How to deliver it — see TONE_PROSODY in services/tts/base.py. A NAME, not numbers:
    #: prosody is billable (speed 0.1 on a long line is a minute of audio charged to the
    #: daily budget) and there is no reason a browser should hold that dial. An unrecognised
    #: name resolves to neutral rather than 422, because a client on an older bundle sending
    #: a tone this deploy does not know must still get audio.
    tone: str | None = Field(default=None, max_length=32)


def _cache_key(provider: str, voice_id: str, text: str, tone: str) -> str:
    """
    Exact-match key. Deliberately NOT the semantic cache used for generations.

    Audio must be byte-identical to what was asked for: a near-match would play a candidate
    a different sentence from the one on their screen. Provider and voice are in the key
    because the same text in a different voice is different audio.

    TONE IS IN THE KEY for exactly the same reason. "That is not right" delivered as a
    correction and the same words delivered flat are different audio, and leaving tone out
    would mean the first delivery of a line wins for a fortnight — so a correction spoken
    once in a neutral context would be served back, flat, to every candidate who got it
    wrong afterwards. That is the bug the tone work exists to fix, cached.
    """
    digest = hashlib.sha256(
        f"{provider}|{voice_id}|{tone}|{text.strip()}".encode()
    ).hexdigest()
    return CacheKeys.tts_audio(digest)


@router.post(
    "/speak",
    dependencies=[Depends(_tts_rate_limit)],
    summary="Synthesise one utterance (falls back to browser speech on any error)",
    responses={
        200: {"content": {"audio/mpeg": {}}, "description": "Audio for this utterance"},
        402: {"description": "Daily character budget spent — use browser speech"},
        503: {"description": "TTS unavailable — use browser speech"},
    },
)
async def speak(request: SpeakRequest, current_user: CurrentUser) -> Response:
    if not settings.TTS_ENABLED:
        # 503 rather than 404: the client's handling is identical either way ("use the
        # browser"), and a 404 would look like a deploy problem rather than a setting.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "TTS is disabled")

    text = request.text.strip()
    voice_id = panel_voice_id(request.speaker)
    if not voice_id:
        logger.warning("tts_unknown_speaker", speaker=request.speaker)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No voice for that speaker")

    try:
        provider = get_tts_provider()
    except TTSError as exc:
        logger.warning("tts_provider_unavailable", error=str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    tone = request.tone if request.tone in TONE_PROSODY else "neutral"
    key = _cache_key(provider.provider_name, voice_id, text, tone)

    # Cache first, and before the budget check — a hit costs nothing, so a spent budget must
    # not stop it being served. This is what makes the fixed question bank nearly free.
    cached = await cache_get_bytes(key)
    if cached is not None:
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers={"X-TTS-Cache": "hit", "Cache-Control": "private, max-age=86400"},
        )

    spent = await tts_spend_today()
    if settings.TTS_DAILY_BUDGET_USD > 0 and spent >= settings.TTS_DAILY_BUDGET_USD:
        logger.error(
            "tts_daily_budget_exceeded",
            spent_usd=round(spent, 4),
            budget_usd=settings.TTS_DAILY_BUDGET_USD,
        )
        # 402 rather than 429: nothing about waiting will help, the budget resets at
        # midnight UTC. The client treats both the same way, but the logs should not.
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, "Speech budget for today is spent"
        )

    try:
        result = await provider.synthesize(text, voice_id=voice_id, tone=tone)
    except TTSBudgetExceededError as exc:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(exc)) from exc
    except TTSError as exc:
        logger.warning("tts_synthesis_failed", speaker=request.speaker, error=str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    await record_tts_spend(result.estimated_cost_usd)
    await cache_set_bytes(key, result.audio, ttl_seconds=settings.TTS_CACHE_TTL_SECONDS)

    logger.info(
        "tts_synthesised",
        speaker=request.speaker,
        tone=tone,
        provider=result.provider,
        characters=result.characters,
        cost_usd=round(result.estimated_cost_usd, 6),
    )
    return Response(
        content=result.audio,
        media_type=result.content_type,
        headers={"X-TTS-Cache": "miss", "Cache-Control": "private, max-age=86400"},
    )


class TTSStatus(BaseModel):
    enabled: bool
    provider: str | None
    #: So the client can decide whether to even try, and show the round is on browser voices.
    budget_remaining_usd: float
    voices: dict[str, bool]


@router.get("/status", summary="Is neural speech available right now?")
async def tts_status(current_user: CurrentUser) -> TTSStatus:
    """
    Lets the client skip the round trip when TTS is off or spent, rather than learning it
    from a 503 on the first contribution of every round.
    """
    if not settings.TTS_ENABLED:
        return TTSStatus(enabled=False, provider=None, budget_remaining_usd=0.0, voices={})

    try:
        provider_name: str | None = get_tts_provider().provider_name
    except TTSError:
        provider_name = None

    spent = await tts_spend_today()
    remaining = max(0.0, settings.TTS_DAILY_BUDGET_USD - spent)
    from app.services.tts.factory import configured_voices  # noqa: PLC0415

    return TTSStatus(
        enabled=provider_name is not None and remaining > 0,
        provider=provider_name,
        budget_remaining_usd=round(remaining, 4),
        # Which speakers actually have a voice id configured. A panelist without one falls
        # back to the browser individually, which is better than the whole round doing so.
        voices=configured_voices(),
    )

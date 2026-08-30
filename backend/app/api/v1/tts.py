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
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys, cache_get_bytes, cache_set_bytes
from app.services.tts.base import (
    TONE_PROSODY,
    StreamingTTSProvider,
    TTSBudgetExceededError,
    TTSError,
    prosody_for,
)
from app.services.tts.factory import get_tts_provider, panel_voice_id
from app.services.tts.spend import record_tts_spend, tts_spend_today
from app.services.tts.usage import record_synthesis

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


def _cache_key(provider: str, voice_id: str, text: str, tone: str, speed: float) -> str:
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

    SO IS THE RESOLVED SPEED, and it is in the key as a NUMBER rather than as the speaker's
    name on purpose. Speed is what actually differs in the bytes; the name is only how it was
    chosen. Keying on the number means two speakers who happen to share a voice id and a pace
    — Anil and the `interviewer` fallback do exactly that — correctly share one cache entry
    instead of synthesising the same audio twice, while any future per-speaker pace splits
    them automatically. Keying on the name would lose the sharing; keying on neither would
    serve one speaker's pace to the other, which is the bug this argument exists to prevent.
    """
    digest = hashlib.sha256(
        f"{provider}|{voice_id}|{tone}|{speed}|{text.strip()}".encode()
    ).hexdigest()
    return CacheKeys.tts_audio(digest)


async def _budget_room() -> tuple[bool, float]:
    """
    Is there speech budget left today, and how much?

    ONE FUNCTION FOR BOTH ENDPOINTS, BECAUSE THEY DISAGREED — and the disagreement silently
    turned neural speech off.

    `TTS_DAILY_BUDGET_USD` is documented as "0 disables the cap", and `/speak` implemented
    exactly that: `if budget > 0 and spent >= budget`. `/status` did not. It computed
    `remaining = max(0.0, budget - spent)`, which is 0.0 when the budget is 0, and then
    reported `enabled = provider is not None and remaining > 0` — so setting the value that
    means "no limit" made the status endpoint say TTS was unavailable.

    That is worse than either behaviour on its own, because the client asks `/status` ONCE per
    round and, told no, correctly never calls `/speak` at all. So the endpoint that would have
    allowed the request was never reached, and the vendor dashboard showed zero requests while
    the account was funded and every setting looked right. Nothing logged, nothing failed.

    Two endpoints reading one setting two ways is not a bug you fix by making the conditionals
    match; it is a bug you fix by there being one conditional. Hence this.

    Returns `(has_room, remaining_usd)`. `remaining_usd` is **-1.0 when uncapped**, which is
    deliberately not a plausible amount of money: a caller that forgets what it means will
    produce something obviously wrong rather than something quietly wrong, and 0.0 would mean
    "exhausted" — the exact confusion this function exists to end.
    """
    cap = settings.TTS_DAILY_BUDGET_USD
    spent = await tts_spend_today()
    if cap <= 0:
        return True, -1.0
    return spent < cap, max(0.0, cap - spent)


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
    # Resolved here as well as inside the provider so the cache key reflects the delivery
    # that will actually be synthesised. prosody_for is pure and total — it falls back to
    # neutral for an unknown tone or speaker rather than raising — so this cannot fail.
    speed = prosody_for(tone, request.speaker)["speed"]
    key = _cache_key(provider.provider_name, voice_id, text, tone, speed)

    # Cache first, and before the budget check — a hit costs nothing, so a spent budget must
    # not stop it being served. This is what makes the fixed question bank nearly free.
    cached = await cache_get_bytes(key)
    if cached is not None:
        # A HIT IS RECORDED, AT ZERO, AND IT IS THE MOST VALUABLE ROW IN THE TABLE.
        #
        # scripts/item_margin.py shows the entire margin gap between an interview and a group
        # discussion is that an interview reads the same twelve bank questions to every
        # candidate — one shared cache entry — while every GD turn is unique text that can
        # never hit. So the hit rate IS the speech economics, and a ledger of misses alone
        # could measure the bill and never measure the thing that reduces it.
        #
        # `characters` is the length of what WOULD have been synthesised, so "characters
        # avoided" is a real figure rather than a zero row with no size.
        await record_synthesis(
            provider=provider.provider_name,
            model=getattr(provider, "_model", ""),
            speaker=request.speaker,
            characters=len(text),
            cost_usd=0.0,
            cached=True,
            user_id=current_user.user_id,
        )
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers={"X-TTS-Cache": "hit", "Cache-Control": "private, max-age=86400"},
        )

    has_room, _remaining = await _budget_room()
    if not has_room:
        logger.error(
            "tts_daily_budget_exceeded",
            spent_usd=round(await tts_spend_today(), 4),
            budget_usd=settings.TTS_DAILY_BUDGET_USD,
        )
        # 402 rather than 429: nothing about waiting will help, the budget resets at
        # midnight UTC. The client treats both the same way, but the logs should not.
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, "Speech budget for today is spent"
        )

    try:
        result = await provider.synthesize(
            text, voice_id=voice_id, tone=tone, speaker=request.speaker
        )
    except TTSBudgetExceededError as exc:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(exc)) from exc
    except TTSError as exc:
        logger.warning("tts_synthesis_failed", speaker=request.speaker, error=str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    # TWO WRITES, TWO PURPOSES, AND THEY ARE NOT REDUNDANT.
    #
    # `record_tts_spend` is the BRAKE: a Redis float for today, read by `_budget_room` before
    # every synthesis, deliberately with no database dependency because a money guard that
    # fails open when Postgres is slow is a money guard that does not exist.
    #
    # `record_synthesis` is the RECORD: one durable row, attributed, that a margin figure can
    # be built from. The Redis counter cannot do that job — it has a 48-hour TTL and one
    # number for everybody — which is why /admin/revenue could only ever report gross.
    await record_tts_spend(result.estimated_cost_usd)
    await record_synthesis(
        provider=result.provider,
        model=getattr(provider, "_model", ""),
        speaker=request.speaker,
        characters=result.characters,
        cost_usd=result.estimated_cost_usd,
        cached=False,
        user_id=current_user.user_id,
    )
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
    #: WHY it is off, for an ADMIN only. Empty for everybody else and whenever it is on.
    #:
    #: THIS EXISTS BECAUSE ITS ABSENCE COST HOURS. `enabled: False` was returned identically
    #: for four completely different causes — TTS switched off, no API key, a retired model
    #: name, and a spent daily budget — and the endpoint swallowed the provider's own
    #: exception message on the way past. So an operator with a funded account, a valid key
    #: and correct voice ids heard browser speech and had nothing anywhere to read: the
    #: vendor dashboard showed zero requests because the client, told `enabled: false`, had
    #: correctly stopped asking.
    #:
    #: ADMIN ONLY, and that is not caution for its own sake. "FISH_API_KEY is not set" names
    #: the vendor and admits a misconfiguration, which is exactly the deployment detail this
    #: product was told to keep out of the browser. The operator needs it; a candidate must
    #: not have it. It is also logged server-side regardless, which is where it belongs.
    reason: str = ""


@router.get("/status", summary="Is neural speech available right now?")
async def tts_status(current_user: CurrentUser) -> TTSStatus:
    """
    Lets the client skip the round trip when TTS is off or spent, rather than learning it
    from a 503 on the first contribution of every round.
    """
    # `reason` is filled on every path that returns enabled=False, and shown only to an
    # admin. See the field's note: four different causes used to be indistinguishable here,
    # including from the operator.
    # FROM THE CONTEXTVAR, NOT FROM `current_user`. AuthenticatedUser carries id, supabase_uid
    # and email and NOT is_admin — every other admin check in this codebase does a separate
    # `select(User.is_admin)`. A `getattr(current_user, "is_admin", False)` here would
    # therefore be False for everybody, always, and the reason would be invisible to the one
    # person who needs it while looking like it worked. The contextvar is set by the auth
    # dependency on every authenticated request and costs nothing to read.
    from app.services.ai.usage import current_user_is_admin  # noqa: PLC0415

    is_admin = bool(current_user_is_admin.get())

    def _for(reason: str) -> str:
        return reason if is_admin else ""

    if not settings.TTS_ENABLED:
        return TTSStatus(
            enabled=False,
            provider=None,
            budget_remaining_usd=0.0,
            voices={},
            reason=_for("TTS_ENABLED is false"),
        )

    provider_name: str | None = None
    failure = ""
    try:
        provider_name = get_tts_provider().provider_name
    except TTSError as exc:
        # LOGGED AT ERROR, AND THIS ONE GENUINELY IS ONE. Everywhere else in this codebase a
        # degradation to browser speech is logged at info, because a spent budget or a vendor
        # outage is a normal operating state. This is different: TTS_ENABLED is true, so the
        # operator has asked for neural speech and the provider cannot be built at all. That
        # is a misconfiguration, it will not fix itself, and every round until it is fixed is
        # silently worse. It must be loud in the logs.
        failure = str(exc) or type(exc).__name__
        logger.error(
            "tts_provider_unavailable",
            reason=failure,
            provider=settings.TTS_PROVIDER,
            model=settings.FISH_MODEL if settings.TTS_PROVIDER == "fish" else None,
            hint="TTS_ENABLED is true but no provider could be constructed",
        )

    has_room, remaining = await _budget_room()
    from app.services.tts.factory import configured_voices  # noqa: PLC0415

    if provider_name is not None and not has_room:
        spent = await tts_spend_today()
        failure = (
            f"daily TTS budget spent: ${spent:.4f} of "
            f"${settings.TTS_DAILY_BUDGET_USD:.2f} (TTS_DAILY_BUDGET_USD)"
        )
        logger.info("tts_budget_spent", spent_usd=round(spent, 4))

    return TTSStatus(
        enabled=provider_name is not None and has_room,
        provider=provider_name,
        budget_remaining_usd=round(remaining, 4),
        # Which speakers actually have a voice id configured. A panelist without one falls
        # back to the browser individually, which is better than the whole round doing so.
        voices=configured_voices(),
        reason=_for(failure),
    )


@router.post(
    "/speak/stream",
    dependencies=[Depends(_tts_rate_limit)],
    summary="Speak one line, streamed so playback can start on the first chunk",
)
async def speak_stream(request: SpeakRequest, current_user: CurrentUser) -> StreamingResponse:
    """
    The same audio as POST /speak, delivered as it is made — where the vendor can do that.

    WHAT THIS IS WORTH, AND WHERE. A panel turn is up to four spoken lines and the candidate
    waits for each whole file before hearing anything. Starting playback on the first chunk
    removes the synthesis time of the line rather than of the turn, which is the part a person
    experiences as the room being slow to speak.

    THE TWO VENDORS ARE NOT THE SAME AND ARE NOT TREATED AS THE SAME. This checks
    `isinstance(provider, StreamingTTSProvider)` — ElevenLabs implements it, Fish does not,
    and `services/tts/fish.py` records why at length. On Fish, which is the DEFAULT vendor,
    this endpoint synthesises the whole file and sends it as a single chunk: the same bytes,
    the same cost, the same first-byte time as today, and a response the client does not have
    to special-case. `X-TTS-Streamed` says which happened, so "is it actually streaming?" is
    answerable from a response header rather than from reading the deployment config.

    NOTHING IS RECORDED OR CACHED UNTIL THE AUDIO IS COMPLETE, and that ordering is the whole
    safety argument. A stream cut halfway has produced playable audio — the candidate heard
    part of a sentence — and writing that to the cache would freeze a truncated line in place
    for a day, so every candidate asked the same question would hear it cut off in the same
    place. So the ledger write, the spend write and the cache write all happen after the last
    chunk, together, or none of them happens. `tests/test_tts_stream.py` pins that.

    The candidate's own experience of a cut stream is unchanged from any other speech failure:
    they hear part of a line, the browser's fallback carries the rest, and the interview
    continues.
    """
    if not settings.TTS_ENABLED:
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
    speed = prosody_for(tone, request.speaker)["speed"]
    key = _cache_key(provider.provider_name, voice_id, text, tone, speed)

    # Cache first and before the budget check, for the reason `speak` gives: a hit costs
    # nothing, so a spent budget must not stop it being served.
    cached = await cache_get_bytes(key)
    if cached is not None:
        await record_synthesis(
            provider=provider.provider_name,
            model=getattr(provider, "_model", ""),
            speaker=request.speaker,
            characters=len(text),
            cost_usd=0.0,
            cached=True,
            user_id=current_user.user_id,
        )

        async def _cached() -> AsyncIterator[bytes]:
            yield cached

        return StreamingResponse(
            _cached(),
            media_type="audio/mpeg",
            headers={"X-TTS-Cache": "hit", "X-TTS-Streamed": "cache", "Cache-Control": "no-cache"},
        )

    has_room, _remaining = await _budget_room()
    if not has_room:
        logger.error(
            "tts_daily_budget_exceeded",
            spent_usd=round(await tts_spend_today(), 4),
            budget_usd=settings.TTS_DAILY_BUDGET_USD,
        )
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, "Speech budget for today is spent"
        )

    # `isinstance` against a runtime_checkable Protocol, not a config flag: the answer is a
    # property of the vendor class, and reading it from settings would let the two disagree
    # after a TTS_PROVIDER change.
    streaming = isinstance(provider, StreamingTTSProvider)

    async def audio() -> AsyncIterator[bytes]:
        chunks: list[bytes] = []
        try:
            if isinstance(provider, StreamingTTSProvider):
                async for chunk in provider.synthesize_stream(
                    text, voice_id=voice_id, tone=tone, speaker=request.speaker
                ):
                    chunks.append(chunk)
                    yield chunk
                # ESTIMATED FROM THE CHARACTER COUNT, which is exactly how these vendors bill
                # — per character, not per byte — so this is the same figure `synthesize`
                # reports rather than an approximation of it.
                cost = provider.estimate_cost_usd(len(text))
            else:
                # GRACEFUL DEGRADATION, and the common case: Fish is the default vendor. One
                # chunk, the whole file, identical to POST /speak in every respect including
                # when the first byte arrives.
                result = await provider.synthesize(
                    text, voice_id=voice_id, tone=tone, speaker=request.speaker
                )
                chunks.append(result.audio)
                cost = result.estimated_cost_usd
                yield result.audio
        except TTSError as exc:
            # NOTHING IS RECORDED AND NOTHING IS CACHED. The status is already 200 and some
            # audio may already be playing, so this cannot become an HTTP error — the stream
            # simply ends, which the browser's audio element reports as a decode or network
            # failure and the client handles the way it handles any other speech failure.
            logger.warning(
                "tts_stream_failed",
                speaker=request.speaker,
                streamed=streaming,
                bytes_sent=sum(len(c) for c in chunks),
                error=str(exc) or type(exc).__name__,
            )
            return

        # ONLY NOW. Complete audio, so it is worth billing, worth recording and worth keeping.
        whole = b"".join(chunks)
        await record_tts_spend(cost)
        await record_synthesis(
            provider=provider.provider_name,
            model=getattr(provider, "_model", ""),
            speaker=request.speaker,
            characters=len(text),
            cost_usd=cost,
            cached=False,
            user_id=current_user.user_id,
        )
        await cache_set_bytes(key, whole, ttl_seconds=settings.TTS_CACHE_TTL_SECONDS)
        logger.info(
            "tts_synthesised",
            speaker=request.speaker,
            tone=tone,
            provider=provider.provider_name,
            characters=len(text),
            cost_usd=round(cost, 6),
            streamed=streaming,
        )

    return StreamingResponse(
        audio(),
        media_type="audio/mpeg",
        headers={
            "X-TTS-Cache": "miss",
            "X-TTS-Streamed": "vendor" if streaming else "whole",
            # Never cached by the browser: the body is only complete if the stream finished,
            # and a truncated response cached by an intermediary would be a silently broken
            # line served for as long as it lived.
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )

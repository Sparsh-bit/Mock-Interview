"""
ElevenLabs text-to-speech — services/tts/elevenlabs.py

The best-sounding option and by far the most expensive; see the cost table in base.py before
choosing it. What it buys over Azure or Google is delivery — a voice that sounds like a
person with an attitude rather than a newsreader — which for a panel of three named
characters arguing with each other is the part that matters most.

WHICH MODEL. `eleven_flash_v2_5` by default, not `eleven_multilingual_v2`:

  * it bills at HALF the credits per character, which on the numbers in base.py is the
    difference between 12x and 4.5x the round's AI cost
  * its latency is around 75ms against several hundred, and this sits in the middle of a
    live discussion where every panel turn already waits on the model

Multilingual v2 is richer and is the right choice for something pre-rendered. In a round
where a candidate is waiting for someone to finish speaking, fast wins.

STREAMING IS DELIBERATELY NOT USED. ElevenLabs can stream audio, and for a single long
narration that is clearly better. Here each utterance is one or two sentences — a couple of
seconds of audio — so the whole file arrives in roughly the time the first chunk would, and
a complete buffer means the client gets an exact `ended` event to hand the microphone back
on. That event is what makes the hands-free round work, and it is more reliable than
anything speechSynthesis provides.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import structlog

from app.services.tts.base import SynthesisResult, TTSError

logger = structlog.get_logger(__name__)

_API = "https://api.elevenlabs.io/v1/text-to-speech"

#: Credits per character, by model. ElevenLabs bills credits, and the Flash and Turbo v2.5
#: models are half price per character — which is most of why Flash is the default.
_CREDITS_PER_CHAR = {
    "eleven_flash_v2_5": 0.5,
    "eleven_turbo_v2_5": 0.5,
    "eleven_multilingual_v2": 1.0,
    "eleven_monolingual_v1": 1.0,
}

#: USD per credit, from the subscription tier. A plan is a fixed monthly fee for a credit
#: allowance, so the true marginal cost is the allowance divided by the fee — and it varies
#: nearly twofold across tiers, which is enough to change decisions.
#:
#:   Creator  $22/100k    = $0.000220
#:   Pro      $99/500k    = $0.000198
#:   Scale    $330/2M     = $0.000165
#:   Business $1320/11M   = $0.000120
#:
#: VERIFY THIS AGAINST YOUR OWN INVOICE before trusting a projection built on it. Vendor
#: pricing moves, and this only exists so spend is observable without opening their console.
_USD_PER_CREDIT_BY_TIER = {
    "free": 0.0,
    "starter": 5 / 30_000,
    "creator": 22 / 100_000,
    "pro": 99 / 500_000,
    "scale": 330 / 2_000_000,
    "business": 1_320 / 11_000_000,
}


class ElevenLabsProvider:
    """One ElevenLabs account, one model, many voices."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "eleven_flash_v2_5",
        tier: str = "creator",
        timeout: float = 12.0,
    ) -> None:
        if not api_key:
            raise TTSError("ELEVENLABS_API_KEY is not set")
        self._key = api_key
        self._model = model
        # Falls back to the priciest per-credit tier on an unknown name, so a typo
        # over-estimates spend rather than under-estimating it. A budget that reads low is
        # worse than one that reads high.
        self._usd_per_credit = _USD_PER_CREDIT_BY_TIER.get(
            tier.lower(), _USD_PER_CREDIT_BY_TIER["creator"]
        )
        self._credits_per_char = _CREDITS_PER_CHAR.get(model, 1.0)
        # Short on purpose. This sits in a live discussion, and a caller waiting twelve
        # seconds for speech should have fallen back to the browser long before.
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "elevenlabs"

    def estimate_cost_usd(self, characters: int) -> float:
        return characters * self._credits_per_char * self._usd_per_credit

    async def synthesize_stream(
        self, text: str, *, voice_id: str, tone: str | None = None, speaker: str | None = None
    ) -> AsyncIterator[bytes]:
        """
        The same audio as `synthesize`, chunked, from ElevenLabs' `/stream` endpoint.

        SAME BODY, SAME MODEL, SAME VOICE SETTINGS — only the URL differs, so a streamed line
        and a whole one are the same audio and cannot come out sounding different. The vendor
        bills identically; what changes is that the first bytes arrive while the rest is still
        being generated, which is most of a second on a four-line panel turn.

        UNVERIFIED AGAINST A LIVE KEY IN THIS REPOSITORY — none is configured here — so this
        is written from the published contract. `services/tts/base.StreamingTTSProvider` says
        what that means and why the fallback matters: a caller that cannot stream falls back
        to `synthesize`, which is a slower first byte and identical audio.
        """
        clean = (text or "").strip()
        if not clean:
            raise TTSError("nothing to speak")
        if not voice_id:
            raise TTSError("no voice_id for this speaker")

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client, client.stream(
                "POST",
                f"{_API}/{voice_id}/stream",
                headers={
                    "xi-api-key": self._key,
                    "accept": "audio/mpeg",
                    "content-type": "application/json",
                },
                json={
                    "text": clean,
                    "model_id": self._model,
                    "voice_settings": {
                        "stability": 0.45,
                        "similarity_boost": 0.75,
                        "style": 0.35,
                        "use_speaker_boost": True,
                    },
                },
            ) as resp:
                if resp.status_code != 200:
                    # READ BEFORE RAISING. On a streaming response the body has not been
                    # fetched yet, so `resp.text` would be empty and the error would say
                    # nothing — which is the failure mode the Fish provider's comments
                    # describe at length.
                    detail = (await resp.aread())[:200].decode("utf-8", "replace")
                    logger.warning(
                        "elevenlabs_stream_failed", status=resp.status_code, detail=detail
                    )
                    raise TTSError(f"elevenlabs returned {resp.status_code}: {detail}")
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            # The type as well as the message: httpx raises ReadTimeout with an empty string,
            # and a log line reading "request failed: " cost a long diagnosis once already.
            raise TTSError(
                f"elevenlabs stream failed: {exc or type(exc).__name__}"
            ) from exc

    async def synthesize(
        self, text: str, *, voice_id: str, tone: str | None = None, speaker: str | None = None
    ) -> SynthesisResult:
        # Accepted and ignored. ElevenLabs has no per-request speed control on the v1
        # endpoint — delivery comes from the voice settings on the voice itself — so rather
        # than fake it with stability nudges that do something else entirely, this provider
        # simply speaks flat. Signature parity is what keeps `tone` from being a Fish-only
        # concept that the caller has to know about.
        clean = (text or "").strip()
        if not clean:
            raise TTSError("nothing to speak")
        if not voice_id:
            raise TTSError("no voice_id for this speaker")

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{_API}/{voice_id}",
                    headers={
                        "xi-api-key": self._key,
                        "accept": "audio/mpeg",
                        "content-type": "application/json",
                    },
                    json={
                        "text": clean,
                        "model_id": self._model,
                        # Tuned for argument rather than narration. Lower stability leaves
                        # more variation between deliveries, which is what stops three
                        # panelists sounding like one reader; style adds emphasis. Both are
                        # kept moderate because at the extremes the voice starts inventing
                        # emotion the text does not carry.
                        "voice_settings": {
                            "stability": 0.45,
                            "similarity_boost": 0.75,
                            "style": 0.35,
                            "use_speaker_boost": True,
                        },
                    },
                )
        except httpx.HTTPError as exc:
            raise TTSError(f"elevenlabs request failed: {exc}") from exc

        if resp.status_code != 200:
            # The body carries the real reason — quota exhausted, unknown voice, bad key —
            # and truncating it to 200 characters keeps a whole error page out of the logs.
            detail = resp.text[:200]
            logger.warning(
                "elevenlabs_synthesis_failed", status=resp.status_code, detail=detail
            )
            raise TTSError(f"elevenlabs returned {resp.status_code}: {detail}")

        characters = len(clean)
        return SynthesisResult(
            audio=resp.content,
            content_type=resp.headers.get("content-type", "audio/mpeg"),
            characters=characters,
            estimated_cost_usd=self.estimate_cost_usd(characters),
            provider=self.provider_name,
            voice_id=voice_id,
        )

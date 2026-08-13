"""
Fish Audio text-to-speech — services/tts/fish.py

WHY THIS ONE. The product is Indian campus placement practice, and Fish Audio's model
catalogue has a genuine supply of Indian-English voices — searched live and verified:
"Indian English Accent" tagged male/professional, "Indian Female", "Clear Indian Male",
"Warm Indian Female". For a candidate rehearsing a Cognizant panel, an interviewer who
sounds like an interviewer they will actually meet is worth more than a technically superior
American voice.

It is also far cheaper per character than ElevenLabs, which matters: see the cost table in
base.py for why speech, not the model, is what would dominate this product's bill.

CREDIT IS SEPARATE FROM PLATFORM CREDIT. Verified against the live API with a real key: a
valid, authenticating key with no API credit returns HTTP 402 and a message pointing at
fish.audio/app/developers. That is a distinct condition from a bad key, and it is mapped to
TTSBudgetExceededError rather than a generic failure so the caller can tell "top up" apart
from "something is broken" — the two need completely different responses.

REFERENCE_ID IS THE VOICE. Fish calls a voice a "model", identified by a 32-character hex id
from the catalogue. Those ids are account- and catalogue-specific, so they live in the
environment (TTS_VOICE_IDS) rather than the repo, exactly as the ElevenLabs voice ids do.
"""

from __future__ import annotations

import httpx
import structlog

from app.services.tts.base import (
    SynthesisResult,
    TTSBudgetExceededError,
    TTSError,
    prosody_for,
)

logger = structlog.get_logger(__name__)

_API = "https://api.fish.audio/v1/tts"

#: USD per character, approximate.
#:
#: Fish prices per million UTF-8 bytes rather than per character, and the two differ for
#: non-ASCII text — negligible for English interview questions, and this figure exists only
#: so spend is observable without opening their dashboard. VERIFY AGAINST YOUR OWN INVOICE
#: before trusting a projection built on it.
#:
#: At roughly $15 per million characters this is about a fourteenth of ElevenLabs' Creator
#: tier, which is the difference between speech costing 12x a GD round's AI and costing less
#: than it. On the free tier it is zero, and this estimate simply over-reports — which is the
#: right direction for a spend figure to be wrong in.
_USD_PER_CHAR = 15.0 / 1_000_000


class FishAudioProvider:
    """One Fish Audio account, one backend model, many voices."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "s2.1-pro-free",
        timeout: float = 12.0,
    ) -> None:
        if not api_key:
            raise TTSError("FISH_API_KEY is not set")
        self._key = api_key
        #: Which synthesis backend. Sent as a HEADER, not in the body — Fish reads it from
        #: `model:`, which is easy to miss and fails as a 402 rather than a 400.
        #:
        #: Defaults to the FREE tier, and that is not a placeholder: verified against the
        #: live API that a zero-credit key returns 402 on the paid backends and real audio
        #: on s2.1-pro-free, in about 3.5 seconds. Since Fish bills API credit separately
        #: from platform credit, an account can look funded and still be refused — so the
        #: default that works is the right default.
        self._model = model
        # Short on purpose: this sits between an interviewer's question and the candidate
        # hearing it, and a caller still waiting after twelve seconds should long since have
        # fallen back to browser speech.
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "fish"

    def estimate_cost_usd(self, characters: int) -> float:
        return characters * _USD_PER_CHAR

    async def synthesize(
        self, text: str, *, voice_id: str, tone: str | None = None, speaker: str | None = None
    ) -> SynthesisResult:
        clean = (text or "").strip()
        if not clean:
            raise TTSError("nothing to speak")
        if not voice_id:
            raise TTSError("no voice_id for this speaker")

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    _API,
                    headers={
                        "Authorization": f"Bearer {self._key}",
                        "Content-Type": "application/json",
                        # Backend selection is a header in this API, not a body field.
                        "model": self._model,
                    },
                    json={
                        "text": clean,
                        # Fish's name for the voice.
                        "reference_id": voice_id,
                        "format": "mp3",
                        # Normalisation expands numbers and abbreviations into words, which
                        # is what stops "10 - 15%" being read as punctuation. An interview
                        # question is full of exactly that.
                        "normalize": True,
                        "latency": "normal",
                        # Delivery. Verified against the live API on identical text that
                        # speed genuinely changes the audio length rather than being
                        # silently accepted and dropped: 0.80 gave 53.9KB, 1.00 gave
                        # 47.2KB, 1.20 gave 35.5KB. Resolved from NAMES server-side — the
                        # line's tone and the panelist speaking it — so the browser cannot
                        # ask for speed 0.1 and bill a minute of audio.
                        "prosody": prosody_for(tone, speaker),
                    },
                )
        except httpx.HTTPError as exc:
            raise TTSError(f"fish request failed: {exc}") from exc

        if resp.status_code == 402:
            # Distinct from every other failure and verified against the live API. Fish bills
            # API credit separately from platform credit, so an account can look funded and
            # still return this. Raised as a budget error so the caller can say "top up"
            # rather than "something went wrong".
            raise TTSBudgetExceededError(
                "Fish Audio API credit is exhausted. API credit is separate from platform "
                "credit — top up at fish.audio/app/developers."
            )
        if resp.status_code != 200:
            detail = resp.text[:200]
            logger.warning("fish_synthesis_failed", status=resp.status_code, detail=detail)
            raise TTSError(f"fish returned {resp.status_code}: {detail}")

        # A JSON body on a 200 means an error dressed as success — refuse it rather than
        # handing the browser a "sound file" that is really an error object.
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype.lower():
            raise TTSError(f"fish returned JSON, not audio: {resp.text[:200]}")

        characters = len(clean)
        return SynthesisResult(
            audio=resp.content,
            content_type="audio/mpeg",
            characters=characters,
            estimated_cost_usd=self.estimate_cost_usd(characters),
            provider=self.provider_name,
            voice_id=voice_id,
        )

"""
Text-to-speech provider interface — services/tts/base.py

WHY THIS IS A PROVIDER ABSTRACTION AND NOT JUST AN ELEVENLABS CLIENT.

The browser's speechSynthesis is free and instant, and it sounds like a browser. Real
neural TTS is the single biggest change available to how this product feels — but it is
priced per CHARACTER, and the arithmetic is decisive enough that the choice of vendor has
to stay a configuration rather than a rewrite.

Measured against the real constants (26 panel turns, ~200 characters a contribution, so
~7,800 characters a round):

    ElevenLabs Creator  $22/100k chars     $1.72 per GD round     12x the round's AI cost
    ElevenLabs Flash v2.5 on Scale         $0.64 per GD round      4.5x
    Azure Neural TTS    ~$15/1M chars      $0.12 per GD round      0.8x
    Google Cloud Neural2 ~$16/1M chars     $0.13 per GD round      0.9x

For reference, every AI call in a GD round now costs $0.142 in total. So ElevenLabs on the
Creator tier would make speech roughly 92% of the product's cost, and at a thousand users
doing one round a day it is $1,716 a day against $117 on Azure.

ElevenLabs is genuinely the best-sounding of them, and for a panel of named characters that
matters. But Azure and Google both have native en-IN voices — Neerja and Prabhat are the two
this codebase's own voice ranking already looks for by name — and for Indian campus
placement practice an authentic accent is worth more than emotional range. Hence: both,
chosen by `TTS_PROVIDER`, with the per-panelist voice ids alongside.

TWO RULES THAT ARE NOT NEGOTIABLE.

1. THE KEY NEVER REACHES THE BROWSER. Synthesis happens server-side and the audio is
   proxied. A frontend calling ElevenLabs directly would ship the API key in the bundle,
   where anyone can spend it.

2. FAILURE FALLS BACK TO THE BROWSER. Every caller must treat server audio as an
   enhancement. If the provider is down, over budget, or slow, the round continues on
   speechSynthesis. A TTS outage must never be able to break a group discussion — which is
   also why this is a separate budget from the AI one rather than sharing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class TTSError(Exception):
    """Synthesis failed. The caller falls back to browser speech."""


class TTSBudgetExceededError(TTSError):
    """
    The character budget for today is spent.

    Distinct from a provider failure because it is expected rather than wrong, and because
    the right response differs: a failure is worth retrying, a spent budget is not.
    """


@dataclass(frozen=True)
class SynthesisResult:
    """Audio for one utterance, plus what it cost."""

    audio: bytes
    #: IANA type for the Content-Type header — "audio/mpeg" for MP3.
    content_type: str
    #: Characters billed. The unit these vendors price in, so it is the unit the budget
    #: counts and the ledger records — token counts are meaningless here.
    characters: int
    estimated_cost_usd: float
    provider: str
    voice_id: str


@runtime_checkable
class TTSProvider(Protocol):
    """
    One text-to-speech vendor.

    Deliberately narrow. Everything a caller needs is "turn this text, in this voice, into
    bytes I can play", and keeping the surface at that means adding a vendor is one file.
    """

    @property
    def provider_name(self) -> str: ...

    async def synthesize(self, text: str, *, voice_id: str) -> SynthesisResult:
        """
        Speak `text` in `voice_id`.

        Raises TTSError on any failure, including a timeout — callers are required to
        degrade to browser speech rather than surface an error, so there is no partial
        success to represent.
        """
        ...

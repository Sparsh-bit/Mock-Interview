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

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

#: How a line is delivered.
#:
#: A real interviewer does not say "walk me through your approach" and "no, that is not what
#: a HashMap does" in the same voice. The first is open and unhurried; the second is slower,
#: flatter and quieter — the sound of somebody stopping you. Reading both in one register is
#: the single clearest tell that nobody is actually in the room, and no amount of good
#: writing in the prompt fixes it, because the words are not what carries that.
#:
#:   asking       putting a question. Measured, a touch slow, leaves room to think.
#:   correcting   the answer was wrong. Slower and quieter: serious, not angry.
#:   affirming    the answer was good. A little quicker and warmer.
#:   aside        talking to the other interviewer, not the candidate. Quicker, offhand.
#:   neutral      everything else, including greetings and the close.
Tone = Literal["neutral", "asking", "correcting", "affirming", "aside"]

#: Tone → prosody, SERVER-SIDE AND ALLOWLISTED.
#:
#: The client sends a tone NAME, never numbers. Prosody is billable output that a caller
#: could otherwise drive to an extreme — speed 0.1 on a long answer is a minute of audio
#: charged to the daily budget — and there is no reason for the browser to have that dial.
#: An unknown name resolves to neutral rather than erroring, because a tone the server does
#: not recognise must never be the thing that costs somebody their interview.
#:
#: Volume is in dB and stays at 0. These are speech-to-speech models, and pushing gain here
#: mostly produces clipping; loudness differences that matter are in the writing.
#:
#: Kept narrow on purpose — verified against the live Fish API that speed genuinely changes
#: duration (0.80 → 53.9KB, 1.00 → 47.2KB, 1.20 → 35.5KB on identical text), so these are
#: real and audible, not a placebo field.
TONE_PROSODY: dict[str, dict[str, float]] = {
    "neutral": {"speed": 1.0, "volume": 0.0},
    "asking": {"speed": 0.98, "volume": 0.0},
    "correcting": {"speed": 0.94, "volume": 0.0},
    "affirming": {"speed": 1.02, "volume": 0.0},
    "aside": {"speed": 1.03, "volume": 0.0},
}
# NARROWED TO ±6%, FROM A RANGE THAT SPANNED 0.88 TO 1.08.
#
# "i want a normal voice and with a medium speaking pce in all the characters." The old spread
# was 20% wide, and on a metered vendor that renders as genuinely different speech rather than
# as resampling — so a correction at 0.88 sounded laboured and an aside at 1.08 sounded rushed,
# in the same conversation, from the same person.
#
# Tone is still expressed, because a correction that arrives at exactly the pace of a
# compliment is one of the things that made the panel read as a form being read out. It is now
# expressed in a band narrow enough that nobody sounds like a different speaker: the difference
# is audible when you are listening for it and never conspicuous when you are not.
#
# Together with SPEAKER_PACE being empty, the widest gap anywhere in the product is now 5% —
# between a correction and an aside — where it used to be 20%.


#: How fast a NAMED SPEAKER talks, as a multiplier on their tone's speed.
#:
#: Tone says how a LINE is delivered; this says how a PERSON talks, and the two are
#: independent — Riya asking a question and Riya conceding a point are both still Riya.
#: Without this the only per-speaker pacing available was the browser's playbackRate, which
#: resamples the finished audio instead of synthesising it differently. Resampling is what
#: made the assertive panelist sound wrong rather than merely quick: reported as a voice that
#: was "annoying and disturbed", not as one that was fast.
#:
#: Riya is the one entry below 1.0 and she is the reason this exists. Her stance is the
#: assertive one, so she carried the largest client-side tempo in the product, stacked on top
#: of a tone speed that already reached 1.08. Slowing her HERE spends a few more billed
#: seconds of audio and gets a voice that sounds like a person talking briskly, which is what
#: was actually wanted.
#:
#: Anything not listed speaks at its tone's speed unchanged, so a new panelist needs no entry
#: and a renamed one degrades to neutral pacing rather than to an error.
SPEAKER_PACE: dict[str, float] = {
    # EMPTY, AND THAT IS THE SETTING. Requested directly: "i want a normal voice and with a
    # medium speaking pce in all the characters."
    #
    # Riya used to be 0.92. That entry existed for a good reason at the time — her stance is
    # the assertive one and she was stacking a client-side tempo on top of a tone speed that
    # reached 1.08, which produced the "annoying and disturbed" voice reported back then. But
    # the whole roster has changed since: Slax, Paula, Hannah and alex are all `measured` or
    # `calm` voices chosen partly for pace, so the differentiation this table was compensating
    # for is now in the voices themselves rather than in a multiplier.
    #
    # Leaving one speaker slower than the others also means the panel does not sound like one
    # room. Everybody at the same pace is what "normal" sounds like.
    #
    # Keeping the mechanism rather than deleting it: a future roster with one genuinely fast
    # voice will want exactly this dial, and the argument for how to use it is above.
}

#: Floor and ceiling on the combined tone x speaker speed.
#:
#: Both multipliers are ours rather than a caller's, so this is not a validation boundary — it
#: is a guard against a future pair of edits that individually look reasonable and multiply
#: into something unlistenable. It also bounds the bill: speed is inversely proportional to
#: audio duration, and duration is what these vendors charge for.
_MIN_SPEED, _MAX_SPEED = 0.80, 1.15


def prosody_for(tone: str | None, speaker: str | None = None) -> dict[str, float]:
    """
    Tone name (and optionally who is speaking) → prosody.

    Unknown or missing names — either argument — fall back to neutral pacing rather than
    raising. A tone or a speaker this deploy does not recognise must never be the thing that
    costs somebody their interview; flat delivery is a far better failure than silence.
    """
    base = TONE_PROSODY.get(tone or "neutral", TONE_PROSODY["neutral"])
    pace = SPEAKER_PACE.get(speaker or "", 1.0)
    if pace == 1.0:
        return base
    speed = min(_MAX_SPEED, max(_MIN_SPEED, base["speed"] * pace))
    return {**base, "speed": round(speed, 3)}


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
class StreamingTTSProvider(Protocol):
    """
    A vendor that can start sending audio before it has finished making it.

    A SEPARATE PROTOCOL RATHER THAN AN OPTIONAL METHOD ON `TTSProvider`, and checked with
    `isinstance` against a `runtime_checkable` Protocol rather than a boolean flag, because
    the two vendors here genuinely differ and the difference is structural:

      ELEVENLABS has a documented streaming endpoint — the same request to
      `/v1/text-to-speech/{voice_id}/stream` returns the same audio as chunked transfer, so
      playback can start on the first chunk. Implemented.

      FISH AUDIO does not, through the API this product uses. `POST /v1/tts` answers with a
      complete file and a Content-Length; their streaming path is a separate WebSocket
      protocol with msgpack framing, which is a different integration rather than a flag on
      this one. NOT implemented, and deliberately not faked: a `synthesize_stream` that
      called `synthesize` and yielded the result once would satisfy every type checker,
      change nothing about when the first byte arrives, and make the code claim a capability
      it does not have.

      Fish is the DEFAULT vendor (`TTS_PROVIDER=fish`), so on a default deployment this
      protocol is unused and speech behaves exactly as it does today. That is the graceful
      degradation, and it is the common case rather than the edge one.

    NEITHER WAS VERIFIED AGAINST A LIVE VENDOR IN THIS REPOSITORY. There is no ElevenLabs key
    configured here, and Fish answers 402 — its API credit is spent, which this codebase
    already documents as distinct from platform credit. So the ElevenLabs implementation is
    written from its published contract and is unproven end to end; `tests/test_tts_stream.py`
    pins the shape and the fallback, which is what can be tested without a key, and the
    fallback is what runs when the contract turns out to differ.
    """

    @property
    def provider_name(self) -> str: ...

    def synthesize_stream(
        self, text: str, *, voice_id: str, tone: str | None = None, speaker: str | None = None
    ) -> AsyncIterator[bytes]:
        """
        Audio for one utterance, in chunks, in order.

        Raises TTSError before the first chunk on a refused request. A failure PART WAY
        through raises from inside the iteration — a caller that has already played some
        audio cannot un-play it, so its only sensible response is to stop, and it needs to be
        able to tell that from a clean end.
        """
        ...


@runtime_checkable
class TTSProvider(Protocol):
    """
    One text-to-speech vendor.

    Deliberately narrow. Everything a caller needs is "turn this text, in this voice, into
    bytes I can play", and keeping the surface at that means adding a vendor is one file.
    """

    @property
    def provider_name(self) -> str: ...

    def estimate_cost_usd(self, characters: int) -> float:
        """
        What `characters` will cost, before spending it.

        ON THE PROTOCOL because a caller needs it without knowing the vendor: the streaming
        endpoint bills after the last chunk, and at that point it has bytes rather than a
        `SynthesisResult`. Both providers already implement it — this only writes down that
        every provider must.
        """
        ...

    async def synthesize(
        self, text: str, *, voice_id: str, tone: str | None = None, speaker: str | None = None
    ) -> SynthesisResult:
        """
        Speak `text` in `voice_id`, delivered as `tone`, at `speaker`'s own pace.

        `tone` is a name from TONE_PROSODY, not numbers — see the note there. A provider
        with no prosody control is free to ignore it; the delivery is then flat, which is
        worse but not broken.

        `speaker` is the panelist's NAME, and it is optional for the same reason: it only
        selects a pace from SPEAKER_PACE, and an unknown or omitted one means "speak at the
        tone's own speed". Passing a name rather than a number keeps the rule that the
        browser never sends prosody — speed decides how many seconds of audio get billed.

        Raises TTSError on any failure, including a timeout — callers are required to
        degrade to browser speech rather than surface an error, so there is no partial
        success to represent.
        """
        ...

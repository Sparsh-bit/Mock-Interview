"""
Choosing a TTS vendor and a voice per speaker — services/tts/factory.py

One place decides which vendor is in use and which voice each speaker gets, for the same
reason the panel roster lives on the server: the voice a name speaks in is not cosmetic. A
client that could pick its own voice id could give Meera a male voice, which is the bug this
whole layer was built to prevent — and on a metered vendor it could also pick an expensive
model.
"""

from __future__ import annotations

import structlog

from app.core.config import settings
from app.services.tts.base import TTSError, TTSProvider

logger = structlog.get_logger(__name__)

_provider: TTSProvider | None = None


#: Fish backends that no longer answer. Sending one produces a HANG rather than an error.
#:
#: This exists because the difference matters enormously. A wrong-but-live model returns 402
#: or 400 in under a second and the client falls back cleanly. A retired one leaves the
#: request open until the client gives up, so the cost of the mistake is a timeout on every
#: single line instead of one fast refusal — and `httpx` reports it as `ReadTimeout('')`,
#: with an empty message, so nothing in the logs names the cause.
#:
#: Add to this list rather than only changing the default: the default protects a fresh
#: checkout, and this protects the deployments whose environment still carries the old value.
_RETIRED_FISH_MODELS: frozenset[str] = frozenset({"s2.1-pro-free", "s2.1-pro", "speech-1.4"})


def get_tts_provider() -> TTSProvider:
    """
    The configured provider, built once.

    Raises TTSError when unconfigured rather than returning None, so a caller cannot
    accidentally treat "no TTS" as "silent success" — every call site is required to catch it
    and fall back to browser speech.
    """
    global _provider
    if _provider is not None:
        return _provider

    name = (settings.TTS_PROVIDER or "").strip().lower()
    if name == "elevenlabs":
        from app.services.tts.elevenlabs import ElevenLabsProvider  # noqa: PLC0415

        _provider = ElevenLabsProvider(
            api_key=settings.ELEVENLABS_API_KEY,
            model=settings.ELEVENLABS_MODEL,
            tier=settings.ELEVENLABS_TIER,
        )
        logger.info(
            "tts_provider_created", provider="elevenlabs", model=settings.ELEVENLABS_MODEL
        )
        return _provider

    if name == "fish":
        from app.services.tts.fish import FishAudioProvider  # noqa: PLC0415

        model = (settings.FISH_MODEL or "").strip()
        if model in _RETIRED_FISH_MODELS:
            # REFUSED AT CONSTRUCTION, not per request, and this is the fix for a reported
            # bug rather than defensive habit.
            #
            # 's2.1-pro-free' was Fish's free backend and the default in this repo. It has
            # been retired, and a retired Fish backend does not answer with an error — it
            # does not answer at all. The connect and the TLS handshake succeed and then the
            # request sits there; measured at 35s and at 60s with no response. So every panel
            # line waited out the 12s client timeout in silence and then fell back to browser
            # speech, which is what "the voice is changing to the older voices" was.
            #
            # A refusal here turns that into the honest state: TTS is unavailable, the status
            # endpoint says so, and the round runs on browser voices from its FIRST line
            # rather than switching partway through. Consistently worse beats intermittently
            # broken — the whole point of the degrade latch on the client.
            #
            # NOT a startup raise, deliberately. A hard failure would take the backend down
            # for a deployment whose env still carries the old value, and TTS is an
            # enhancement — losing it must never cost anybody their interview.
            raise TTSError(
                f"FISH_MODEL={model!r} is a retired Fish backend. It does not return an "
                "error, it never responds, so every line would wait out the client timeout "
                "before falling back. Set FISH_MODEL to a current model — 's1', "
                "'speech-1.6', 'speech-1.5' or 's1-mini' — and top up API credit at "
                "fish.audio/app/developer, which Fish bills separately from platform credit."
            )

        _provider = FishAudioProvider(api_key=settings.FISH_API_KEY, model=model)
        logger.info("tts_provider_created", provider="fish", model=model)
        return _provider

    raise TTSError(f"unknown or unset TTS_PROVIDER: {name!r}")


def _voice_map() -> dict[str, str]:
    """
    Speaker name -> vendor voice id, from config.

    Keyed by the SERVER's panelist names (api/v1/gd.py PANELISTS) plus "interviewer". Parsed
    from a "Name:voice_id,Name:voice_id" string so adding a panelist is an env var rather
    than a deploy, and so voice ids — which are account-specific — never enter the repo.
    """
    raw = settings.TTS_VOICE_IDS or ""
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if ":" not in pair:
            continue
        name, _, vid = pair.partition(":")
        name, vid = name.strip(), vid.strip()
        if name and vid:
            out[name.lower()] = vid
    return out


def panel_voice_id(speaker: str) -> str | None:
    """The voice id for this speaker, or None if they have none configured."""
    return _voice_map().get((speaker or "").strip().lower())


def configured_voices() -> dict[str, bool]:
    """
    Which speakers have a voice, for /tts/status.

    Reported per speaker rather than as one boolean so a partly-configured panel degrades one
    voice at a time instead of dropping the whole round to browser speech.
    """
    from app.api.v1.gd import PANELIST_NAMES  # noqa: PLC0415
    from app.api.v1.panel import INTERVIEWER_NAMES  # noqa: PLC0415

    have = _voice_map()
    # Both panels, plus the solo interviewer used when the panel layer is unavailable. A name
    # missing here falls back to browser speech for that speaker ALONE, which is why this is
    # reported per name rather than as one boolean.
    speakers = [*INTERVIEWER_NAMES, *PANELIST_NAMES, "interviewer"]
    return {name: name.lower() in have for name in speakers}

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

    have = _voice_map()
    return {name: name.lower() in have for name in [*PANELIST_NAMES, "interviewer"]}

"""
Fish is the default vendor, ElevenLabs is still one env var away — tests/test_tts_default_vendor.py

TTS_PROVIDER used to default to 'elevenlabs'. It now defaults to 'fish', and the change is
worth about a tenth of the per-round speech bill: ElevenLabs' Creator tier is ~$210 per
million characters and Fish is ~$15, which flash_v2_5's half-credit rate narrows to roughly
10x rather than 14x. Fish also has real Indian-English voices, which for campus placement
practice is the part that is not about money.

WHAT THESE TESTS ARE ACTUALLY FOR is the risk that comes with a default swap, not the swap
itself. Three things can go wrong and none of them look like a failing import:

  1. THE DEFAULT SILENTLY REVERTS. A merge puts 'elevenlabs' back and nobody notices,
     because both values work — the only symptom is a bill. Pinned on the FIELD default,
     not the loaded value, so this tests the code rather than the machine's .env.

  2. THE ELEVENLABS PATH ROTS. A vendor that is no longer the default is a vendor nobody
     exercises. The instruction was to keep it fully intact and selectable, so it is
     exercised here through the same factory, on the same fake transport, as Fish.

  3. THE SWITCH DOES NOT ACTUALLY SWITCH VENDORS. This is the one that would be invisible.
     `provider_name` is a string a provider hands out about itself; it proves nothing about
     where the bytes came from. So the end-to-end check below drives a real synthesize()
     over a fake HTTP transport and asserts on the HOST, the auth header and the body
     shape — the things the vendor sees. Fish is api.fish.audio with a `model:` header and
     `reference_id`; ElevenLabs is api.elevenlabs.io with the voice in the PATH and
     `xi-api-key`. Those cannot be confused for each other.

No network calls. The transport is fake and every key here is fake with it.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.services.tts import factory
from app.services.tts.elevenlabs import ElevenLabsProvider
from app.services.tts.fish import FishAudioProvider

_ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


@pytest.fixture(autouse=True)
def _reset_provider_singleton():
    """The factory memoises into a module global; without this the first test to build a
    provider serves it to every later one and the config changes do nothing."""
    factory._provider = None
    yield
    factory._provider = None


class _Recorder:
    """A stand-in for httpx.AsyncClient that records one POST and answers with audio.

    Deliberately not a mock of the provider. The whole question these tests ask is what
    goes out on the wire, so the seam is as close to the wire as it can be without one.
    """

    def __init__(self, calls: list[dict]):
        self._calls = calls

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, headers=None, json=None, **kwargs):
        self._calls.append({"url": url, "headers": headers or {}, "json": json or {}})
        return httpx.Response(
            200,
            content=b"ID3\x03\x00fake-mp3-bytes",
            headers={"content-type": "audio/mpeg"},
        )


@pytest.fixture
def wire(monkeypatch):
    """Every outbound POST either provider makes, in order."""
    calls: list[dict] = []
    monkeypatch.setattr(httpx, "AsyncClient", _Recorder(calls))
    return calls


class TestTheDefaultIsFish:
    def test_the_field_default_is_fish(self):
        # THE FIELD, not settings.TTS_PROVIDER. `settings` reads .env, so asserting the
        # loaded value would pass or fail on whatever the developer running the suite has
        # configured locally — which is exactly the wrong signal for a question about what
        # a fresh deployment gets.
        assert Settings.model_fields["TTS_PROVIDER"].default == "fish"

    def test_env_example_agrees_with_the_field_default(self):
        # .env.example is what an operator copies. If the two disagree, one of them is
        # lying to somebody setting the app up for the first time, and the wrong one is
        # whichever they happened to read.
        text = _ENV_EXAMPLE.read_text()
        assigned = re.findall(r"^TTS_PROVIDER=(.+)$", text, flags=re.MULTILINE)
        assert assigned == ["fish"]

    def test_switching_the_vendor_is_still_only_a_default(self):
        # The point of the change is which bill you get, not whether speech is on. Making
        # it cheap must not be mistaken for making it free, so TTS_ENABLED stays False.
        assert Settings.model_fields["TTS_ENABLED"].default is False

    def test_the_fish_backend_default_is_not_a_retired_one(self):
        # FishAudioProvider's own signature default, one layer below the factory. It was
        # 's2.1-pro-free' — retired, and a retired Fish backend HANGS rather than
        # refusing. The factory always passes FISH_MODEL explicitly and blocks the retired
        # list, so this was unreachable; it stops being unreachable the moment anybody
        # constructs the provider directly, and Fish being the default vendor makes that
        # far more likely.
        import inspect

        default = inspect.signature(FishAudioProvider.__init__).parameters["model"].default
        assert default not in factory._RETIRED_FISH_MODELS
        assert default == "s1"

    def test_the_default_config_builds_a_fish_provider(self, monkeypatch):
        monkeypatch.setattr(
            factory.settings, "TTS_PROVIDER", Settings.model_fields["TTS_PROVIDER"].default
        )
        monkeypatch.setattr(factory.settings, "FISH_API_KEY", "fake-fish-key")
        monkeypatch.setattr(factory.settings, "FISH_MODEL", "s1")
        assert isinstance(factory.get_tts_provider(), FishAudioProvider)


class TestElevenLabsIsIntactAndSelectable:
    def test_setting_the_env_var_still_gets_you_elevenlabs(self, monkeypatch):
        monkeypatch.setattr(factory.settings, "TTS_PROVIDER", "elevenlabs")
        monkeypatch.setattr(factory.settings, "ELEVENLABS_API_KEY", "fake-11-key")
        provider = factory.get_tts_provider()
        assert isinstance(provider, ElevenLabsProvider)
        assert provider.provider_name == "elevenlabs"

    def test_it_is_case_and_whitespace_insensitive_like_before(self, monkeypatch):
        # This is how the value arrives from a hosting provider's environment UI. Nothing
        # about the default change may narrow what is accepted.
        monkeypatch.setattr(factory.settings, "TTS_PROVIDER", "  ElevenLabs \n")
        monkeypatch.setattr(factory.settings, "ELEVENLABS_API_KEY", "fake-11-key")
        assert isinstance(factory.get_tts_provider(), ElevenLabsProvider)

    def test_its_cost_model_still_works(self):
        # The tier table is the thing that would quietly rot on an unused path — and it is
        # what the spend ledger reports, so rot there under-reports a real bill.
        creator = ElevenLabsProvider(api_key="k", tier="creator").estimate_cost_usd(7_800)
        assert creator > 0

    def test_an_unknown_provider_name_is_still_refused(self, monkeypatch):
        from app.services.tts.base import TTSError

        # Not "fall back to the default". A typo in TTS_PROVIDER must be loud: silently
        # serving the default vendor is how a deployment ends up billed by one vendor
        # while its voice map belongs to the other.
        monkeypatch.setattr(factory.settings, "TTS_PROVIDER", "elevnlabs")
        with pytest.raises(TTSError, match="unknown or unset"):
            factory.get_tts_provider()


class TestTheSwitchChangesWhatTheVendorSees:
    """End to end through the factory and a real synthesize(), over a fake transport.

    `provider_name` is self-reported and would pass even if both branches called the same
    API. These assert on the request itself.
    """

    @pytest.mark.asyncio
    async def test_the_default_talks_to_fish_in_fishs_dialect(self, monkeypatch, wire):
        monkeypatch.setattr(
            factory.settings, "TTS_PROVIDER", Settings.model_fields["TTS_PROVIDER"].default
        )
        monkeypatch.setattr(factory.settings, "FISH_API_KEY", "fake-fish-key")
        monkeypatch.setattr(factory.settings, "FISH_MODEL", "s1")

        result = await factory.get_tts_provider().synthesize(
            "What is a HashMap?", voice_id="0123456789abcdef0123456789abcdef", speaker="Riya"
        )

        assert len(wire) == 1
        sent = wire[0]
        assert "api.fish.audio" in sent["url"]
        assert "elevenlabs" not in sent["url"]
        # Fish takes the voice in the BODY as reference_id and the backend as a HEADER.
        assert sent["json"]["reference_id"] == "0123456789abcdef0123456789abcdef"
        assert sent["headers"]["model"] == "s1"
        assert sent["headers"]["Authorization"] == "Bearer fake-fish-key"
        assert "xi-api-key" not in sent["headers"]
        assert result.provider == "fish"
        assert result.audio.startswith(b"ID3")

    @pytest.mark.asyncio
    async def test_flipping_the_var_talks_to_elevenlabs_in_theirs(self, monkeypatch, wire):
        monkeypatch.setattr(factory.settings, "TTS_PROVIDER", "elevenlabs")
        monkeypatch.setattr(factory.settings, "ELEVENLABS_API_KEY", "fake-11-key")
        monkeypatch.setattr(factory.settings, "ELEVENLABS_MODEL", "eleven_flash_v2_5")

        result = await factory.get_tts_provider().synthesize(
            "What is a HashMap?", voice_id="EXAVITQu4vr4xnSDxMaL", speaker="Riya"
        )

        assert len(wire) == 1
        sent = wire[0]
        assert "api.elevenlabs.io" in sent["url"]
        assert "fish.audio" not in sent["url"]
        # ElevenLabs takes the voice in the PATH and the model in the BODY — the mirror
        # image of Fish. One request could never be mistaken for the other.
        assert sent["url"].endswith("/EXAVITQu4vr4xnSDxMaL")
        assert sent["json"]["model_id"] == "eleven_flash_v2_5"
        assert sent["headers"]["xi-api-key"] == "fake-11-key"
        assert "Authorization" not in sent["headers"]
        assert "reference_id" not in sent["json"]
        assert result.provider == "elevenlabs"

    @pytest.mark.asyncio
    async def test_the_same_line_is_billed_far_less_on_the_new_default(
        self, monkeypatch, wire
    ):
        """The reason the default moved, measured rather than asserted from the docs.

        Both providers are driven over the same transport with the same text, and their
        own cost estimates — the figures that reach the spend ledger — are compared.
        """
        line = "Walk me through how a HashMap resolves a collision."

        monkeypatch.setattr(factory.settings, "TTS_PROVIDER", "fish")
        monkeypatch.setattr(factory.settings, "FISH_API_KEY", "fake-fish-key")
        monkeypatch.setattr(factory.settings, "FISH_MODEL", "s1")
        fish = await factory.get_tts_provider().synthesize(
            line, voice_id="0123456789abcdef0123456789abcdef"
        )

        factory._provider = None
        monkeypatch.setattr(factory.settings, "TTS_PROVIDER", "elevenlabs")
        monkeypatch.setattr(factory.settings, "ELEVENLABS_API_KEY", "fake-11-key")
        monkeypatch.setattr(factory.settings, "ELEVENLABS_MODEL", "eleven_flash_v2_5")
        monkeypatch.setattr(factory.settings, "ELEVENLABS_TIER", "creator")
        eleven = await factory.get_tts_provider().synthesize(
            line, voice_id="EXAVITQu4vr4xnSDxMaL"
        )

        assert fish.characters == eleven.characters == len(line)
        # ~10x on flash_v2_5's half-credit rate, ~14x at list. Asserted as a floor of 5x so
        # this pins the ORDER OF MAGNITUDE rather than breaking on a tier price change —
        # if that gap ever closes to less than 5x, the reason for this default is gone and
        # somebody should be told.
        assert eleven.estimated_cost_usd > fish.estimated_cost_usd * 5

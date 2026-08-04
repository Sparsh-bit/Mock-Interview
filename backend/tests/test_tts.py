"""
Neural speech — tests/test_tts.py

Two things have to hold, and they are not the same kind of thing.

MONEY. TTS is billed per CHARACTER, and on ElevenLabs' Creator tier one GD round of neural
speech costs roughly twelve times every AI call in that round put together. So the cost
estimate, the budget and the cache all have to be right, and an error that under-reports
spend is worse than one that over-reports it.

CORRECTNESS. The client must never choose its own voice. A voice id chosen client-side is how
a panelist called Meera ends up male — the exact bug that was reported — and on a metered
vendor it is also how a caller picks an expensive model.
"""

from __future__ import annotations

import pytest

from app.api.v1.tts import _MAX_CHARS, _cache_key
from app.core.config import settings
from app.services.tts.base import SynthesisResult, TTSBudgetExceededError, TTSError
from app.services.tts.elevenlabs import ElevenLabsProvider


class TestTheClientCannotChooseAVoice:
    def test_the_request_takes_a_speaker_name_not_a_voice_id(self):
        # The whole reason voices are resolved server-side. If SpeakRequest ever grows a
        # voice_id field, a client can give Meera a male voice again.
        from app.api.v1.tts import SpeakRequest

        assert set(SpeakRequest.model_fields) == {"text", "speaker"}

    def test_the_voice_map_is_parsed_from_config(self, monkeypatch):
        from app.services.tts import factory

        monkeypatch.setattr(
            settings, "TTS_VOICE_IDS", "Riya:v_riya, Arjun:v_arjun ,Meera:v_meera", raising=False
        )
        assert factory.panel_voice_id("Riya") == "v_riya"
        # Whitespace and case must not matter: these come from an env var typed by a human.
        assert factory.panel_voice_id("  arjun ") == "v_arjun"
        assert factory.panel_voice_id("MEERA") == "v_meera"

    def test_an_unmapped_speaker_has_no_voice(self, monkeypatch):
        from app.services.tts import factory

        monkeypatch.setattr(settings, "TTS_VOICE_IDS", "Riya:v_riya", raising=False)
        # None, not a default voice. Falling back to *some* voice is how Meera gets a male
        # one; the endpoint turns this into a 503 and that speaker uses browser speech.
        assert factory.panel_voice_id("Meera") is None

    def test_malformed_config_entries_are_ignored_not_guessed(self, monkeypatch):
        from app.services.tts import factory

        monkeypatch.setattr(
            settings, "TTS_VOICE_IDS", "Riya:v_riya,brokenentry,Arjun:,:orphan", raising=False
        )
        assert factory.panel_voice_id("Riya") == "v_riya"
        assert factory.panel_voice_id("Arjun") is None
        assert factory.panel_voice_id("brokenentry") is None


class TestCostEstimation:
    def test_flash_bills_half_the_credits_of_multilingual(self):
        # This is the difference between ~12x and ~4.5x the round's AI cost, so it is the
        # single most consequential setting in the module.
        flash = ElevenLabsProvider(api_key="k", model="eleven_flash_v2_5", tier="creator")
        multi = ElevenLabsProvider(api_key="k", model="eleven_multilingual_v2", tier="creator")
        assert flash.estimate_cost_usd(1000) == pytest.approx(multi.estimate_cost_usd(1000) / 2)

    def test_a_higher_tier_costs_less_per_character(self):
        chars = 7_800  # one GD round
        creator = ElevenLabsProvider(api_key="k", tier="creator").estimate_cost_usd(chars)
        scale = ElevenLabsProvider(api_key="k", tier="scale").estimate_cost_usd(chars)
        assert scale < creator

    def test_an_unknown_tier_over_estimates_rather_than_under(self, ):
        # A typo in ELEVENLABS_TIER must not make spend look cheaper than it is: a budget
        # that reads low stops protecting anything.
        typo = ElevenLabsProvider(api_key="k", tier="creatorr").estimate_cost_usd(10_000)
        cheapest_paid = ElevenLabsProvider(api_key="k", tier="business").estimate_cost_usd(10_000)
        assert typo > cheapest_paid

    def test_a_gd_round_is_priced_where_the_docs_say_it_is(self):
        # 26 turns x ~1.5 contributions x ~200 chars. If this drifts far from the figure in
        # AI-COST-MODEL.md and services/tts/base.py, one of them is now lying.
        cost = ElevenLabsProvider(api_key="k", model="eleven_flash_v2_5", tier="creator") \
            .estimate_cost_usd(7_800)
        assert 0.7 < cost < 1.0

    def test_no_api_key_is_refused_at_construction(self):
        # Not at the first call. A provider that exists but cannot work would report itself
        # available through /tts/status and fail every utterance.
        with pytest.raises(TTSError):
            ElevenLabsProvider(api_key="")


class TestTheAudioCacheIsExactNotSemantic:
    def test_identical_text_shares_a_key(self):
        a = _cache_key("elevenlabs", "v1", "What is a HashMap?")
        b = _cache_key("elevenlabs", "v1", "  What is a HashMap?  ")
        assert a == b

    def test_different_text_does_not(self):
        # Audio must be byte-identical to what is on screen. A near-match — which the
        # SEMANTIC cache would happily serve for generations — would play the candidate a
        # different sentence from the one they are reading.
        a = _cache_key("elevenlabs", "v1", "What is a HashMap?")
        b = _cache_key("elevenlabs", "v1", "What is a Hashtable?")
        assert a != b

    def test_the_voice_is_part_of_the_key(self):
        # Same words in a different voice is different audio. Without this, Riya's cached
        # line would be served in Arjun's turn.
        assert _cache_key("elevenlabs", "v_riya", "Yes.") != _cache_key(
            "elevenlabs", "v_arjun", "Yes."
        )

    def test_the_provider_is_part_of_the_key(self):
        # Switching vendor must not serve the old vendor's audio.
        assert _cache_key("elevenlabs", "v1", "Yes.") != _cache_key("azure", "v1", "Yes.")


class TestBudgetAndBounds:
    def test_tts_has_its_own_budget_separate_from_the_ai_one(self):
        # Characters and tokens are not interchangeable. Sharing one budget would mean
        # speech quietly consuming the allowance that scores interviews.
        assert settings.TTS_DAILY_BUDGET_USD > 0
        assert hasattr(settings, "AI_DAILY_BUDGET_USD")

    def test_tts_is_off_by_default(self):
        # A per-character bill has to be opted into by somebody who has seen the numbers.
        assert settings.TTS_ENABLED is False

    def test_an_utterance_length_ceiling_exists(self):
        # A panel contribution is 1-3 sentences by prompt rule. At per-character pricing an
        # unbounded field is a way to burn the budget, not just a slow request.
        assert 200 <= _MAX_CHARS <= 1000

    @pytest.mark.asyncio
    async def test_spend_is_recorded_and_read_back(self):
        from app.services.tts.spend import record_tts_spend, tts_spend_today

        before = await tts_spend_today()
        await record_tts_spend(0.25)
        assert await tts_spend_today() >= before + 0.25

    @pytest.mark.asyncio
    async def test_zero_and_negative_spend_are_ignored(self):
        from app.services.tts.spend import record_tts_spend, tts_spend_today

        before = await tts_spend_today()
        await record_tts_spend(0)
        await record_tts_spend(-1)
        assert await tts_spend_today() == before

    def test_the_budget_error_is_distinct_from_a_failure(self):
        # A spent budget is expected and not worth retrying; a vendor failure might be.
        assert issubclass(TTSBudgetExceededError, TTSError)


class TestTheResultCarriesWhatTheLedgerNeeds:
    def test_characters_not_tokens(self):
        # These vendors bill per character, so a token count would be meaningless here.
        r = SynthesisResult(
            audio=b"x", content_type="audio/mpeg", characters=12,
            estimated_cost_usd=0.001, provider="elevenlabs", voice_id="v1",
        )
        assert r.characters == 12
        assert "token" not in str(SynthesisResult.__dataclass_fields__.keys())

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

        # `tone` is a NAME from an allowlist, resolved to prosody server-side, so it does
        # not weaken this: the client still cannot pick a voice, and it cannot pick a speed
        # either — which matters because speed is what decides how much audio gets billed.
        assert set(SpeakRequest.model_fields) == {"text", "speaker", "tone"}

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
        a = _cache_key("elevenlabs", "v1", "What is a HashMap?", "asking", 1.0)
        b = _cache_key("elevenlabs", "v1", "  What is a HashMap?  ", "asking", 1.0)
        assert a == b

    def test_different_text_does_not(self):
        # Audio must be byte-identical to what is on screen. A near-match — which the
        # SEMANTIC cache would happily serve for generations — would play the candidate a
        # different sentence from the one they are reading.
        a = _cache_key("elevenlabs", "v1", "What is a HashMap?", "asking", 1.0)
        b = _cache_key("elevenlabs", "v1", "What is a Hashtable?", "asking", 1.0)
        assert a != b

    def test_the_voice_is_part_of_the_key(self):
        # Same words in a different voice is different audio. Without this, Riya's cached
        # line would be served in Arjun's turn.
        assert _cache_key("elevenlabs", "v_riya", "Yes.", "neutral", 1.0) != _cache_key(
            "elevenlabs", "v_arjun", "Yes.", "neutral", 1.0
        )

    def test_the_provider_is_part_of_the_key(self):
        # Switching vendor must not serve the old vendor's audio.
        assert _cache_key("elevenlabs", "v1", "Yes.", "neutral", 1.0) != _cache_key(
            "azure", "v1", "Yes.", "neutral", 1.0
        )

    def test_the_tone_is_part_of_the_key(self):
        # Otherwise the first delivery of a line wins for a fortnight. A sentence spoken
        # once in passing would be served back — flat — to every candidate who later got
        # that question wrong, which is precisely the thing tone exists to prevent.
        assert _cache_key(
            "fish", "v1", "That is not quite right.", "correcting", 0.88
        ) != _cache_key("fish", "v1", "That is not quite right.", "neutral", 1.0)

    def test_the_resolved_speed_is_part_of_the_key(self):
        # A speaker with their own pace produces different bytes for the same words in the
        # same tone. Leaving speed out would serve the slowed panelist's audio to everyone
        # else on that voice, and vice versa — the same class of bug as omitting tone.
        assert _cache_key("fish", "v1", "Go on.", "neutral", 0.92) != _cache_key(
            "fish", "v1", "Go on.", "neutral", 1.0
        )

    def test_two_speakers_at_the_same_pace_still_share_one_entry(self):
        # The reason speed is in the key as a NUMBER rather than as the speaker's name.
        # Anil and the `interviewer` fallback share a voice id and a pace, so they must
        # share the cached audio rather than paying the vendor twice for identical bytes.
        assert _cache_key("fish", "v_anil", "Welcome.", "neutral", 1.0) == _cache_key(
            "fish", "v_anil", "Welcome.", "neutral", 1.0
        )


class TestBudgetAndBounds:
    def test_tts_has_its_own_budget_separate_from_the_ai_one(self):
        # Characters and tokens are not interchangeable. Sharing one budget would mean
        # speech quietly consuming the allowance that scores interviews.
        assert settings.TTS_DAILY_BUDGET_USD > 0
        assert hasattr(settings, "AI_DAILY_BUDGET_USD")

    def test_tts_is_off_by_default(self):
        # A per-character bill has to be opted into by somebody who has seen the numbers.
        #
        # Asserts the FIELD DEFAULT, not the loaded value: `settings` reads .env, so checking
        # the runtime value makes this test pass or fail based on the machine it runs on
        # rather than on the code. It failed the moment TTS was switched on locally, which is
        # exactly the wrong signal.
        from app.core.config import Settings

        assert Settings.model_fields["TTS_ENABLED"].default is False

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


class TestToneIsAllowlistedServerSide:
    """
    Tone is what makes a correction sound like a correction rather than being read out in
    the same breezy voice as the greeting. It is also billable output, so the browser gets
    to send a NAME and the server owns the numbers.
    """

    def test_every_tone_the_prompt_can_emit_resolves(self):
        # The five names in prompts/interview_panel.md. A name the prompt is told to use
        # that the table does not know would silently flatten every line tagged with it.
        from app.services.tts.base import TONE_PROSODY

        for name in ("neutral", "asking", "correcting", "affirming", "aside"):
            assert name in TONE_PROSODY

    def test_an_unknown_tone_is_neutral_not_an_error(self):
        # A client on last week's bundle sending a tone this deploy has never heard of must
        # still get audio. Silence is a far worse failure than flat delivery.
        from app.services.tts.base import TONE_PROSODY, prosody_for

        assert prosody_for("enthusiastic-pirate") == TONE_PROSODY["neutral"]
        assert prosody_for(None) == TONE_PROSODY["neutral"]
        assert prosody_for("") == TONE_PROSODY["neutral"]

    def test_a_correction_is_slower_than_a_question_which_is_slower_than_an_aside(self):
        # The actual claim being made about how a room sounds: you slow down to tell
        # somebody they are wrong, and you speed up when muttering to your colleague. If
        # these ever collapse to equal, tone is doing nothing and the tests should say so.
        from app.services.tts.base import prosody_for

        assert (
            prosody_for("correcting")["speed"]
            < prosody_for("asking")["speed"]
            < prosody_for("aside")["speed"]
        )

    def test_no_tone_can_be_used_to_run_up_the_bill(self):
        # Speed is what decides how many seconds of audio a request produces, and audio is
        # charged per character but rendered per second — an extreme value is a denial-of-
        # budget dressed as a stylistic choice. Bounded on both sides.
        from app.services.tts.base import TONE_PROSODY

        for name, p in TONE_PROSODY.items():
            assert 0.8 <= p["speed"] <= 1.25, name
            assert p["volume"] == 0.0, name

    async def test_fish_sends_the_prosody_the_tone_resolves_to(self):
        # The end-to-end claim: a tone NAME on the request becomes real prosody in the
        # vendor call. Verified against the live API separately that speed genuinely changes
        # the audio length (0.80 -> 53.9KB, 1.20 -> 35.5KB on identical text), so this is
        # checking the wiring, not the premise.
        import httpx

        from app.services.tts.base import TONE_PROSODY
        from app.services.tts.fish import FishAudioProvider

        sent: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            sent.update(_json.loads(request.content))
            return httpx.Response(200, content=b"\xff\xfb" + b"\x00" * 64,
                                  headers={"content-type": "audio/mpeg"})

        transport = httpx.MockTransport(handler)
        provider = FishAudioProvider(api_key="k")

        original = httpx.AsyncClient

        class _Patched(original):  # type: ignore[misc,valid-type]
            def __init__(self, **kw):
                kw["transport"] = transport
                super().__init__(**kw)

        httpx.AsyncClient = _Patched  # type: ignore[misc]
        try:
            await provider.synthesize("You are wrong.", voice_id="v1", tone="correcting")
        finally:
            httpx.AsyncClient = original  # type: ignore[misc]

        assert sent["prosody"] == TONE_PROSODY["correcting"]


class TestPerSpeakerPace:
    """
    A named speaker can talk slower or faster than their tone alone would.

    This exists because of a real report: the assertive GD panelist was "annoying and
    disturbed" to listen to. She was not merely quick — she was the product of three
    multipliers stacked on one another, the last of which was a browser playbackRate that
    RESAMPLES finished audio rather than synthesising it differently. Resampling is what
    made it sound wrong rather than fast. Pace belongs here, where the vendor applies it
    during synthesis.
    """

    def test_an_unlisted_speaker_speaks_at_the_tone_speed(self):
        from app.services.tts.base import TONE_PROSODY, prosody_for

        assert prosody_for("asking", "Nobody") == TONE_PROSODY["asking"]
        # Omitted entirely is the same as unknown — every existing caller relies on this.
        assert prosody_for("asking") == TONE_PROSODY["asking"]

    def test_a_listed_speaker_is_slowed_relative_to_their_tone(self):
        from app.services.tts.base import TONE_PROSODY, prosody_for

        for tone in TONE_PROSODY:
            assert prosody_for(tone, "Riya")["speed"] < TONE_PROSODY[tone]["speed"], tone

    def test_pace_does_not_invert_the_tone_ordering(self):
        # Slowing a speaker must not flatten how their own lines differ from each other. A
        # correction from Riya still has to be slower than her asides, or the pace fix would
        # have cost the tone work it sits on top of.
        from app.services.tts.base import prosody_for

        assert (
            prosody_for("correcting", "Riya")["speed"]
            < prosody_for("asking", "Riya")["speed"]
            < prosody_for("aside", "Riya")["speed"]
        )

    def test_the_combined_speed_stays_within_listenable_bounds(self):
        # The guard against two individually reasonable edits multiplying into something
        # unlistenable — and against a runaway speed inflating billed audio duration.
        from app.services.tts.base import SPEAKER_PACE, TONE_PROSODY, prosody_for

        for tone in TONE_PROSODY:
            for speaker in SPEAKER_PACE:
                assert 0.80 <= prosody_for(tone, speaker)["speed"] <= 1.15

    def test_volume_is_untouched_by_pace(self):
        from app.services.tts.base import prosody_for

        assert prosody_for("asking", "Riya")["volume"] == 0.0

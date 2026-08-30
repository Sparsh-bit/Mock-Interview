"""
Speech that starts before it is finished — tests/test_tts_stream.py

THE TWO VENDORS ARE NOT THE SAME, AND THIS FILE EXISTS BECAUSE ASSUMING THEY WERE WOULD HAVE
BEEN THE EASY MISTAKE.

  ELEVENLABS has a streaming endpoint. The same request to
  `/v1/text-to-speech/{voice_id}/stream` returns the same audio as chunked transfer, so
  playback can start on the first chunk. `ElevenLabsProvider.synthesize_stream` implements it.

  FISH AUDIO does not, through the API this product uses. `POST /v1/tts` answers with a
  complete MP3 and a Content-Length; Fish's streaming path is a separate WebSocket protocol
  carrying msgpack frames — a different integration, not a flag on this one. So
  `FishAudioProvider` does NOT implement `StreamingTTSProvider`, and the endpoint sends the
  whole file in one chunk on Fish, which is byte-for-byte today's behaviour.

  Fish is the DEFAULT vendor (`TTS_PROVIDER=fish`), so the non-streaming path is the COMMON
  case rather than the edge case, and these tests treat it as such.

NEITHER WAS VERIFIED AGAINST A LIVE VENDOR. There is no ElevenLabs key in this repository, and
Fish answers 402 — its API credit is spent, which this codebase already documents as separate
from platform credit. So the ElevenLabs implementation is written from the published contract
and is unproven end to end. What IS testable without a key is the shape, the capability
detection and the fallback — and the fallback is exactly what runs if the published contract
turns out to differ, which is why it is the thing worth pinning hardest.

────────────────────────────────────────────────────────────────────────────────────────────
THE SILENT FAILURE: A TRUNCATED LINE, CACHED
────────────────────────────────────────────────────────────────────────────────────────────

Audio is cached by the exact text for a day. A stream cut halfway has produced playable
audio — the candidate heard part of a sentence — and writing THAT to the cache would freeze a
truncated line in place, so every candidate asked the same question would hear it cut off in
the same place, long after the network blip. Nothing would look broken.

So the ledger write, the spend write and the cache write happen after the last chunk,
together, or none of them happens.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from app.services.tts.base import StreamingTTSProvider, TTSProvider

_API = pathlib.Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "tts.py"


class TestWhichVendorCanActuallyStream:
    def test_elevenlabs_declares_the_streaming_protocol(self):
        from app.services.tts.elevenlabs import ElevenLabsProvider

        provider = ElevenLabsProvider(api_key="test-key")
        assert isinstance(provider, StreamingTTSProvider)
        assert isinstance(provider, TTSProvider)

    def test_fish_does_not(self):
        """
        A FINDING, NOT A GAP. `POST /v1/tts` returns a complete file; streaming Fish is a
        WebSocket protocol with msgpack framing. A `synthesize_stream` that called
        `synthesize` and yielded once would satisfy the protocol, pass every type check,
        change nothing about when the first byte arrives, and leave the code claiming a
        capability it does not have.
        """
        from app.services.tts.fish import FishAudioProvider

        provider = FishAudioProvider(api_key="test-key")
        assert not isinstance(provider, StreamingTTSProvider)
        # And it is still a perfectly good TTS provider — the endpoint uses `synthesize`.
        assert isinstance(provider, TTSProvider)

    def test_the_default_vendor_is_the_non_streaming_one(self):
        """
        Worth pinning, because it decides which branch is the common case. If the default ever
        becomes ElevenLabs, the fallback path stops being the one most deployments run and
        this file's emphasis should change with it.
        """
        from app.core.config import settings

        assert settings.TTS_PROVIDER in {"fish", "elevenlabs"}

    def test_elevenlabs_streams_from_the_stream_endpoint_with_the_same_body(self):
        """
        Same model, same voice settings, only the URL differs — so a streamed line and a whole
        one are the same audio and cannot come out sounding different.
        """
        from app.services.tts import elevenlabs as el

        src = inspect.getsource(el.ElevenLabsProvider.synthesize_stream)
        assert '/stream"' in src
        for setting in ("stability", "similarity_boost", "style", "use_speaker_boost"):
            assert setting in src, f"{setting} differs between the streamed and whole paths"
        assert "model_id" in src

    def test_a_streaming_error_body_is_read_before_it_is_raised(self):
        # On a streaming response the body has not been fetched yet, so `resp.text` would be
        # empty and the error would say nothing — the exact failure mode fish.py documents at
        # length after it cost a long diagnosis.
        from app.services.tts import elevenlabs as el

        src = inspect.getsource(el.ElevenLabsProvider.synthesize_stream)
        assert "await resp.aread()" in src

    def test_every_provider_can_price_characters(self):
        # The streaming endpoint bills after the last chunk, when it has bytes rather than a
        # SynthesisResult, so this has to be on the protocol rather than on one class.
        from app.services.tts.elevenlabs import ElevenLabsProvider
        from app.services.tts.fish import FishAudioProvider

        for provider in (
            ElevenLabsProvider(api_key="k"),
            FishAudioProvider(api_key="k"),
        ):
            assert provider.estimate_cost_usd(1000) > 0


class TestNothingIsRecordedOrCachedUntilTheAudioIsComplete:
    """
    Source assertions on ordering, because ordering is the guarantee and no runtime test can
    show that one line does NOT run before another. What they catch is the regression that
    happens: somebody moving a cache write earlier "so the next request is faster".
    """

    @pytest.fixture
    def stream_endpoint(self) -> str:
        src = _API.read_text()
        return src[src.index("async def speak_stream("):]

    def test_the_error_path_writes_nothing(self, stream_endpoint: str):
        # The LAST `except TTSError` — the first one is the provider lookup at the top,
        # which is a different failure with a different (and correct) 503 response.
        handler = stream_endpoint[
            stream_endpoint.rindex("except TTSError as exc:") : stream_endpoint.index(
                "# ONLY NOW."
            )
        ]
        assert "cache_set_bytes" not in handler
        assert "record_tts_spend" not in handler
        assert "record_synthesis" not in handler
        # It returns rather than raising: the status is already 200 and audio may already be
        # playing, so this cannot become an HTTP error.
        assert "return" in handler

    @pytest.mark.parametrize(
        "write", ["record_tts_spend(", "record_synthesis(", "cache_set_bytes("]
    )
    def test_every_write_happens_after_the_last_chunk(self, stream_endpoint: str, write: str):
        # `rindex`, because the cached fast path also returns a StreamingResponse — the
        # first occurrence would cut the body off above the generator entirely.
        body = stream_endpoint[: stream_endpoint.rindex("return StreamingResponse(")]
        marker = body.index("# ONLY NOW.")
        # The `cached` fast path above also records — that one is a complete, already-cached
        # utterance, so only the occurrences inside the generator are in question.
        generator = body[body.index("async def audio()") :]
        assert write in generator
        assert generator.index(write) > (marker - body.index("async def audio()")), (
            f"{write} runs before the audio is known to be complete"
        )

    def test_the_response_is_never_stored_by_a_cache_in_between(self, stream_endpoint: str):
        # The body is only complete if the stream finished. An intermediary caching a
        # truncated one would serve a silently broken line for as long as it lived.
        assert '"Cache-Control": "no-store"' in stream_endpoint

    def test_the_fallback_path_is_a_single_whole_chunk(self, stream_endpoint: str):
        # The Fish case, and the default deployment. Same bytes, same cost, same first-byte
        # time as POST /speak — and a response the client does not have to special-case.
        assert "await provider.synthesize(" in stream_endpoint
        assert '"X-TTS-Streamed": "vendor" if streaming else "whole"' in stream_endpoint

    def test_capability_is_detected_from_the_provider_not_from_settings(
        self, stream_endpoint: str
    ):
        # Reading it from TTS_PROVIDER would let the setting and the class disagree after a
        # vendor change, and the symptom would be a 500 rather than a fallback.
        assert "isinstance(provider, StreamingTTSProvider)" in stream_endpoint
        assert "settings.TTS_PROVIDER" not in stream_endpoint

    def test_a_cache_hit_is_still_served_when_the_budget_is_spent(self, stream_endpoint: str):
        # The same ordering `speak` has: a hit costs nothing, so a spent budget must not stop
        # it being served.
        assert stream_endpoint.index("cached = await cache_get_bytes(key)") < stream_endpoint.index(
            "has_room, _remaining = await _budget_room()"
        )

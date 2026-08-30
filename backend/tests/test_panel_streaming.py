"""
The panel speaks while it is still being written — tests/test_panel_streaming.py

THE WAIT THIS REMOVES. A panel turn is four short spoken lines inside one JSON object, and
until now the candidate saw none of it until the whole object arrived — most of a second of
silence at the exact moment they are most alert, because the interviewer has stopped talking
and they are waiting to be asked something. The model writes that object left to right: the
first line is finished long before the last one starts.

`scripts/panel_stream_latency.py` measures the before and after against a recorded turn.
These tests pin the correctness that the measurement is worthless without.

────────────────────────────────────────────────────────────────────────────────────────────
THE ONE THAT MATTERS: AN INTERRUPTED STREAM SAVES NOTHING
────────────────────────────────────────────────────────────────────────────────────────────

Every other failure here is visible. This one would not be. The Redis turn cache is the only
thing the panel endpoint writes, and a half-written turn frozen into it would be served for
fifteen minutes as a COMPLETE turn — so the candidate would lose two of their four lines on
every retry, reconnect and refresh, long after the blip that caused it. Nothing would look
broken; the room would just say less than it meant to.

Three separate things make that impossible, and the tests below assert all three rather than
trusting any one:

  1. `generate._stream_into` raises when a stream ends without its terminator, so a truncated
     answer is a FAILED ATTEMPT rather than a short one.
  2. `_remember_turn` is only ever reached with a turn that came back from
     `generate_structured`, which means it parsed and validated as a whole.
  3. `StreamedObjects` never emits a partial object, at any cut point — asserted by cutting a
     real turn at every single character position, which is the only way to be sure rather
     than lucky.

WHAT IS NOT TESTED HERE. No test calls a real provider or a real vendor: what a model returns
is not this repository's to guarantee. Every stream below is a scripted one, which is what
makes "cut it at character 137" a thing that can be asked at all.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.services.ai.base_provider import (
    BaseAIProvider,
    ProviderRequest,
    ProviderResponse,
    StreamChunk,
)
from app.services.ai.generate import _stream_into
from app.services.ai.stream_parser import StreamedObjects, _match_object

#: A real-shaped panel turn, with the things that break naive scanners: an em dash, a quoted
#: brace, an escaped quote, and unicode.
TURN = json.dumps(
    {
        "turns": [
            {
                "speaker": "Anil",
                "text": 'Okay — so you said the block after "{" runs first. Is that right?',
                "tone": "asking",
            },
            {"speaker": "Priya", "text": "Priya here. Let me take the next one.", "tone": "aside"},
            {
                "speaker": "Priya",
                "text": "Tell me what happens when two threads write at once.",
                "tone": "asking",
            },
        ],
        "asked_question": True,
        "candidate_turn": "answered",
    },
    ensure_ascii=False,
)


class TestReadingAnObjectThatIsStillBeingWritten:
    def test_every_line_is_emitted_from_a_character_at_a_time_stream(self):
        """
        The worst case a real provider can produce: one character per delta.
        """
        parser = StreamedObjects()
        got = [obj for ch in TURN for obj in parser.feed(ch)]
        assert [o["speaker"] for o in got] == ["Anil", "Priya", "Priya"]

    def test_the_same_lines_come_out_however_the_stream_is_chopped(self):
        """
        A delta boundary is arbitrary — it can fall inside a word, inside an escape, or
        between a key and its value — and none of that may change the result.
        """
        for size in (1, 2, 3, 7, 13, 64, 512, len(TURN)):
            parser = StreamedObjects()
            got = [
                obj
                for i in range(0, len(TURN), size)
                for obj in parser.feed(TURN[i : i + size])
            ]
            assert [o["speaker"] for o in got] == ["Anil", "Priya", "Priya"], f"size {size}"
            assert got[0]["text"].startswith("Okay — so you said")

    def test_a_brace_inside_a_line_does_not_close_the_object_early(self):
        # Interview dialogue is full of braces and quotes — a panelist reading code back, a
        # correction quoting a snippet. Counting braces without knowing which are inside a
        # string truncates the line, and the candidate is asked half a question.
        parser = StreamedObjects()
        got = list(parser.feed(TURN))
        assert '"{"' in got[0]["text"]

    def test_an_escaped_quote_does_not_end_the_string(self):
        raw = json.dumps(
            {"turns": [{"speaker": "Anil", "text": 'He said \\"no\\" twice }', "tone": "asking"}]}
        )
        parser = StreamedObjects()
        got = list(parser.feed(raw))
        assert len(got) == 1
        assert got[0]["text"].endswith("}")

    def test_it_only_reads_the_turns_array(self):
        # Anchored on the key rather than on the first "[", so an array elsewhere in the
        # response cannot start emitting objects that are not dialogue.
        raw = '{"notes": [{"speaker": "Ghost", "text": "not dialogue"}], "turns": []}'
        assert list(StreamedObjects().feed(raw)) == []

    @pytest.mark.parametrize("cut", range(1, len(TURN)))
    def test_no_partial_object_is_ever_emitted_at_any_cut_point(self, cut: int):
        """
        THE EXHAUSTIVE ONE. Every prefix of a real turn, one per character.

        Whatever comes out must be a WHOLE line — every key present, the text identical to the
        finished one. A parser that emitted "as much of line two as arrived" would pass a
        spot-check at three or four cut points and fail here at dozens.
        """
        whole = {o["text"]: o for o in StreamedObjects().feed(TURN)}
        for obj in StreamedObjects().feed(TURN[:cut]):
            assert set(obj) == {"speaker", "text", "tone"}
            assert obj["text"] in whole, "a truncated line escaped the parser"
            assert obj == whole[obj["text"]]

    def test_an_object_that_has_not_closed_returns_none_rather_than_guessing(self):
        assert _match_object('{"a": 1', 0) is None
        assert _match_object('{"a": "}"', 0) is None
        assert _match_object('{"a": "}"}', 0) == 10


class _ScriptedProvider(BaseAIProvider):
    """
    A provider that yields exactly what it is told to, and stops exactly where it is told to.

    The point of scripting it is `terminate`: a real provider cannot be asked to die after
    the third delta, and dying after the third delta is the case that matters.
    """

    def __init__(self, deltas: list[str], *, terminate: bool = True) -> None:
        self._deltas = deltas
        self._terminate = terminate

    @property
    def provider_name(self) -> str:
        return "scripted"

    @property
    def model_name(self) -> str:
        return "scripted-1"

    @property
    def supports_streaming(self) -> bool:
        return True

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            content="".join(self._deltas), model=self.model_name, prompt_tokens=1,
            completion_tokens=1, finish_reason="stop",
        )

    async def stream(self, request: ProviderRequest):
        for d in self._deltas:
            yield StreamChunk(text=d)
        if self._terminate:
            yield StreamChunk(final=await self.complete(request))

    async def health_check(self) -> bool:
        return True


def _request() -> ProviderRequest:
    from app.services.ai.base_provider import ProviderMessage

    return ProviderRequest(
        messages=[ProviderMessage(role="user", content="x")], max_tokens=320
    )


class TestATruncatedStreamIsAFailureAndNotAShortAnswer:
    async def test_a_finished_stream_returns_the_response(self):
        seen: list[str] = []
        resp = await _stream_into(
            _ScriptedProvider(["a", "b", "c"]), _request(), seen.append
        )
        assert seen == ["a", "b", "c"]
        assert resp.content == "abc"

    async def test_a_stream_with_no_terminator_raises(self):
        """
        THE HEART OF IT. The deltas were real, the text looks like an answer, and the only
        thing distinguishing it from a finished one is the missing final chunk. Returning the
        accumulated text would hand the caller half a JSON object to validate — and the
        dangerous case is the half that parses.
        """
        from app.services.ai.base_provider import ProviderError

        seen: list[str] = []
        with pytest.raises(ProviderError, match="truncated"):
            await _stream_into(
                _ScriptedProvider(["{\"turns\": [", "{\"speaker\""], terminate=False),
                _request(),
                seen.append,
            )
        # The deltas WERE delivered — the caller has shown provisional text and must throw it
        # away. That is why the failure has to be loud.
        assert seen

    async def test_a_provider_that_raises_mid_stream_propagates(self):
        from app.services.ai.base_provider import ProviderError

        class _Dies(_ScriptedProvider):
            async def stream(self, request):
                yield StreamChunk(text="{\"turns\": [")
                raise ProviderError("connection reset", provider="scripted")

        with pytest.raises(ProviderError):
            await _stream_into(_Dies([]), _request(), lambda _d: None)


class TestStreamingIsTheSameCallAndNotACheaperOne:
    """
    `generate_structured` streams INSIDE its existing loop, so everything that made the
    non-streaming path trustworthy still applies. These assert that rather than assuming it.
    """

    async def test_the_validated_result_is_returned_not_the_streamed_text(self, monkeypatch):
        from app.services.ai import generate as gen
        from app.services.ai.schemas import InterviewPanelTurn

        provider = _ScriptedProvider([TURN[:40], TURN[40:]])
        monkeypatch.setattr(gen, "get_ai_providers", lambda: [provider])
        monkeypatch.setattr(gen, "eligible_providers", lambda providers, **_kw: providers)

        seen: list[str] = []
        parsed, raw = await gen.generate_structured(
            InterviewPanelTurn,
            _request().messages,
            max_tokens=320,
            on_delta=seen.append,
        )
        assert "".join(seen) == TURN
        assert isinstance(parsed, InterviewPanelTurn)
        assert [t.speaker for t in parsed.turns] == ["Anil", "Priya", "Priya"]
        assert raw == TURN

    async def test_usage_is_still_recorded_for_a_streamed_call(self, monkeypatch):
        """
        A streamed call that the ledger could not see would be spend nothing can account for,
        and `tests/test_ai_usage.py` fails the build for exactly that on the non-streamed
        path. The terminator carries the token counts so both paths record identically.
        """
        from app.services.ai import generate as gen
        from app.services.ai.schemas import InterviewPanelTurn

        recorded: list[dict] = []

        async def _record(**kw):
            recorded.append(kw)

        monkeypatch.setattr(gen, "get_ai_providers", lambda: [_ScriptedProvider([TURN])])
        monkeypatch.setattr(gen, "eligible_providers", lambda providers, **_kw: providers)
        monkeypatch.setattr(gen, "record_call", _record)

        await gen.generate_structured(
            InterviewPanelTurn,
            _request().messages,
            max_tokens=320,
            context="interview_panel_turn",
            on_delta=lambda _d: None,
        )
        assert recorded, "a streamed call recorded no usage"
        assert recorded[0]["feature"] == "interview_panel_turn"
        assert recorded[0]["outcome"] == "ok"

    async def test_a_retry_tells_the_caller_to_start_again(self, monkeypatch):
        """
        A second attempt rewrites the answer from the beginning. Without `on_restart` the two
        attempts' deltas would be concatenated and the candidate would watch the panel say
        everything twice.
        """
        from app.services.ai import generate as gen
        from app.services.ai.schemas import InterviewPanelTurn

        monkeypatch.setattr(
            gen,
            "get_ai_providers",
            lambda: [_ScriptedProvider(["not json at all"]), _ScriptedProvider([TURN])],
        )
        monkeypatch.setattr(gen, "eligible_providers", lambda providers, **_kw: providers)
        monkeypatch.setattr(gen, "record_call", lambda **_kw: asyncio.sleep(0))

        events: list[str] = []
        await gen.generate_structured(
            InterviewPanelTurn,
            _request().messages,
            max_tokens=320,
            attempts_per_provider=1,
            on_delta=lambda d: events.append(f"delta:{d[:6]}"),
            on_restart=lambda: events.append("restart"),
        )
        assert "restart" in events
        assert events.index("restart") > 0, "restart fired before anything was written"
        assert events[0].startswith("delta:"), "the first attempt streamed nothing"

    async def test_no_restart_is_reported_when_the_first_attempt_works(self, monkeypatch):
        from app.services.ai import generate as gen
        from app.services.ai.schemas import InterviewPanelTurn

        monkeypatch.setattr(gen, "get_ai_providers", lambda: [_ScriptedProvider([TURN])])
        monkeypatch.setattr(gen, "eligible_providers", lambda providers, **_kw: providers)
        monkeypatch.setattr(gen, "record_call", lambda **_kw: asyncio.sleep(0))

        events: list[str] = []
        await gen.generate_structured(
            InterviewPanelTurn,
            _request().messages,
            max_tokens=320,
            on_delta=lambda _d: None,
            on_restart=lambda: events.append("restart"),
        )
        assert events == []

    async def test_a_provider_that_cannot_stream_still_works(self, monkeypatch):
        """
        The default `stream` yields everything at once, so a provider with no streaming
        support needs no fallback path at the call site — the caller gets one delta instead
        of forty and is otherwise unaffected.
        """
        from app.services.ai import generate as gen
        from app.services.ai.schemas import InterviewPanelTurn

        class _NoStream(_ScriptedProvider):
            @property
            def supports_streaming(self) -> bool:
                return False

        monkeypatch.setattr(gen, "get_ai_providers", lambda: [_NoStream([TURN])])
        monkeypatch.setattr(gen, "eligible_providers", lambda providers, **_kw: providers)
        monkeypatch.setattr(gen, "record_call", lambda **_kw: asyncio.sleep(0))

        seen: list[str] = []
        parsed, _raw = await gen.generate_structured(
            InterviewPanelTurn,
            _request().messages,
            max_tokens=320,
            on_delta=seen.append,
        )
        # Nothing streamed, because nothing could — and the turn is still correct.
        assert seen == []
        assert len(parsed.turns) == 3


class TestNothingPartialIsEverRemembered:
    """
    The Redis turn cache is the only thing the panel endpoint writes. These pin that it is
    written from a validated turn and from nothing else.
    """

    def test_the_cache_write_happens_after_validation_in_the_source(self):
        """
        A SOURCE ASSERTION, because the ordering is the guarantee and no runtime test can
        show that a line does NOT run before another one. What it catches is the regression
        that actually happens: somebody moving the cache write earlier "so the client sees it
        sooner" during a refactor.
        """
        import inspect
        import pathlib

        src = (
            pathlib.Path(inspect.getfile(TestNothingPartialIsEverRemembered)).resolve().parents[1]
            / "app" / "api" / "v1" / "panel.py"
        ).read_text()
        stream_fn = src[src.index("async def panel_turn_stream("):]
        body = stream_fn[: stream_fn.index("return StreamingResponse(")]
        assert "_finalise_turn(turn, request)" in body
        assert body.index("turn, _raw = await task") < body.index("_remember_turn("), (
            "the cache is written before the model call has been awaited and validated"
        )
        assert body.index("_finalise_turn(") < body.index("_remember_turn("), (
            "the cache is written before the turn is validated"
        )

    def test_the_error_path_writes_nothing(self):
        import inspect
        import pathlib

        src = (
            pathlib.Path(inspect.getfile(TestNothingPartialIsEverRemembered)).resolve().parents[1]
            / "app" / "api" / "v1" / "panel.py"
        ).read_text()
        stream_fn = src[src.index("async def panel_turn_stream("):]
        # Everything between catching the failure and returning from it.
        handler = stream_fn[
            stream_fn.index("except AIProviderUnavailableError") : stream_fn.index("finally:")
        ]
        assert "_remember_turn" not in handler
        assert "cache_set" not in handler

    def test_the_generation_task_is_cancelled_if_the_client_goes_away(self):
        import inspect
        import pathlib

        src = (
            pathlib.Path(inspect.getfile(TestNothingPartialIsEverRemembered)).resolve().parents[1]
            / "app" / "api" / "v1" / "panel.py"
        ).read_text()
        stream_fn = src[src.index("async def panel_turn_stream("):]
        assert "finally:" in stream_fn
        assert "task.cancel()" in stream_fn


class TestTheWireFormat:
    def test_an_event_is_never_split_by_a_newline_in_the_payload(self):
        """
        SSE frames end at a blank line, so a raw newline inside the data would split one
        event into two and the second half would be unparseable. A panel line legitimately
        contains newlines — a correction quoting code does.
        """
        from app.api.v1.panel import _sse

        frame = _sse("line", {"speaker": "Anil", "text": "one\ntwo\n\nthree"})
        assert frame.endswith("\n\n")
        assert frame.count("\n\n") == 1
        body = frame.split("data: ", 1)[1].strip()
        assert json.loads(body)["text"] == "one\ntwo\n\nthree"

    def test_unicode_survives_the_wire(self):
        from app.api.v1.panel import _sse

        frame = _sse("line", {"text": "Okay — so, résumé"})
        assert "—" in frame
        assert json.loads(frame.split("data: ", 1)[1])["text"] == "Okay — so, résumé"

    def test_each_kind_of_event_is_named(self):
        from app.api.v1.panel import _sse

        assert _sse("done", {}).startswith("event: done\n")
        assert _sse("restart", {}).startswith("event: restart\n")

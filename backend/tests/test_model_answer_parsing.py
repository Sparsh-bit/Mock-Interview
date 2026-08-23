"""
The ideal answer arrives whole — tests/test_model_answer_parsing.py

REPORTED: "the detailed analysis the answers were also not able to get generated when hitting
the button of show ideal answers".

TWO INDEPENDENT FAULTS, both in the shared JSON extractor, both measured against the live
provider before being fixed. Neither was a timeout and neither was the model failing.

  1. A LITERAL CONTROL CHARACTER KILLED THE WHOLE RESPONSE. The call completed normally —
     `stop_reason=end_turn`, 893 of 1400 tokens — and then failed validation, because a raw
     newline inside a JSON string is forbidden by strict JSON. `json.loads` raised "Invalid
     control character", every extraction pattern hit the same error, and the response was
     reported as containing no JSON at all. With `attempts_per_provider=1` that was an
     immediate 503. It scales with prose length, which is why long design answers failed and
     short conceptual ones did not, and why it looked intermittent.

  2. THE MODEL SPLIT ONE OBJECT ACROSS TWO FENCED BLOCKS. For a design question it reliably
     wrote `{"model_answer": ...}` and then a SECOND block containing `what_was_missing`,
     `key_points` and `verdict_line`. The extractor took the first match, so the request
     succeeded, nothing was logged, and the three coaching fields sat at their empty defaults
     — losing the only part of the response a candidate needed. This is the worse of the two
     bugs precisely because it looked like success.

These are tested at the parser rather than through the endpoint: the fault was never in the
endpoint, and every other AI call site in the app shares this extractor and was exposed to
both.
"""

from __future__ import annotations

import pytest

from app.services.ai.generate import _parser
from app.services.ai.schemas import ModelAnswerResponse


def _parse(raw: str) -> ModelAnswerResponse:
    return _parser.parse(raw, ModelAnswerResponse)


class TestARawControlCharacterIsNotFatal:
    def test_a_literal_newline_inside_a_string_still_parses(self):
        # Exactly what the provider sent: a real newline inside the string value, not "\\n".
        raw = '{"model_answer": "First line.\nSecond line.", "verdict_line": "ok"}'
        parsed = _parse(raw)
        assert "First line." in parsed.model_answer
        assert "Second line." in parsed.model_answer

    def test_a_tab_inside_a_string_still_parses(self):
        raw = '{"model_answer": "before\tafter", "verdict_line": "ok"}'
        assert "after" in _parse(raw).model_answer

    def test_it_survives_inside_a_fenced_block_too(self):
        # Fixing only the fast path would leave the fenced route throwing on the same
        # character, so the same response would still fail whenever it arrived fenced.
        raw = '```json\n{"model_answer": "line one\nline two"}\n```'
        assert "line two" in _parse(raw).model_answer

    def test_genuinely_broken_json_is_still_rejected(self):
        # `strict=False` permits control characters in strings and nothing else. A response
        # with no object in it must still fail loudly rather than parse into defaults.
        from app.core.exceptions import AppError

        with pytest.raises((AppError, Exception)):
            _parse("I am afraid I cannot help with that request.")


class TestAnObjectSplitAcrossBlocksIsReassembled:
    #: The exact shape the provider returned for a design question.
    TWO_BLOCKS = '''```json
{
  "model_answer": "I would use a table with an indexed unique short_code, and base62-encode a counter for ID generation."
}
```

```json
{
  "what_was_missing": ["No collision handling", "No caching strategy"],
  "key_points": ["base62 over random", "Redis read-through", "read-heavy workload"],
  "verdict_line": "Right instincts, surface level."
}
```'''

    def test_every_field_survives_the_split(self):
        parsed = _parse(self.TWO_BLOCKS)
        assert "base62" in parsed.model_answer
        # THE REGRESSION THIS EXISTS FOR: these were empty, and empty looked like success.
        assert len(parsed.what_was_missing) == 2
        assert len(parsed.key_points) == 3
        assert parsed.verdict_line == "Right instincts, surface level."

    def test_an_earlier_fragment_wins_a_collision(self):
        # Keeps the old first-match-wins behaviour for anything that already worked, so the
        # merge cannot change the meaning of a response that was parsing correctly before.
        raw = (
            '```json\n{"model_answer": "the real one"}\n```\n\n'
            '```json\n{"model_answer": "a later contradiction", "verdict_line": "v"}\n```'
        )
        parsed = _parse(raw)
        assert parsed.model_answer == "the real one"
        assert parsed.verdict_line == "v"

    def test_a_single_block_is_unchanged(self):
        # The common case must not be touched by any of this.
        raw = (
            '```json\n{"model_answer": "one block", "what_was_missing": ["a"],'
            ' "key_points": ["b"], "verdict_line": "v"}\n```'
        )
        parsed = _parse(raw)
        assert parsed.model_answer == "one block"
        assert parsed.what_was_missing == ["a"]

    def test_both_faults_at_once(self):
        # They co-occur in practice — a long answer is both the reason the model splits the
        # object and the reason a stray newline lands in it.
        raw = (
            '```json\n{"model_answer": "line one\nline two"}\n```\n\n'
            '```json\n{"what_was_missing": ["gap"], "key_points": ["kp"],'
            ' "verdict_line": "v"}\n```'
        )
        parsed = _parse(raw)
        assert "line two" in parsed.model_answer
        assert parsed.what_was_missing == ["gap"]
        assert parsed.key_points == ["kp"]


class TestTheEndpointIsSizedForWhatTheModelActuallySends:
    def test_the_ceiling_covers_the_largest_measured_shape(self):
        # A design question's full response measured 2700-4100 characters of JSON, roughly
        # 700-1000 output tokens. At the previous 900 the coaching fields were truncated away
        # and the salvage path returned them empty — a success that dropped the useful half.
        from app.core.config import settings

        assert settings.MODEL_ANSWER_MAX_TOKENS >= 1200

    def test_it_retries_like_every_other_call_site(self):
        # With one attempt, a single unusable response was a 503 the candidate read as "the
        # ideal answer will not generate".
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parents[1] / "app/api/v1/analysis.py"
        ).read_text()
        assert "attempts_per_provider=2" in src
        assert "attempts_per_provider=1" not in src

    def test_neither_figure_is_hardcoded(self):
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parents[1] / "app/api/v1/analysis.py"
        ).read_text()
        assert "settings.MODEL_ANSWER_MAX_TOKENS" in src
        assert "settings.MODEL_ANSWER_BUDGET_SECONDS" in src

    def test_the_budget_stays_inside_what_the_client_waits(self):
        # The client allows 90s for this call. The server must lose that race deliberately and
        # return a real error, rather than having the connection cut from under it.
        import pathlib
        import re

        from app.core.config import settings

        hook = (
            pathlib.Path(__file__).resolve().parents[2] / "frontend/src/hooks/useData.ts"
        ).read_text()
        at = hook.index("useGenerateModelAnswer")
        m = re.search(r"timeout:\s*([\d_]+)", hook[at : at + 900])
        assert m, "the client no longer sets a timeout for this call"
        client_seconds = int(m.group(1).replace("_", "")) / 1000
        assert client_seconds > settings.MODEL_ANSWER_BUDGET_SECONDS

"""
A response cut off by max_tokens is not garbage — tests/test_ai_truncation_salvage.py

WHAT THIS IS FOR. Resume analysis asked for 20 skills and 6 projects in one JSON
object under a 2600-token ceiling that the answer never once fit inside. Measured
against the live providers, every attempt of every run came back
`stop_reason=max_tokens` / `finish_reason=length`, with the `skills` array complete
and the `projects` array after it clipped mid-object. The parser then rejected the
whole body, so 27 successfully extracted skills were thrown away with the broken
tail, `generate_structured` retried, the retry hit the same ceiling in the same
place, and the candidate's upload stored no skills and no projects at all.

The ceilings that caused that are fixed at the call sites and the analysis is split
in two, but a ceiling is a ceiling: any of them can be reached by an unusually
verbose answer, and every AI-backed feature in the app is one truncation away from
discarding work it has already paid for. So the parser salvages the complete prefix.

WHAT IT MUST NOT DO is invent anything, or turn a genuinely malformed response into
a silent partial success. Both directions are pinned below.
"""

from __future__ import annotations

import pytest

from app.services.ai.json_validator import AIValidationError, JSONValidator
from app.services.ai.response_parser import ResponseParser, _repair_truncated_json
from app.services.ai.schemas import ResumeProjectsHalf, ResumeSkillsHalf

_parser = ResponseParser(JSONValidator())

#: The measured failure, shortened: a fenced body whose skills array is complete and
#: whose projects array is cut off inside an object. The real one was 2600 tokens.
TRUNCATED_AT_A_PROJECT = """```json
{
  "skills": [
    {"name": "Java", "confidence": "explicit"},
    {"name": "Spring Boot", "confidence": "explicit"},
    {"name": "PostgreSQL", "confidence": "inferred"}
  ],
  "projects": [
    {"name": "E-Commerce Platform", "technologies": ["Spring Boot", "Redis"]},
    {"name": "Real-Time Chat", "technologies": ["WebSocket", "Mon"""


class TestWhatSurvivesATruncation:
    def test_the_complete_prefix_is_kept(self):
        """
        THE TEST THIS FILE EXISTS FOR. Every skill the model finished writing has to
        come back; before the salvage this raised and the whole call was discarded.
        """
        half = _parser.parse(TRUNCATED_AT_A_PROJECT, ResumeSkillsHalf)
        assert [s.name for s in half.skills] == ["Java", "Spring Boot", "PostgreSQL"]

    def test_nothing_at_the_cut_is_invented(self):
        """
        THE LINE THE SALVAGE MUST NOT CROSS. Both project NAMES survive, because the
        model finished writing both — that is the point of keeping the prefix. What
        must not survive is the value it was cut off inside: the technology list ends
        at "WebSocket" and the clipped "Mon… is dropped rather than kept as a
        half-written string. A fabricated detail is worse than a missing one, because
        the interviewer then asks the candidate about something that is not on their
        resume.
        """
        half = _parser.parse(TRUNCATED_AT_A_PROJECT, ResumeProjectsHalf)
        assert [p.name for p in half.projects] == ["E-Commerce Platform", "Real-Time Chat"]
        assert half.projects[1].technologies == ["WebSocket"]

    def test_a_cut_inside_a_string_is_survivable(self):
        """The cut lands mid-string far more often than on a clean boundary."""
        assert _parser.parse(
            '{"skills": [{"name": "Java", "confidence": "explicit"}, {"name": "Spri',
            ResumeSkillsHalf,
        ).skills[0].name == "Java"

    def test_a_cut_inside_a_nested_array_is_survivable(self):
        half = _parser.parse(
            '{"projects": [{"name": "Chat", "technologies": ["WebSocket", "Mongo',
            ResumeProjectsHalf,
        )
        assert half.projects[0].name == "Chat"
        assert half.projects[0].technologies == ["WebSocket"]

    def test_an_escaped_quote_before_the_cut_does_not_confuse_the_scan(self):
        """
        The scan has to track escape state, or a `\\"` inside a description flips it
        into thinking the string ended and every bracket after it is miscounted.
        """
        half = _parser.parse(
            r'{"projects": [{"name": "A \"real\" thing", "role": "Dev"}, {"name": "B',
            ResumeProjectsHalf,
        )
        assert half.projects[0].name == 'A "real" thing'
        assert half.projects[0].role == "Dev"


class TestWhatMustStillFail:
    """
    The salvage is a last resort, not a way to accept anything. It runs only after
    normal extraction has failed, and it must not paper over a different failure.
    """

    def test_a_body_with_no_json_at_all_still_raises(self):
        with pytest.raises(AIValidationError):
            _parser.parse("I cannot help with that request.", ResumeSkillsHalf)

    def test_a_cut_before_a_single_complete_element_yields_nothing(self):
        """Nothing was finished, so there is nothing to keep and no repair to make."""
        assert _repair_truncated_json('{"skills": [{"name": "Ja') is None

    def test_a_mismatched_bracket_is_not_treated_as_truncation(self):
        """
        `}]` closing an object with an array bracket is a malformed response, not a
        cut-off one. Salvaging it would hide a real provider or prompt problem.
        """
        assert _repair_truncated_json('{"skills": [{"name": "Java"}]}]') is None

    def test_a_balanced_body_is_not_repaired(self):
        """
        If the brackets balance, truncation is not what is wrong with it — the caller
        already failed to parse it, and the honest answer is to report that.
        """
        assert _repair_truncated_json('{"skills": [{"name": "Java",}]}') is None

    def test_salvage_still_goes_through_schema_validation(self):
        """
        A salvaged fragment is not trusted. It is validated like any other response,
        so a truncated body whose surviving prefix is the wrong shape is rejected —
        and at the call sites, an `is_valid` predicate rejects it a second time for
        being schema-valid but useless.
        """
        with pytest.raises(AIValidationError):
            _parser.parse('{"skills": [{"nome": "Java"}, {"nome": "Spri', ResumeSkillsHalf)

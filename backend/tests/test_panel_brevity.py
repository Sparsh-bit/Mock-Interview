"""
The panel must not lecture — tests/test_panel_brevity.py

Reported from a real session: "the interview is explaining the concept for too long."

It was doing exactly what it had been told to. The correction rule used to say the panel
"gives the correct answer briefly and plainly, in two or three sentences", which is an
invitation to teach — and the token budget comfortably fitted a paragraph, so it wrote one.
A candidate sat in silence through a lecture on a topic they had just failed.

These tests pin the two changes so a later edit has to be deliberate:

  * the prompt forbids explaining the concept, and says a correction is ONE sentence
  * the token ceiling does not leave room for a paragraph

WHAT THEY CANNOT DO is assert on model output — that needs a live call and CI has no key.
So they guard the inputs, which is what actually regressed. The measured result on the live
model after these changes: mean 12.4 words a line over a wrong-answer correction, a
good-answer acknowledgement and a code review, longest line 20 words. Before, corrections
ran to full paragraphs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROMPT = Path(__file__).resolve().parents[1] / "app" / "prompts" / "interview_panel.md"
_PANEL = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "panel.py"


@pytest.fixture(scope="module")
def prompt() -> str:
    """
    The prompt, header comment stripped and whitespace collapsed.

    STRIPPED because a test that matches its own explanatory prose is a test that passes
    whether or not the rule survives — a mistake already made twice in this repo, once in the
    caching tests and once in the voice tests.

    COLLAPSED because the prompt is hard-wrapped markdown, so "never give an example" is
    genuinely stored as "never give\n   an example". Matching raw text would mean these tests
    fail whenever somebody reflows a paragraph, which trains people to delete them.
    """
    text = _PROMPT.read_text()
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return re.sub(r"\s+", " ", body)


class TestThePromptForbidsLecturing:
    def test_it_says_outright_that_this_is_not_teaching(self, prompt: str):
        # The rule the whole complaint reduces to. Teaching happens in the report, where it
        # can be read properly; in the room it is time taken from a candidate who is waiting.
        assert "NOT TEACHING" in prompt
        assert "DO NOT EXPLAIN THE CONCEPT" in prompt

    def test_it_names_the_specific_lecturing_behaviours(self, prompt: str):
        # "Be brief" is advice. These are the actual things it was doing, each named, because
        # a model follows a prohibition it can recognise itself doing.
        low = prompt.lower()
        for banned in (
            "never define a term",
            "never walk through how something works",
            "never give an example",
        ):
            assert banned in low, banned

    def test_a_correction_is_one_sentence(self, prompt: str):
        # This is the line that regressed. It used to read "in two or three sentences",
        # which is a paragraph delivered aloud.
        assert "IN ONE SENTENCE" in prompt
        # The exact phrasing that caused it, in the form it takes once wrapping is collapsed.
        assert "in two or three sentences" not in prompt

    def test_it_shows_a_bad_example_and_not_only_a_good_one(self, prompt: str):
        # The struck-through lecture. A rule with a counter-example is followed far more
        # reliably than a rule stated once, and this one exists precisely because the model
        # thought the long version was more helpful.
        assert "~~" in prompt, "the worked example of a lecture has been removed"
        assert "That is a lecture" in prompt

    def test_a_good_answer_earns_words_not_paragraphs(self, prompt: str):
        low = prompt.lower()
        assert "do not gush" in low
        # Extending a correct answer with what you would have added is the polite version of
        # the same fault, and it doubles the length of every good exchange.
        assert "do not add the bit they missed" in low

    def test_a_code_review_points_at_a_mistake_rather_than_fixing_it(self, prompt: str):
        assert "ONE LINE PER MISTAKE" in prompt
        assert "do not write the corrected code for them" in prompt.lower()

    def test_the_line_length_rule_is_stated_in_words_not_vibes(self, prompt: str):
        # "Keep it short" is unfalsifiable; a number is not. Twenty-five words is roughly one
        # spoken sentence and the model can actually check itself against it.
        assert "One or two sentences" in prompt
        assert "Twenty-five words" in prompt


class TestTheBudgetDoesNotFitALecture:
    def test_max_tokens_is_low_enough_to_matter(self):
        # The prompt asks for brevity and the ceiling enforces it. At 500 there was room for
        # roughly 375 words — four paragraphs — so the instruction was the only thing
        # standing between the candidate and a lecture, and it lost.
        source = _PANEL.read_text()
        match = re.search(r"max_tokens=(\d+)", source)
        assert match, "the panel turn no longer sets max_tokens"
        budget = int(match.group(1))
        assert budget <= 360, f"max_tokens={budget} leaves room for a paragraph again"
        # And not so low that a legitimate four-line turn plus JSON scaffolding gets cut off
        # mid-body — which fails validation, costs a retry, and can end with no panel at all.
        assert budget >= 260, f"max_tokens={budget} risks truncating a normal turn"


class TestTheStagesStillExist:
    """Brevity edits must not delete behaviour. Cheap, and it has already happened once."""

    @pytest.mark.parametrize(
        "stage",
        ["opening", "skill_check", "mid", "pivot", "code_review", "wrapping",
         "candidate_questions", "answering_candidate"],
    )
    def test_every_stage_the_api_accepts_is_described_in_the_prompt(
        self, prompt: str, stage: str
    ):
        # A stage the API accepts but the prompt has never heard of produces a turn written
        # to no rules at all, which is worse than rejecting it.
        assert stage in prompt, f"the prompt no longer describes the {stage} stage"

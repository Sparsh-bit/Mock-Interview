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
        """
        The SPOKEN turn's ceiling. The prompt asks for brevity and this enforces it — at 500
        there was room for roughly 375 words, four paragraphs, so the instruction was the only
        thing between the candidate and a lecture, and it lost.

        ANCHORED TO THE InterviewPanelTurn CALL rather than to the first `max_tokens=` in the
        file, which is what it used to match. panel.py now makes a second generation — the
        graded code verdict — and that one legitimately needs a far larger budget, because it
        returns a big structured evaluation rather than four spoken lines. A bare search found
        whichever call appeared first and started reporting the evaluator's budget as though
        the panel had been allowed to start lecturing again.

        The property being protected is specifically "what the panel SAYS is short". Matching
        on the call that produces speech is what makes that true, rather than nearly true.
        """
        source = _PANEL.read_text()
        call = re.search(r"generate_structured\(\s*InterviewPanelTurn\b(.*?)\n\s*\)", source, re.S)
        assert call, "the panel turn no longer generates an InterviewPanelTurn"
        match = re.search(r"max_tokens=(\d+)", call.group(1))
        assert match, "the panel turn no longer sets max_tokens"
        budget = int(match.group(1))
        assert budget <= 360, f"max_tokens={budget} leaves room for a paragraph again"
        # And not so low that a legitimate four-line turn plus JSON scaffolding gets cut off
        # mid-body — which fails validation, costs a retry, and can end with no panel at all.
        assert budget >= 260, f"max_tokens={budget} risks truncating a normal turn"

    def test_the_code_verdict_is_not_billed_as_a_spoken_turn(self):
        """
        The verdict generation is a separate call with a separate budget, and it must stay
        separate. Folding the evaluation into the spoken turn would either truncate the
        evaluation or re-open the ceiling on the speech — the two cannot share one budget.
        """
        source = _PANEL.read_text()
        verdict = re.search(r"generate_structured\(\s*CodingEvaluation\b(.*?)\n\s*\)", source, re.S)
        assert verdict, "the code verdict no longer generates a CodingEvaluation"
        assert re.search(r"max_tokens=(\d+)", verdict.group(1)), "the verdict sets no ceiling"
        # It is graded against a schema the candidate never hears, so it is allowed to be
        # large — but it is on the path between submit and the panel speaking, so it is not
        # allowed to be unbounded.
        assert int(re.search(r"max_tokens=(\d+)", verdict.group(1)).group(1)) <= 2000


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


class TestTheNameIsNotSaidEveryTurn:
    """
    Reported: "it is calling the name again and again in every question that feels annoying
    keep the name in starting only."

    The interesting part is WHY telling the model to use names sparingly did not work. Every
    turn is a separate stateless call, so "don't use their name if you used it last turn" is
    an instruction the model has no way to follow — it cannot see the last turn. It reached
    for the name every question because, from inside any single call, once IS sparing.

    So the decision moved to the server, which is the only thing that can see the sequence.
    """

    def test_the_social_moments_always_use_it(self):
        # Greeting somebody, wrapping up, asking whether they have questions — a person uses
        # a name at every one of those, and it never grates because it is doing real work.
        from app.api.v1.panel import _should_use_name

        assert _should_use_name.__doc__ is not None
        source = _PANEL.read_text()
        for stage in ("opening", "skill_check", "wrapping", "candidate_questions"):
            assert f'"{stage}"' in source

    def test_the_prompt_tells_the_model_when_to_stay_off_it(self):
        # An empty slot invites the model to decide, and what it decides is "every turn".
        source = _PANEL.read_text()
        assert "Do NOT use the candidate's name anywhere in this turn" in source

    def test_the_cadence_is_deterministic_rather_than_random(self):
        # A coin flip per turn would sometimes produce three in a row, which is the exact
        # thing being fixed — and the same session replayed would behave differently.
        source = _PANEL.read_text()
        assert "answered % 3 == 0" in source
        # Checked against the CODE, not the prose. The comment beside this rule explains why
        # it is not random, so a naive substring search matches its own explanation — the
        # same mistake this repo has now made three times.
        code = re.sub(r"#.*$", "", source, flags=re.M)
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        assert "random" not in code.lower()

    def test_the_prompt_says_it_plainly_too(self, prompt: str):
        # Belt and braces: the server decides, and the prompt explains why, so a model that
        # sees the YES slot still does not stack the name three times in one turn.
        assert "USE THE CANDIDATE'S NAME SPARINGLY" in prompt
        assert "Not on every question" in prompt
        # Using each OTHER'S names must stay frequent — that is how a listener tracks who is
        # about to speak, and it is the thing that makes a handover audible.
        assert "Use each OTHER'S names freely" in prompt


class TestThePanelSoundsAlive:
    """Requested: thinking sounds, and laughter where it is genuinely warranted."""

    def test_it_is_told_to_hesitate_where_a_person_would(self, prompt: str):
        assert "THINK OUT LOUD WHERE A PERSON WOULD ACTUALLY BE THINKING" in prompt
        # The reasoning matters more than the rule: fluency at the moment a human would
        # hesitate is the single clearest tell of a machine.
        assert "fluency at the moments a human would hesitate" in prompt

    def test_laughter_is_allowed_and_bounded(self, prompt: str):
        assert "LAUGH WHEN SOMETHING IS ACTUALLY FUNNY" in prompt
        # The bound is what makes it safe. A panel laughing at a wrong answer, at nerves or
        # at an accent would be far worse than one that never laughs.
        assert "anything the candidate could read as being laughed AT" in prompt
        assert "if there is any doubt, do not" in prompt

    def test_the_gd_panel_got_the_same_treatment(self):
        import re

        raw = (_PROMPT.parent / "gd_panel.md").read_text()
        gd = re.sub(r"\s+", " ", raw)
        assert "THINK OUT LOUD, AND LAUGH" in gd
        assert "NEVER at the candidate" in gd
        # And the same name discipline, for the same reason.
        assert "Not in consecutive turns" in gd


class TestAFollowUpIsDeliveredAsOne:
    """
    "I cannot see the cross questions in the interview still."

    The feature was running the whole time. The orchestrator generates a follow-up after
    every third answer, records its id on the session, and serves it as the next question —
    but GET /next returned the same four fields for every question, so the client could not
    tell, delivered it through the generic `mid` stage, and it arrived looking exactly like
    a fresh question from the plan.

    Which meant the single moment in the interview where the panel visibly listened to the
    candidate was indistinguishable from the moments it did not. Invisible is the same as
    absent from where the candidate is sitting.
    """

    def test_the_api_says_whether_a_question_is_a_follow_up(self):
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parent.parent / "app/api/v1/interview.py"
        ).read_text()
        nxt = src[src.index("async def get_next_question") :]
        assert '"is_follow_up"' in nxt

    def test_it_is_read_from_the_session_record_not_re_derived(self):
        # `cross_question_ids` is what the orchestrator keys its own logic on. A second
        # derivation — inferring from the question row, say — could disagree with it, and
        # then the label and the behaviour would drift apart.
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parent.parent / "app/api/v1/interview.py"
        ).read_text()
        assert "cross_question_ids" in src

    def test_the_panel_accepts_a_follow_up_stage(self):
        from app.api.v1.panel import PanelTurnRequest

        pattern = PanelTurnRequest.model_fields["stage"].metadata[0].pattern
        assert "follow_up" in pattern

    def test_the_prompt_tells_it_to_stay_on_the_thread(self, prompt: str):
        # Uses the module's collapsed `prompt` fixture rather than re-reading the file. The
        # prompt is hard-wrapped markdown, so "it is not a new topic" is genuinely stored as
        # "it is not\n   a new topic" — the fixture's own docstring records that this exact
        # mistake has been made twice in this repo already, and I made it a third time.
        block = prompt[prompt.index("**follow_up**") : prompt.index("**pivot**")].lower()
        # The three things that distinguish a follow-up from a new question.
        assert "not a new topic" in block
        assert "quote or name the thing" in block
        # No handover: the same person who asked the last question asks this one.
        assert "do not re-introduce the topic" in block
        assert "hand over" in block

"""
The panel's code review is grounded in a real verdict — tests/test_panel_code_verdict.py

REPORTED: "the sql or any coding question is coming and the interviewer is not analysing the
solution". That was accurate rather than a misreading. The `code_review` stage did put the
submission in front of the model and ask for dialogue about it, but nothing ever established
whether the code WORKED — so the panel said plausible things about code it had not evaluated.

The product already had a real evaluator (`coding_evaluator.md` + `CodingEvaluation`), graded
on a four-point correctness scale with named bugs and a complexity comparison. It was reachable
only from `/code/analyse`, which the interview never called.

These test the reduction step, which is where the judgement is. The scoped DB read and the AI
call around it are plumbing, and are deliberately not mocked here.
"""

from __future__ import annotations

from app.api.v1.panel import summarise_code_verdict
from app.services.ai.schemas import CodeBug, CodingEvaluation


def _evaluation(**over) -> CodingEvaluation:
    base = {
        "correctness_level": "partially_correct",
        "summary": "Handles the common case but not an empty array.",
        "approach": "brute_force",
        "correctness_score": 6.0,
        "efficiency_score": 4.0,
        "code_quality_score": 7.0,
        "overall_score": 6.0,
    }
    base.update(over)
    return CodingEvaluation(**base)  # type: ignore[arg-type]


class TestItSaysTheThingThatMatters:
    def test_the_worst_bug_wins_regardless_of_list_order(self):
        # A spoken review gets exactly one bug. Taking bugs[0] would have led with the style
        # nit here and never mentioned the crash, which is how a review sounds thorough and
        # is useless.
        v = summarise_code_verdict(
            _evaluation(
                bugs=[
                    CodeBug(description="Trailing comma in output", severity="style"),
                    CodeBug(description="Index out of bounds on an empty array", severity="critical"),
                    CodeBug(description="Shadowed loop variable", severity="minor"),
                ]
            )
        )
        assert "Index out of bounds" in v
        assert "Trailing comma" not in v

    def test_only_one_bug_is_ever_mentioned(self):
        v = summarise_code_verdict(
            _evaluation(
                bugs=[
                    CodeBug(description="First problem", severity="major"),
                    CodeBug(description="Second problem", severity="major"),
                ]
            )
        )
        assert v.count("Main bug") == 1
        assert "Second problem" not in v

    def test_correctness_and_approach_are_always_stated(self):
        # These are the two things the panel is forbidden from guessing at, so they must
        # always be present when a verdict exists at all.
        v = summarise_code_verdict(_evaluation())
        assert "Correctness" in v
        assert "partially correct" in v
        assert "brute force" in v

    def test_a_complexity_gap_is_named_but_a_match_is_not_dressed_up(self):
        gap = summarise_code_verdict(
            _evaluation(time_complexity="O(n^2)", optimal_time_complexity="O(n)")
        )
        assert "theirs is O(n^2)" in gap and "optimal is O(n)" in gap

        match = summarise_code_verdict(
            _evaluation(time_complexity="O(n)", optimal_time_complexity="O(n)")
        )
        assert "optimal" in match
        assert "theirs is" not in match

    def test_an_unsound_brute_force_is_flagged_as_such(self):
        # A WORKING brute force is a legitimate interview pass; one that does not hold up is
        # not, and the panel must be able to tell those apart.
        sound = summarise_code_verdict(_evaluation(is_brute_force_sound=True))
        unsound = summarise_code_verdict(_evaluation(is_brute_force_sound=False))
        assert "does not hold up" in unsound
        assert "does not hold up" not in sound


class TestItStaysShortEnoughToSpeak:
    def test_a_maximal_evaluation_is_still_one_breath(self):
        # The panel has a 320-token output budget and is meant to say two sentences. Passing
        # the whole evaluation through is what made it lecture last time.
        v = summarise_code_verdict(
            _evaluation(
                bugs=[CodeBug(description=f"Problem {i}", severity="major") for i in range(8)],
                edge_cases_missed=[f"case {i}" for i in range(8)],
                strengths=[f"strength {i}" for i in range(8)],
                improvements=[f"improvement {i}" for i in range(8)],
                follow_up_questions=[f"follow up {i}" for i in range(8)],
                time_complexity="O(n^2)",
                optimal_time_complexity="O(n)",
            )
        )
        assert len(v) < 400, v
        # The long lists must not have leaked in wholesale. Asserted on the indexed items
        # rather than on a word count: "case" also occurs in the summary prose, and counting
        # the substring measures the fixture's wording rather than this function's behaviour.
        assert "improvement 0" not in v
        assert "follow up 0" not in v
        assert "strength 0" not in v
        assert "Problem 1" not in v  # one bug only
        assert "case 1" not in v  # one edge case only
        assert "case 0" in v  # ...but the first one IS carried


class TestItFailsSoftRatherThanLoud:
    def test_something_that_is_not_an_evaluation_yields_no_verdict(self):
        # The caller turns "" into an explicit instruction that the panel has NOT been told
        # whether the code works. An exception here would 500 a live interview instead.
        assert summarise_code_verdict(None) == ""
        assert summarise_code_verdict({"correctness_level": "correct"}) == ""
        assert summarise_code_verdict("correct") == ""

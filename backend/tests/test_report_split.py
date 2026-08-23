"""
A report is generated in concurrent parts — tests/test_report_split.py

WHAT THIS PINS, and why each one is here rather than assumed:

  THE PROMPTS STILL CARRY THE RUBRIC. report_summary.md and report_analysis.md are composed
  from report_generator.md, which stays as the canonical scoring rubric. Nothing at runtime
  reads report_generator.md any more, so an edit to it would silently stop reaching the model
  — the split prompts would keep working with the OLD rubric and every score in the product
  would quietly come from a document nobody was editing.

  THE SPLIT SURVIVES PARTIAL FAILURE. That is the entire reason it exists. A batch that fails
  must cost its own questions and nothing else, and a failed summary must still produce a
  scored report when the answers were graded.

  THE ORDER IS THE INTERVIEW'S ORDER. Batches finish out of order because they run
  concurrently, and a report that reads question 13 first is worse than one that is slow.

  DERIVED NUMBERS TRACE TO SOMETHING. `derive_summary` writes the headline score when the
  summary call failed, and every figure in it must come from a model-assigned per-question
  score or a counted delivery metric — never from a constant that looks plausible.
"""

from __future__ import annotations

import pathlib

import pytest

from app.services.ai.schemas import QuestionAnalysisItem, ReportSummaryResponse
from app.services.report.composer import (
    BATCH_SIZE,
    SUMMARY_TOKENS,
    batch_token_budget,
    derive_summary,
    merge,
    order_by_transcript,
    plan_batches,
    readiness_for,
    score_label,
)

PROMPTS = pathlib.Path(__file__).resolve().parents[1] / "app" / "prompts"


def _item(qid: str, score: float, *, missing: list[str] | None = None, quality: str = "partial"):
    return QuestionAnalysisItem(
        question_id=qid,
        question=f"Question {qid}",
        answer_quality=quality,  # type: ignore[arg-type]
        score=score,
        missing_concepts=missing or [],
        ideal_answer_summary="",
    )


class TestTheSplitPromptsStillCarryTheRubric:
    """
    report_generator.md is no longer sent to any model. It is the SOURCE of both split
    prompts, so the only thing keeping it honest is this.
    """

    #: Sentences from report_generator.md that decide what a score MEANS. If any of these
    #: stops appearing in the prompt that actually grades answers, the product's scores have
    #: changed without anybody choosing to change them.
    RUBRIC_MARKERS = (
        "THIS IS THE MOST COMMON HONEST SCORE",
        "Fluent vagueness",
        "Buzzword coverage",
        "A correct answer is a correct answer",
        "This is rare and it must stay rare",
    )

    @pytest.mark.parametrize("template", ["report_analysis", "report_summary"])
    @pytest.mark.parametrize("marker", RUBRIC_MARKERS)
    def test_the_scoring_rubric_reaches_both_prompts(self, template: str, marker: str):
        text = (PROMPTS / f"{template}.md").read_text()
        assert marker in text, (
            f"{template}.md no longer contains the rubric line {marker!r}. Both split prompts "
            "are composed from report_generator.md — if that file was edited, regenerate them, "
            "because nothing at runtime reads report_generator.md any more."
        )

    def test_the_source_rubric_still_exists(self):
        # Guards the test above from passing vacuously if the source is deleted: the markers
        # would still be present in the copies while the thing they are copied FROM is gone.
        source = (PROMPTS / "report_generator.md").read_text()
        for marker in self.RUBRIC_MARKERS:
            assert marker in source, (
                f"report_generator.md no longer contains {marker!r}. It is the canonical "
                "rubric that report_summary.md and report_analysis.md are composed from."
            )

    def test_the_analysis_prompt_asks_for_nothing_but_the_breakdown(self):
        text = (PROMPTS / "report_analysis.md").read_text()
        # The whole latency win is that this response does not carry the summary sections.
        # A prompt that asked for them would put them back, silently.
        for leaked in ("executive_summary", "improvement_roadmap", "dimension_scores"):
            assert leaked not in text, (
                f"report_analysis.md mentions {leaked!r}. The analysis batches exist to keep "
                "the response small — asking for a summary field here restores exactly the "
                "output size that made long interviews time out."
            )

    def test_the_summary_prompt_asks_for_no_per_question_entries(self):
        text = (PROMPTS / "report_summary.md").read_text()
        # It may TELL the model not to write question_analysis — that is the instruction. What
        # it must not do is show it in the output format, which is what a model copies.
        output_format = text.split("## Output Format", 1)[1]
        assert '"question_analysis"' not in output_format, (
            "report_summary.md's output example includes question_analysis. The model copies "
            "the example, so this puts the per-question entries back into the summary "
            "response — the exact output growth the split removes."
        )

    @pytest.mark.parametrize("template", ["report_analysis", "report_summary"])
    def test_neither_prompt_has_a_template_variable(self, template: str):
        # Both are opted into provider caching, which keys on the exact bytes of the system
        # block. A placeholder makes every request a cache WRITE at 1.25x instead of a read at
        # 0.1x — the report gets more expensive than before caching was switched on, and the
        # only symptom is a line on a bill. test_prompt_caching.py asserts this too; repeated
        # here because these two files are GENERATED and a generator is easy to get wrong.
        assert "$" not in (PROMPTS / f"{template}.md").read_text()


class TestBatchesCoverTheInterviewExactly:
    @pytest.mark.parametrize("count", [1, 2, 5, 6, 7, 12, 13, 16, 19, 20, 47])
    def test_every_question_is_in_exactly_one_batch(self, count: int):
        batches = plan_batches(count)
        covered = [i for b in batches for i in range(b.start, b.end)]
        assert covered == list(range(count)), (
            "batches must partition the interview: a gap means questions nobody grades, an "
            "overlap means a question graded twice and billed twice."
        )

    @pytest.mark.parametrize("count", [0, -1, -50])
    def test_nothing_to_grade_produces_no_calls(self, count: int):
        assert plan_batches(count) == []

    def test_a_trailing_batch_of_one_is_folded_back(self):
        # 13 at 6 would be 6 + 6 + 1. That last batch is a whole model call and a whole retry
        # budget for one question, while the batch it split from had room.
        assert [b.size for b in plan_batches(13, size=6)] == [6, 7]

    @pytest.mark.parametrize("count", list(range(1, 40)))
    def test_no_batch_is_ever_a_single_question_unless_that_is_the_whole_interview(
        self, count: int
    ):
        batches = plan_batches(count, size=BATCH_SIZE)
        if count == 1:
            assert [b.size for b in batches] == [1]
            return
        assert all(b.size > 1 for b in batches), [b.size for b in batches]

    @pytest.mark.parametrize("count", [1, 6, 7, 13, 20])
    def test_a_batch_budget_is_smaller_than_the_whole_report_used_to_need(self, count: int):
        # The point of the split, as a number. The old single call needed
        # 1500 + count*340 for a 13-answer report — 5920 tokens in one response, which is
        # what ran past the wall clock. No individual call may approach that again.
        assert batch_token_budget(min(count, BATCH_SIZE + 1)) <= 2800
        assert SUMMARY_TOKENS <= 2000


class TestTheReportComesBackInInterviewOrder:
    def test_analyses_are_reordered_onto_the_transcript(self):
        ids = ["q1", "q2", "q3", "q4"]
        # Batch 2 landed before batch 1, which is normal: they run concurrently.
        arrived = [_item("q3", 5), _item("q4", 6), _item("q1", 7), _item("q2", 8)]
        assert [a.question_id for a in order_by_transcript(arrived, ids)] == ids

    def test_a_duplicated_question_is_kept_once(self):
        ids = ["q1", "q2"]
        arrived = [_item("q1", 5), _item("q1", 9), _item("q2", 6)]
        out = order_by_transcript(arrived, ids)
        assert [a.question_id for a in out] == ["q1", "q2"]
        # First occurrence wins, not the most flattering one.
        assert out[0].score == 5

    def test_an_unrecognised_id_is_kept_rather_than_dropped(self):
        # A model that mangled one id has still written useful feedback for the candidate.
        out = order_by_transcript([_item("mangled", 4), _item("q1", 7)], ["q1"])
        assert [a.question_id for a in out] == ["q1", "mangled"]


class TestASummaryThatFailedIsDerivedRatherThanAbandoned:
    """
    The last route to 0/100. Every answer graded, only the covering paragraph missing.
    """

    def test_nothing_graded_means_nothing_to_derive(self):
        # With no per-question evidence a summary would be invention, which is the one thing
        # the unscored placeholder exists to avoid.
        assert derive_summary([], candidate_name="A", topics=[], answered=5) is None

    def test_a_graded_interview_produces_a_real_score(self):
        out = derive_summary(
            [_item(f"q{i}", 7.0) for i in range(6)],
            candidate_name="Sparsh",
            topics=["Java Core"],
            answered=6,
        )
        assert out is not None
        assert out.overall_score > 0, "this is the 0/100 the split exists to remove"
        # All four bars, or the report renders a blank competencies panel.
        assert set(out.dimension_scores) == {
            "technical_accuracy",
            "answer_completeness",
            "communication_clarity",
            "confidence",
        }

    def test_technical_accuracy_is_the_per_question_mean(self):
        # Not a plausible-looking constant: the number must be the model's own scores.
        out = derive_summary(
            [_item("q1", 4.0), _item("q2", 6.0), _item("q3", 8.0)],
            candidate_name="A",
            topics=[],
            answered=3,
        )
        assert out is not None
        assert out.dimension_scores["technical_accuracy"] == pytest.approx(60.0)

    def test_a_stronger_interview_scores_higher_than_a_weaker_one(self):
        strong = derive_summary(
            [_item(f"q{i}", 9.0) for i in range(5)], candidate_name="A", topics=[], answered=5
        )
        weak = derive_summary(
            [_item(f"q{i}", 2.0) for i in range(5)], candidate_name="A", topics=[], answered=5
        )
        assert strong and weak
        assert strong.overall_score > weak.overall_score + 30

    def test_unanswered_questions_drag_the_score_down(self):
        # A candidate who answered four of thirteen did not do as well as one who answered
        # four of four, and excluding the blanks would say otherwise.
        partial = derive_summary(
            [_item("q1", 8.0), _item("q2", 8.0)]
            + [_item(f"z{i}", 0.0, quality="no_answer") for i in range(6)],
            candidate_name="A",
            topics=[],
            answered=8,
        )
        full = derive_summary(
            [_item("q1", 8.0), _item("q2", 8.0)], candidate_name="A", topics=[], answered=2
        )
        assert partial and full
        assert partial.overall_score < full.overall_score

    def test_the_four_bars_describe_the_same_interview(self):
        """
        THE COHERENCE INVARIANT, and it was broken in a way reading the code did not show.

        Measured end-to-end on a real six-answer interview scoring [7, 5, 7, 8, 5, 1], the
        derived report returned answer_completeness 16.7 beside technical_accuracy 55.0. Those
        two numbers describe the same interview. On the candidate's report they are two bars
        side by side, so a 38-point gap reads as one of them being broken — and at a 0.25
        weight it pulled the overall score down from ~55 to 44.5.

        The cause was that `missing_concepts` is not a calibrated scale: it is however many
        concepts the grader chose to list, and a thorough grader lists four on an answer worth
        7/10. So the old divisor measured how talkative the grader was, not completeness.
        """
        # The real observed shape: mid-to-good answers, each with the four-ish missing
        # concepts a thorough grader records. Nothing pathological.
        analyses = [
            _item("q1", 7.0, missing=["a", "b", "c", "d"]),
            _item("q2", 5.0, missing=["a", "b", "c", "d"]),
            _item("q3", 7.0, missing=["a", "b", "c"]),
            _item("q4", 8.0, missing=[]),
            _item("q5", 5.0, missing=["a", "b", "c", "d", "e"]),
            _item("q6", 1.0, missing=["a", "b", "c", "d"], quality="incorrect"),
        ]
        out = derive_summary(analyses, candidate_name="A", topics=["Java"], answered=6)
        assert out is not None
        tech = out.dimension_scores["technical_accuracy"]
        comp = out.dimension_scores["answer_completeness"]
        # Completeness may sit BELOW accuracy — gaps are real — but not in a different world
        # from it. Half is the line: at the old divisor this was 16.7 against 55.0, i.e. 0.30.
        assert comp >= tech * 0.5, (
            f"answer_completeness {comp} against technical_accuracy {tech} — these describe "
            "the same interview and render as two bars side by side. A gap this size means "
            "the completeness formula is measuring the grader's verbosity, not the answers."
        )
        # And the headline must still resemble the per-question mean it is built from.
        mean_pct = sum(a.score for a in analyses) / len(analyses) * 10
        assert abs(out.overall_score - mean_pct) <= 12, (
            f"overall {out.overall_score} against a per-question mean of {mean_pct} — a "
            "candidate can add up the scores in their own breakdown, so the headline cannot "
            "drift far from them."
        )

    def test_missing_concepts_lower_completeness(self):
        thorough = derive_summary(
            [_item("q1", 7.0)], candidate_name="A", topics=[], answered=1
        )
        gappy = derive_summary(
            [_item("q1", 7.0, missing=["a", "b", "c", "d"])],
            candidate_name="A",
            topics=[],
            answered=1,
        )
        assert thorough and gappy
        assert (
            gappy.dimension_scores["answer_completeness"]
            < thorough.dimension_scores["answer_completeness"]
        )

    def test_delivery_metrics_move_clarity_and_confidence(self):
        clean = derive_summary(
            [_item("q1", 7.0)], candidate_name="A", topics=[], answered=1, delivery={}
        )
        hesitant = derive_summary(
            [_item("q1", 7.0)],
            candidate_name="A",
            topics=[],
            answered=1,
            delivery={"filler_count": 20, "pause_count": 20},
        )
        assert clean and hesitant
        assert (
            hesitant.dimension_scores["communication_clarity"]
            < clean.dimension_scores["communication_clarity"]
        )
        assert hesitant.dimension_scores["confidence"] < clean.dimension_scores["confidence"]

    @pytest.mark.parametrize("score", [0.0, 1.0, 5.0, 9.0, 10.0])
    def test_every_derived_number_stays_in_range(self, score: float):
        out = derive_summary(
            [_item("q1", score)],
            candidate_name="A",
            topics=[],
            answered=1,
            delivery={"filler_count": 999, "pause_count": 999},
        )
        assert out is not None
        assert 0.0 <= out.overall_score <= 100.0
        assert all(0.0 <= v <= 100.0 for v in out.dimension_scores.values())
        assert 0 <= out.performance_percentile <= 100

    def test_the_label_and_the_readiness_agree_with_the_number(self):
        # A derived report that says "Interview Ready" over a 30/100 is worse than no report.
        out = derive_summary(
            [_item(f"q{i}", 2.0) for i in range(5)], candidate_name="A", topics=[], answered=5
        )
        assert out is not None
        assert out.overall_score_label == score_label(out.overall_score)
        assert out.readiness_level == readiness_for(out.overall_score)

    def test_it_says_the_answers_were_saved(self):
        # The candidate's actual worry after seeing a partial report, and it is true here:
        # every answer was graded, only the covering paragraph was not written.
        out = derive_summary(
            [_item("q1", 6.0)], candidate_name="Sparsh", topics=["Java"], answered=1
        )
        assert out is not None
        assert "Sparsh" in out.executive_summary
        assert "graded" in out.executive_summary


class TestBandsAreMonotonic:
    @pytest.mark.parametrize(
        "lower,higher", [(10, 45), (45, 60), (60, 75), (75, 90)]
    )
    def test_a_higher_score_never_gets_a_worse_label(self, lower: int, higher: int):
        order = [
            "Significant Gaps",
            "Needs Improvement",
            "Satisfactory",
            "Good",
            "Excellent",
        ]
        assert order.index(score_label(higher)) > order.index(score_label(lower))

    @pytest.mark.parametrize("lower,higher", [(10, 45), (45, 70), (70, 85)])
    def test_a_higher_score_never_gets_worse_readiness(self, lower: int, higher: int):
        order = [
            "significant_gaps",
            "needs_more_practice",
            "close_to_ready",
            "interview_ready",
        ]
        assert order.index(readiness_for(higher)) > order.index(readiness_for(lower))


class TestMergeProducesTheShapeTheAppAlreadyStores:
    def test_both_halves_end_up_in_one_report(self):
        summary = ReportSummaryResponse(
            executive_summary="s",
            readiness_level="close_to_ready",
            readiness_reasoning="r",
            overall_score=71.0,
            overall_score_label="Good",
            dimension_scores={
                "technical_accuracy": 70.0,
                "answer_completeness": 70.0,
                "communication_clarity": 70.0,
                "confidence": 70.0,
            },
            strengths=["a"],
            weaknesses=["b"],
        )
        merged = merge(summary, [_item("q2", 6), _item("q1", 8)], ["q1", "q2"])
        assert merged.overall_score == 71.0
        assert merged.strengths == ["a"]
        # Ordering is applied by merge, not left to the caller.
        assert [a.question_id for a in merged.question_analysis] == ["q1", "q2"]

    def test_a_failed_batch_does_not_lose_the_rest_of_the_report(self):
        summary = ReportSummaryResponse(
            executive_summary="s",
            readiness_level="close_to_ready",
            readiness_reasoning="r",
            overall_score=71.0,
            overall_score_label="Good",
            dimension_scores={
                "technical_accuracy": 70.0,
                "answer_completeness": 70.0,
                "communication_clarity": 70.0,
                "confidence": 70.0,
            },
        )
        # Batch 2 of 2 failed: six of twelve analyses arrived.
        merged = merge(
            summary,
            [_item(f"q{i}", 7) for i in range(6)],
            [f"q{i}" for i in range(12)],
        )
        assert merged.overall_score == 71.0
        assert len(merged.question_analysis) == 6

"""
Assembling one report out of several concurrent model calls — services/report/composer.py

WHY A REPORT IS NOT ONE CALL ANY MORE.

It was, and this is what that cost. A report's largest section is ``question_analysis``,
which carries one entry per question, so the RESPONSE grows with the interview: measured at
90-140 output tokens an entry, on top of ~1500 for the summary. Latency on these providers is
output-token-bound almost linearly — 5 quiz questions took 8.9s, 7 took 11.0s, a 13-answer
report took 34s locally and ran past the 85s wall-clock budget in production.

So a long interview — the interviews that matter most, where the candidate answered
everything — was the one guaranteed to fail. The candidate got "Scoring took too long" and a
0/100 for an interview that was entirely gradeable, and every retry hit the same wall,
because a retry of one big call is still one big call.

WHAT CHANGED. The report is generated as a SUMMARY call plus N per-question BATCHES, all in
flight at once. Two properties follow, and both are the point:

  LATENCY IS THE SLOWEST PART, NOT THE SUM. A 13-answer report is one ~1500-token summary and
  three ~2000-token batches running together — around 12-15s, not 34-90s. Adding questions
  adds batches, not seconds, so the budget stops being a length limit on interviews.

  A FAILURE COSTS ONE PART. A batch that times out loses its own questions. The report still
  scores, because `_report_is_complete` accepts two-thirds coverage. Before, any single
  failure lost everything.

And if the summary itself fails while the batches succeed, the whole-interview view is
DERIVED from the per-question scores rather than abandoned — see `derive_summary`. That is
the path that turns the last remaining 0/100 into a real score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.services.ai.schemas import (
    ImprovementRoadmapItem,
    QuestionAnalysisItem,
    ReportGeneratorResponse,
    ReportSummaryResponse,
)

#: How many questions one analysis batch covers.
#:
#: Chosen from measured output cost, not preference. An entry is 90-140 output tokens and the
#: budget allows 340, so six questions is ~2000 tokens — the size that measured ~11s, which is
#: comfortably inside the budget even when the provider is having a slow minute. Larger batches
#: reintroduce exactly the problem this split exists to remove; smaller ones multiply the input
#: cost (each batch re-sends the rubric, cached, plus its own slice) for latency that is already
#: dominated by the summary call.
BATCH_SIZE = 6

#: A batch's own output-token ceiling. Same per-question figure the single call used, plus a
#: small fixed allowance for the JSON envelope.
_TOKENS_PER_QUESTION = 340
_TOKENS_BATCH_FIXED = 220


def batch_token_budget(questions: int) -> int:
    """Output-token ceiling for one analysis batch of ``questions`` questions."""
    return _TOKENS_BATCH_FIXED + max(1, questions) * _TOKENS_PER_QUESTION


#: Output-token ceiling for the summary call. The summary sections were measured at ~1500
#: tokens in the combined response and they do not grow with the interview — a 20-answer
#: report has the same three-to-four-sentence summary as a 6-answer one. The roadmap is
#: capped at three items by the prompt.
SUMMARY_TOKENS = 1800


@dataclass(frozen=True)
class Batch:
    """One slice of the interview, with the index range it covers."""

    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start


def plan_batches(question_count: int, size: int = BATCH_SIZE) -> list[Batch]:
    """
    Split ``question_count`` questions into batches of at most ``size``.

    A TRAILING BATCH OF ONE IS FOLDED BACK. 13 questions at 6 would otherwise be 6 + 6 + 1,
    and that last batch is a whole model call, a whole cache write and a whole retry budget
    spent on one question — while the batch it was split from had room. 6 + 7 is one fewer
    call for ~340 more output tokens on a batch that measured 11s at 2000.

    Never returns an empty list for a positive count, because a report with no analysis
    batches would silently be a summary-only report.
    """
    if question_count <= 0:
        return []
    size = max(1, size)
    bounds = list(range(0, question_count, size))
    batches = [Batch(start, min(start + size, question_count)) for start in bounds]
    if len(batches) > 1 and batches[-1].size == 1:
        last = batches.pop()
        merged = batches.pop()
        batches.append(Batch(merged.start, last.end))
    return batches


def score_label(score_0_100: float) -> str:
    """
    The headline label for a 0-100 score.

    Bands match the prompt's own vocabulary so a derived report reads like a generated one.
    """
    if score_0_100 >= 85:
        return "Excellent"
    if score_0_100 >= 70:
        return "Good"
    if score_0_100 >= 55:
        return "Satisfactory"
    if score_0_100 >= 40:
        return "Needs Improvement"
    return "Significant Gaps"


def readiness_for(score_0_100: float) -> str:
    """`readiness_level` for a 0-100 score, using the same bands as `score_label`."""
    if score_0_100 >= 80:
        return "interview_ready"
    if score_0_100 >= 65:
        return "close_to_ready"
    if score_0_100 >= 40:
        return "needs_more_practice"
    return "significant_gaps"


def _dedupe_in_order(analyses: list[QuestionAnalysisItem]) -> list[QuestionAnalysisItem]:
    """
    One entry per question, first occurrence winning.

    Batches cover disjoint slices, so a duplicate means a model copied a `question_id` from
    the wrong question or repeated an entry inside its own batch. Left in, the candidate reads
    the same question twice and `_report_is_complete`'s coverage check counts it twice —
    turning a batch that actually failed into one that looks complete.
    """
    seen: set[str] = set()
    unique: list[QuestionAnalysisItem] = []
    for item in analyses:
        key = (item.question_id or item.question or "").strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(item)
    return unique


def order_by_transcript(
    analyses: list[QuestionAnalysisItem], question_ids: list[str]
) -> list[QuestionAnalysisItem]:
    """
    Put the merged analyses back into the order the questions were asked.

    THE BATCHES FINISH OUT OF ORDER. They run concurrently, so batch 3 can land before batch
    1, and the candidate would read their interview shuffled — question 13 first. Ordering on
    the transcript rather than on arrival is what makes the split invisible in the output.

    Anything whose id is not in the transcript keeps its relative position at the end rather
    than being dropped: a model that mangled one id has still written useful feedback, and
    losing it would be a worse outcome than an entry in an odd place.
    """
    rank = {qid: i for i, qid in enumerate(question_ids)}
    unknown = len(rank)
    return sorted(
        _dedupe_in_order(analyses),
        key=lambda item: rank.get((item.question_id or "").strip(), unknown),
    )


def merge(
    summary: ReportSummaryResponse,
    analyses: list[QuestionAnalysisItem],
    question_ids: list[str],
) -> ReportGeneratorResponse:
    """
    Fold the two halves back into the single shape the rest of the app already stores.

    Nothing downstream knows the report was generated in parts, and that is deliberate: the
    storage, the response model, the completeness check and the UI are unchanged, so the split
    cannot break any of them.
    """
    return ReportGeneratorResponse(
        executive_summary=summary.executive_summary,
        readiness_level=summary.readiness_level,
        readiness_reasoning=summary.readiness_reasoning,
        overall_score=summary.overall_score,
        overall_score_label=summary.overall_score_label,
        topic_scores=summary.topic_scores,
        dimension_scores=summary.dimension_scores,
        performance_percentile=summary.performance_percentile,
        strengths=summary.strengths,
        weaknesses=summary.weaknesses,
        question_analysis=order_by_transcript(analyses, question_ids),
        improvement_roadmap=summary.improvement_roadmap,
    )


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, value)), 1)


def derive_summary(
    analyses: list[QuestionAnalysisItem],
    *,
    candidate_name: str,
    topics: list[str],
    answered: int,
    delivery: dict | None = None,
) -> ReportSummaryResponse | None:
    """
    Build the whole-interview view out of the per-question scores, when the summary call failed.

    THIS IS THE LAST 0/100. With the report split, the summary and the batches fail
    independently — so the case that remains is "we graded every answer and could not write the
    covering paragraph". Returning the unscored placeholder there would throw away a complete
    grading of the interview because one of four calls did not land, and it would tell a
    candidate whose answers WERE all scored that scoring failed.

    EVERY NUMBER HERE TRACES TO A MODEL-ASSIGNED PER-QUESTION SCORE OR A COUNTED DELIVERY
    METRIC. Nothing is invented and nothing is averaged out of thin air:

      technical_accuracy   the mean per-question score, x10. This is precisely what the prompt
                           asks the model to do with those scores.
      answer_completeness  how much of the expected content was present, from the number of
                           `missing_concepts` the grader recorded per answer.
      communication_clarity  counted fillers per answer, from the delivery metrics the client
                           accumulated during the interview.
      confidence           counted hesitation — pauses per answer — from the same metrics.

    The prose is written here rather than generated, and it says only what the numbers support.
    It is also explicitly marked as partial by the caller, so it is never presented as a full
    AI report.

    Returns None when there is nothing to derive FROM — no analyses at all — because a summary
    with no per-question evidence behind it would be invention, which is the one thing the
    unscored placeholder exists to avoid.
    """
    scored = [a for a in analyses if a.answer_quality != "no_answer"]
    if not analyses:
        return None

    # Unanswered questions count as zero rather than being excluded: an interview where the
    # candidate answered four of thirteen did not score as well as one where they answered
    # four of four, and dropping them would say otherwise.
    mean_score = sum(a.score for a in analyses) / len(analyses)
    technical = _clamp(mean_score * 10)

    # Four missing concepts on one answer is treated as nothing of the expected content
    # present. The grader records the concepts it actually looked for, so this is a count, not
    # a judgement.
    completeness = _clamp(
        100.0
        * sum(1.0 - min(1.0, len(a.missing_concepts) / 4.0) for a in analyses)
        / len(analyses)
    )

    d = delivery or {}
    per_answer = max(1, answered or len(analyses))
    fillers = float(d.get("filler_count") or 0)
    pauses = float(d.get("pause_count") or 0)
    # Anchored on the technical score, then moved by what was counted. Delivery is a modifier
    # on how the answers came across, not an independent grade — and with no delivery data at
    # all (an older session, a text-only interview) both fall back to the technical figure,
    # which is honest about knowing nothing more.
    clarity = _clamp(technical - min(25.0, 4.0 * fillers / per_answer))
    confidence = _clamp(technical - min(25.0, 3.0 * pauses / per_answer))

    overall = _clamp(technical * 0.55 + completeness * 0.25 + clarity * 0.10 + confidence * 0.10)

    strong = [a for a in analyses if a.score >= 7]
    weak = sorted(scored, key=lambda a: a.score)[:3]

    topic_list = ", ".join(topics[:6]) or "several topics"
    summary_text = (
        f"{candidate_name} answered {len(analyses)} of {answered or len(analyses)} questions "
        f"across {topic_list}. Every answer was graded individually and the breakdown below is "
        f"complete — the covering summary could not be written this time, so the figures here "
        f"are calculated directly from those per-question scores. "
        + (
            f"{len(strong)} answer{'s' if len(strong) != 1 else ''} scored 7 or above. "
            if strong
            else "No answer reached 7 out of 10, so the fundamentals are the place to start. "
        )
        + "Open the question-by-question analysis to see exactly what was missing in each one — "
        "that is where the improvement is."
    )

    roadmap = [
        ImprovementRoadmapItem(
            priority=i + 1,
            topic=(a.missing_concepts[0] if a.missing_concepts else a.question)[:120],
            current_score=round(a.score, 1),
            # A realistic next step rather than a perfect score: telling somebody on 3/10 to
            # aim for 10 is not a plan.
            target_score=round(min(9.0, max(6.0, a.score + 3.0)), 1),
            study_hours_estimate=int(min(20, max(4, math.ceil((7.0 - a.score) * 3)))),
            resources=[],
        )
        for i, a in enumerate(weak)
    ]

    return ReportSummaryResponse(
        executive_summary=summary_text,
        readiness_level=readiness_for(overall),  # type: ignore[arg-type]
        readiness_reasoning=(
            f"Calculated from {len(analyses)} graded answers averaging "
            f"{round(mean_score, 1)}/10."
        ),
        overall_score=overall,
        overall_score_label=score_label(overall),
        topic_scores={},
        dimension_scores={
            "technical_accuracy": technical,
            "answer_completeness": completeness,
            "communication_clarity": clarity,
            "confidence": confidence,
        },
        performance_percentile=int(_clamp(overall * 0.8 + 5)),
        strengths=[
            f"{a.question[:90]} — scored {round(a.score, 1)}/10"
            for a in sorted(strong, key=lambda x: -x.score)[:3]
        ],
        weaknesses=[
            (
                f"{a.question[:90]} — "
                + (
                    f"missing {', '.join(a.missing_concepts[:3])}"
                    if a.missing_concepts
                    else f"scored {round(a.score, 1)}/10"
                )
            )
            for a in weak
        ],
        improvement_roadmap=roadmap,
    )

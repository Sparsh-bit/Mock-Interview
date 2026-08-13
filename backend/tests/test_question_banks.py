"""
The question banks, and the promise about how many questions an interview asks.

TWO REPORTED BUGS ARE PINNED HERE.

1. "It says 20 questions and asks me 8." The planner is told to produce
   INTERVIEW_QUESTION_COUNT questions, but the validator accepted any plan with
   four or more and nothing measured the gap. A candidate who had prepared for
   Cognizant got a third of the interview the dashboard advertised, four times
   running, and nothing in the code or the logs said so.

2. "It never asks the topics I actually prepared." The seed bank held five
   questions — and a second, divergent copy of five more in a YAML only a manual
   script read. Five cannot fill twelve, so a short plan had nothing to be topped
   up from, and the topics a Cognizant candidate revises were mostly absent.
"""

from __future__ import annotations

import collections

import pytest

from app.core.config import settings
from app.data.java_fundamentals import (
    ALL_TOPICS,
    FRAMEWORK_TOPICS,
    JAVA_QUESTION_BANK,
    for_track,
    topics_for_track,
)
from app.data.quiz_bank import QUIZ_BANK
from app.services.interview import orchestrator as orch

#: Every topic the user named as "the basics, asked in every company interview".
#: Each entry is (label, substrings that would identify it in a question or topic
#: name). Matched loosely on purpose — the point is that the subject is covered,
#: not that a particular phrase appears.
REQUIRED_TOPICS: list[tuple[str, tuple[str, ...]]] = [
    ("JDK / JVM / JRE", ("jdk", "jvm", "jre")),
    ("Java code execution", ("javac", "bytecode", ".class")),
    ("Stack and heap", ("stack", "heap")),
    ("Scanner vs BufferedReader", ("scanner", "bufferedreader")),
    ("Wrapper classes", ("wrapper", "autoboxing", "integer")),
    ("Static methods", ("static",)),
    ("String creation", ("new string", "string literal", "string s =")),
    ("String pool", ("string pool", "intern")),
    ("== vs .equals", ("==", "equals()")),
    ("StringBuilder", ("stringbuilder",)),
    ("StringBuffer", ("stringbuffer",)),
    ("Lambda expressions", ("lambda", "functional interface")),
    ("Multithreading", ("thread", "multithread")),
    ("JDBC", ("jdbc", "preparedstatement")),
    ("Collections framework", ("collection", "arraylist", "hashmap")),
    ("Getters and setters", ("getter", "setter", "encapsulation")),
    ("Diamond problem", ("diamond",)),
    ("Exception handling", ("exception", "checked")),
    ("throw vs throws", ("throw", "throws")),
    ("final / finally / finalize", ("finally", "finalize")),
    ("Hibernate vs JDBC", ("hibernate",)),
    ("Spring Boot", ("spring boot",)),
    ("Dependency injection", ("dependency injection", "autowired", "constructor injection")),
    ("Spring REST", ("restcontroller", "getmapping", "requestbody")),
    ("REST API", ("rest api", "http method", "idempotent", "status code")),
    ("JPA", ("jpa", "entitymanager")),
    ("Jackson", ("jackson", "json")),
    # Added on request after the first pass.
    ("SOLID principles", ("solid", "single responsibility", "liskov", "open-closed")),
    ("Design patterns", ("singleton", "factory", "builder", "strategy pattern")),
]


def _interview_haystack() -> str:
    return " ".join(
        f"{q['topic']} {q['content']} {' '.join(q['keywords'])} {q['ideal']}"
        for q in JAVA_QUESTION_BANK
    ).lower()


def _quiz_haystack() -> str:
    return " ".join(
        f"{topic} {q['question']} {' '.join(q['options'])} {q['explanation']}"
        for topic, qs in QUIZ_BANK.items()
        for q in qs
    ).lower()


class TestTheInterviewPromiseIsKept:
    def test_the_ai_plan_floor_is_close_to_the_advertised_count(self):
        """
        The floor used to be a bare 4 while the dashboard advertised 12 or 20 —
        so a plan a third of the promised length was accepted silently. It is now
        two thirds of the target, and anything below that is replaced rather than
        served.
        """
        assert orch._MIN_AI_PLAN_QUESTIONS >= (settings.INTERVIEW_QUESTION_COUNT * 2) // 3
        assert orch._MIN_AI_PLAN_QUESTIONS > 4 or settings.INTERVIEW_QUESTION_COUNT <= 6

    def test_a_short_plan_is_topped_up_rather_than_served(self):
        src = __import__("inspect").getsource(orch.InterviewOrchestrator.create_plan)
        assert "_top_up_plan" in src, (
            "create_plan does not top a short plan up, so the count the dashboard "
            "advertises is not the count the candidate gets"
        )

    def test_falling_short_is_logged_not_shrugged_at(self):
        """
        If even the bank cannot reach the target, that has to be visible — the
        number shown to the candidate will not match what was advertised.
        """
        src = __import__("inspect").getsource(orch.InterviewOrchestrator.create_plan)
        assert "interview_plan_below_target" in src

    def test_the_adaptive_path_uses_the_setting_not_a_hardcoded_number(self):
        """
        This was `if len(answered_ids) >= 10`, so raising the setting to 20 moved
        the number on the dashboard and not the interview.
        """
        src = __import__("inspect").getsource(orch.InterviewOrchestrator.get_next_question)
        assert ">= _PLANNED_QUESTION_COUNT" in src
        assert ">= 10" not in src

    def test_the_bank_can_actually_fill_a_full_interview(self):
        """
        The whole point of the top-up. Five questions could not fill twelve, which
        is why the shortfall had no remedy.
        """
        assert len(JAVA_QUESTION_BANK) >= settings.INTERVIEW_QUESTION_COUNT, (
            f"bank has {len(JAVA_QUESTION_BANK)} questions but an interview asks "
            f"{settings.INTERVIEW_QUESTION_COUNT} — a short plan cannot be topped up"
        )

    def test_the_bank_can_fill_the_maximum_configurable_interview(self):
        """The setting allows up to 25; the bank should cover that too."""
        assert len(JAVA_QUESTION_BANK) >= 25


class TestEveryRequiredTopicIsAsked:
    """The list the user gave, checked against both surfaces."""

    @pytest.mark.parametrize("label,needles", REQUIRED_TOPICS, ids=[t[0] for t in REQUIRED_TOPICS])
    def test_interview_bank_covers(self, label: str, needles: tuple[str, ...]):
        hay = _interview_haystack()
        assert any(n in hay for n in needles), (
            f"the interview bank never asks about {label} — a candidate who "
            f"prepared it will not be tested on it"
        )

    @pytest.mark.parametrize("label,needles", REQUIRED_TOPICS, ids=[t[0] for t in REQUIRED_TOPICS])
    def test_quiz_bank_covers(self, label: str, needles: tuple[str, ...]):
        hay = _quiz_haystack()
        assert any(n in hay for n in needles), f"the quiz bank has nothing on {label}"


class TestDifficultySplit:
    """
    Interviews are spoken: easy to medium theory. The quiz is read at your own
    pace with four options visible, so it carries the hard cases.
    """

    def test_interview_questions_are_never_hard(self):
        hard = [q["content"] for q in JAVA_QUESTION_BANK if q["difficulty"] not in ("easy", "medium")]
        assert not hard, (
            "these interview questions are above medium; a candidate has about a "
            f"minute and no editor: {hard}"
        )

    def test_interview_bank_has_both_levels(self):
        levels = {q["difficulty"] for q in JAVA_QUESTION_BANK}
        assert levels == {"easy", "medium"}

    def test_every_quiz_question_declares_a_difficulty(self):
        """
        The endpoint has always read `q.get("difficulty", "medium")`, but nothing
        in the bank set it — so every question in the product reported medium and
        the easy/hard distinction did not exist.
        """
        missing = [
            f"{topic}: {q['question'][:60]}"
            for topic, qs in QUIZ_BANK.items()
            for q in qs
            if "difficulty" not in q
        ]
        assert not missing, f"quiz questions with no difficulty: {missing}"

    def test_quiz_difficulties_are_valid_values(self):
        bad = {
            q.get("difficulty")
            for qs in QUIZ_BANK.values()
            for q in qs
            if q.get("difficulty") not in ("easy", "medium", "hard")
        }
        assert not bad, f"invalid difficulty values: {bad}"

    def test_the_quiz_has_hard_questions(self):
        counts = collections.Counter(q["difficulty"] for qs in QUIZ_BANK.values() for q in qs)
        assert counts["hard"] >= 10, f"only {counts['hard']} hard questions in the whole bank"
        assert counts["easy"] >= 10
        assert counts["medium"] >= 10


class TestFrameworkScoping:
    """
    The user's own constraint: do not ask a company about topics it does not test.
    A Spring dependency-injection question in a TCS aptitude round burns one of
    twelve slots on something the candidate will never be asked.
    """

    def test_a_java_fse_role_gets_the_frameworks(self):
        topics = topics_for_track("Java Full Stack Engineer", "GenC Next")
        assert set(topics) >= FRAMEWORK_TOPICS

    @pytest.mark.parametrize(
        "track,program",
        [("TCS NQT", "Ninja"), ("Aptitude Round", "Fresher"), ("", "")],
    )
    def test_a_non_java_role_gets_core_only(self, track: str, program: str):
        topics = set(topics_for_track(track, program))
        assert not (FRAMEWORK_TOPICS & topics), (
            f"{track or 'unnamed'} would be asked framework questions it does not test: "
            f"{sorted(FRAMEWORK_TOPICS & topics)}"
        )

    def test_core_topics_are_asked_of_everyone(self):
        core = {t for t in ALL_TOPICS if t not in FRAMEWORK_TOPICS}
        assert set(topics_for_track("TCS NQT", "Ninja")) >= core
        assert set(topics_for_track("Java FSE", "GenC Next")) >= core

    def test_core_only_is_still_enough_for_a_full_interview(self):
        """
        Scoping must not reintroduce the shortfall it was meant to avoid — a TCS
        interview still has to reach the advertised count.
        """
        assert len(for_track("TCS NQT", "Ninja")) >= settings.INTERVIEW_QUESTION_COUNT


class TestBankIntegrity:
    def test_no_duplicate_interview_questions(self):
        contents = [q["content"] for q in JAVA_QUESTION_BANK]
        dupes = [c for c, n in collections.Counter(contents).items() if n > 1]
        assert not dupes, f"duplicate interview questions: {dupes}"

    def test_no_duplicate_quiz_questions(self):
        qs = [q["question"] for topic_qs in QUIZ_BANK.values() for q in topic_qs]
        dupes = [c for c, n in collections.Counter(qs).items() if n > 1]
        assert not dupes, f"duplicate quiz questions: {dupes}"

    def test_every_interview_question_has_keywords_and_a_model_answer(self):
        """Keywords drive scoring and gap detection; without them an answer cannot be marked."""
        bad = [
            q["content"][:60]
            for q in JAVA_QUESTION_BANK
            if len(q["keywords"]) < 3 or len(q["ideal"]) < 80
        ]
        assert not bad, f"interview questions with thin scoring data: {bad}"

    def test_every_quiz_question_has_four_options_and_a_valid_answer(self):
        bad = [
            f"{topic}: {q['question'][:50]}"
            for topic, qs in QUIZ_BANK.items()
            for q in qs
            if len(q["options"]) != 4 or not 0 <= q["correct_index"] <= 3
        ]
        assert not bad, f"malformed quiz questions: {bad}"

    def test_every_quiz_question_explains_the_answer(self):
        """A quiz that marks you wrong without saying why teaches nothing."""
        bad = [
            f"{topic}: {q['question'][:50]}"
            for topic, qs in QUIZ_BANK.items()
            for q in qs
            if len(q.get("explanation", "")) < 40
        ]
        assert not bad, f"quiz questions with no real explanation: {bad}"

    def test_quiz_options_within_a_question_are_distinct(self):
        bad = [
            f"{topic}: {q['question'][:50]}"
            for topic, qs in QUIZ_BANK.items()
            for q in qs
            if len(set(q["options"])) != len(q["options"])
        ]
        assert not bad, f"quiz questions with duplicate options: {bad}"


class TestOneSeedSource:
    def test_the_orchestrator_seeds_from_the_shared_bank(self):
        """
        There were two divergent five-question seed sets — one hardcoded here, one
        in a YAML only a manual script read. Neither could fill an interview.
        """
        src = __import__("inspect").getsource(orch.InterviewOrchestrator._ensure_seed_questions)
        assert "JAVA_QUESTION_BANK" in src
        assert "HashMap, Hashtable, and ConcurrentHashMap" not in src, (
            "the old hardcoded seed list is still here"
        )

    def test_seeding_creates_a_topic_per_bank_topic(self):
        """
        Everything used to be seeded under one "Java Fundamentals" topic, which
        made the report's topic breakdown a single bar that told a candidate
        nothing about where they were weak.
        """
        src = __import__("inspect").getsource(orch.InterviewOrchestrator._ensure_seed_questions)
        assert "topic_rows" in src


class TestThePlanTokenBudget:
    """
    The root cause of all three complaints, pinned.

    `max_tokens` for the plan was a flat 2500. A planned question carries content,
    topic_name, difficulty, question_type, expected_keywords and ideal_answer —
    about 165 output tokens each — so a 20-question plan needs roughly 3,300 and
    the JSON truncated mid-array. The parse failed, both providers were exhausted,
    and EVERY plan silently fell back to the fixed bank. Which produced, at once:
    fewer questions than advertised, the same questions every time, and none of
    the topics a candidate had actually prepared.

    Verified against the live API: with the flat ceiling the log showed
    `ai_json_extraction_failed` with a truncated preview on every attempt; with the
    scaled budget the plan returns 20 freshly generated questions and no fallback.
    """

    def test_the_budget_scales_with_the_question_count(self):
        assert orch.plan_token_budget(20) > orch.plan_token_budget(10)
        assert orch.plan_token_budget(10) > orch.plan_token_budget(5)

    def test_the_budget_covers_the_configured_interview_length(self):
        """
        The measured need is about 165 output tokens per question. Anything at or
        below that is a truncation waiting to happen.
        """
        budget = orch.plan_token_budget(settings.INTERVIEW_QUESTION_COUNT)
        assert budget >= settings.INTERVIEW_QUESTION_COUNT * 200, (
            f"{budget} tokens for {settings.INTERVIEW_QUESTION_COUNT} questions is "
            "too tight — a truncated plan costs the full call and yields nothing"
        )

    def test_the_budget_covers_the_maximum_configurable_length(self):
        """The setting allows up to 25, so 25 must not truncate either."""
        assert orch.plan_token_budget(25) >= 25 * 200

    def test_the_old_flat_ceiling_would_have_failed(self):
        """
        Documents the actual defect so nobody 'simplifies' this back to a constant.
        """
        assert orch.plan_token_budget(20) > 2500

    def test_the_budget_is_capped(self):
        """A pathological count must not request an unbounded response."""
        assert orch.plan_token_budget(10_000) == orch._PLAN_TOKENS_MAX

    def test_a_zero_count_still_gets_the_fixed_part(self):
        assert orch.plan_token_budget(0) == orch._PLAN_TOKENS_FIXED

    def test_the_call_site_uses_the_helper_not_a_literal(self):
        src = __import__("inspect").getsource(orch.InterviewOrchestrator.create_plan)
        assert "plan_token_budget(" in src
        assert "max_tokens=2500" not in src


class TestRetakesGetDifferentQuestions:
    """
    "I want different questions every time." Three mechanisms, because the plan can
    come from three places and all of them used to be blind to history.
    """

    def test_previously_answered_questions_are_looked_up(self):
        src = __import__("inspect").getsource(orch.InterviewOrchestrator.create_plan)
        assert "_already_asked" in src

    def test_the_planner_is_told_what_to_avoid(self):
        src = __import__("inspect").getsource(orch.InterviewOrchestrator.create_plan)
        assert "already_asked=" in src

    def test_the_prompt_accepts_the_avoid_list(self):
        import pathlib

        prompt = (
            pathlib.Path(__import__("app").__file__).parent / "prompts/interview_plan.md"
        ).read_text()
        assert "$already_asked" in prompt
        assert "Do not repeat any of these" in prompt

    def test_the_bank_topup_REFUSES_seen_questions_rather_than_deprioritising_them(self):
        """
        A preference was not enough, and the arithmetic is why: the bank holds 37 questions
        and an interview is 12, so a candidate exhausts it on their fourth sitting. After
        that every top-up was a repeat — ranked last, but still served, because the code
        chose "a repeat beats a short interview".

        That trade is only correct while a short interview is the alternative. It is not:
        create_plan now GENERATES the remainder, so the real choice is between a repeat and
        a fresh question. Asserted on the filter rather than on the ranking, because the
        ranking is exactly what was there before and was not enough.
        """
        src = __import__("inspect").getsource(orch.InterviewOrchestrator._top_up_plan)
        assert "already_answered" in src
        assert "q.id not in already_answered" in src, (
            "seen questions must be filtered out of the eligible pool, not merely ranked "
            "below the unseen ones"
        )

    def test_the_gap_the_bank_cannot_cover_is_generated_not_repeated(self):
        # The other half. Without this, making the filter hard would trade repeated
        # questions for short interviews, which is a different bug rather than a fix.
        src = __import__("inspect").getsource(orch.InterviewOrchestrator.create_plan)
        assert "_generate_question" in src
        assert "_MAX_GENERATED_TOP_UPS" in src, "unbounded generation on the start path"

    def test_the_fallback_plan_prefers_unseen_questions(self):
        """
        Not a rare path: the AI plan times out often enough that the fallback is
        what many candidates get. Making only the top-up history-aware left a
        measured 15 of 20 questions repeated on a second attempt.
        """
        src = __import__("inspect").getsource(orch.InterviewOrchestrator._fallback_plan)
        assert "seen_ids" in src

    def test_a_retake_does_not_reuse_a_cached_plan(self):
        """
        The cache holds at most _MAX_PLAN_VARIANTS per signature, so by a fourth
        attempt a reused variant is very likely one the candidate has already sat.
        """
        src = __import__("inspect").getsource(orch.InterviewOrchestrator.create_plan)
        assert "is_retake" in src
        assert "not is_retake" in src

    def test_exhausting_the_bank_for_a_candidate_is_logged(self):
        """
        The bank running out of unseen questions for somebody is actionable — it means the
        curated set needs more content — so it must be visible rather than silently papered
        over by generation.
        """
        src = __import__("inspect").getsource(orch.InterviewOrchestrator._top_up_plan)
        assert "interview_plan_bank_exhausted_for_candidate" in src

    def test_the_bank_is_measured_against_the_interview_length(self):
        """
        The number that made this a bug rather than an edge case, asserted so it cannot
        drift quietly. If the bank ever grows past a few interviews' worth, the generated
        top-up stops firing on its own and this test is the reminder that the constant
        above it was chosen against these figures.
        """
        from app.core.config import settings
        from app.data.java_fundamentals import JAVA_QUESTION_BANK

        per_interview = settings.INTERVIEW_QUESTION_COUNT
        sittings_before_exhaustion = len(JAVA_QUESTION_BANK) / per_interview
        assert sittings_before_exhaustion < 5, (
            f"{len(JAVA_QUESTION_BANK)} bank questions at {per_interview} per interview is "
            f"{sittings_before_exhaustion:.1f} sittings — this is why the top-up must "
            "generate rather than repeat"
        )


class TestReportCompleteness:
    """
    Every report in production had dimension_scores={} and question_analysis=[] —
    the four competencies panel and the per-question breakdown, both blank. They
    were optional in the schema (default_factory) and appeared in the prompt only
    as an example, so when the model economised on a long response it dropped them
    and nothing objected.
    """

    def test_generation_rejects_a_report_with_no_dimension_scores(self):
        from app.api.v1.reports import _report_is_complete

        class R:
            dimension_scores: dict = {}
            question_analysis: list = []

        assert _report_is_complete(R(), answered=5) is False

    def test_generation_rejects_a_partial_dimension_set(self):
        from app.api.v1.reports import _report_is_complete

        class R:
            dimension_scores = {"technical_accuracy": 50.0}
            question_analysis = [object()] * 5

        assert _report_is_complete(R(), answered=5) is False

    def test_generation_rejects_a_summarised_question_analysis(self):
        """One entry for a sixteen-question interview is a summary, not analysis."""
        from app.api.v1.reports import _report_is_complete

        class R:
            dimension_scores = dict.fromkeys(
                ("technical_accuracy", "answer_completeness", "communication_clarity", "confidence"),
                50.0,
            )
            question_analysis = [object()]

        assert _report_is_complete(R(), answered=16) is False

    def test_a_complete_report_passes(self):
        from app.api.v1.reports import _report_is_complete

        class R:
            dimension_scores = dict.fromkeys(
                ("technical_accuracy", "answer_completeness", "communication_clarity", "confidence"),
                50.0,
            )
            question_analysis = [object()] * 16

        assert _report_is_complete(R(), answered=16) is True

    def test_near_complete_analysis_is_accepted(self):
        """
        15 of 16 analysed is far better for the candidate than the unscored
        fallback, so the bar is most-of-the-interview rather than all of it.
        """
        from app.api.v1.reports import _report_is_complete

        class R:
            dimension_scores = dict.fromkeys(
                ("technical_accuracy", "answer_completeness", "communication_clarity", "confidence"),
                50.0,
            )
            question_analysis = [object()] * 15

        assert _report_is_complete(R(), answered=16) is True

    def test_the_prompt_states_both_are_required(self):
        import pathlib as _p

        prompt = (
            _p.Path(__import__("app").__file__).parent / "prompts/report_generator.md"
        ).read_text()
        assert "Required fields" in prompt
        assert "ONE ENTRY PER QUESTION" in prompt

    def test_the_time_budget_covers_a_measured_full_report(self):
        """
        A complete 20-answer report was MEASURED at 47.9 seconds. The old flat 50s
        cleared that by two seconds, so any longer interview or slower moment fell
        into the unscored fallback — and every retry hit the same wall, so a long
        interview could never finish.
        """
        from app.api.v1.reports import (
            _REPORT_AI_BUDGET_COLD_SECONDS,
            _REPORT_AI_BUDGET_WARM_SECONDS,
        )

        assert _REPORT_AI_BUDGET_WARM_SECONDS >= 70, "no headroom over the measured 47.9s"
        # Cold must stay inside the gateway: ~37s cold start + budget < ~100s.
        assert 37 + _REPORT_AI_BUDGET_COLD_SECONDS <= 95

    def test_the_budget_is_chosen_from_process_uptime(self):
        from app.api.v1 import reports as r

        assert callable(r.report_ai_budget_seconds)
        assert r.report_ai_budget_seconds() in (
            r._REPORT_AI_BUDGET_COLD_SECONDS,
            r._REPORT_AI_BUDGET_WARM_SECONDS,
        )

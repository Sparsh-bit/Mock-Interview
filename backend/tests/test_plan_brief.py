"""
What the planner is actually told — tests/test_plan_brief.py

THE REPORT. A candidate sat a Cognizant Digital Nurture 5.0 Java FSE mock in preparation
for the real technical interview and said three things about it: it asked "mostly the
scenario based questions only", it was "not looking at what i have filled in the blocks for
additional topics", and it did not cover the round they are actually sitting — Java and OOP,
React, SQL, Spring Boot and REST, coding aloud, the project, HR.

All three were true, and none of them was a bug in one place:

  · SUBJECTS came from `_must_cover_block`, which for a Java role rendered the curated bank
    — sixteen Java topics, no React, no SQL area, no spoken-coding area. So a full-stack
    candidate was briefed on two thirds of their own syllabus.
  · SHAPE came from a bolded sentence in `interview_plan.md`: "MOST QUESTIONS MUST BE
    SCENARIO-BASED. At least two thirds of them." Unconditionally, for every role. It was
    right for a sales screen and wrong for a fundamentals viva, and one sentence cannot be
    both.
  · The FOCUS box got one trailing clause in the same file, against "Draw the majority of
    your questions from this list" and "Stay inside it".

`orchestrator._plan_brief` is the single answer to all three, and these are the tests that
say what it must produce. They assert on the RENDERED TEXT rather than on internals, because
the rendered text is the whole product: the model sees this and nothing else.

WHAT IS DELIBERATELY NOT ASSERTED. No test here pins a question sentence, because there are
none to pin — the syllabus stores areas, subtopic descriptors and cross-question themes, and
the model writes every sentence fresh. A test that asserted a phrase would be the
hardcoding the candidate asked us not to do, arriving through the back door.
"""

from __future__ import annotations

import pytest

from app.data import question_shape
from app.services.interview.orchestrator import _plan_brief

#: The interview the whole change exists for. Track name and program both given, as the
#: setup form now sends them — the program chip used to set only the track id, so the wire
#: carried program="" and `syllabus.resolve` could never match.
COGNIZANT = {
    "track_name": "Digital Nurture — Java FSE",
    "program": "Digital Nurture — Java FSE",
    "company": "Cognizant",
}

#: A non-technical role at a company that is not on the catalogue. This is the Morani
#: Plastics case: a sales candidate was once briefed for an Accenture CS interview, and the
#: domains.py path is the fix. Every test that touches the technical side has a twin here,
#: because the failure mode of "make the campus round a viva" is "make every round a viva".
SALES = {
    "track_name": "Sales Executive",
    "program": "Sales",
    "company": "Morani Plastics",
}

COUNTS = [4, 8, 12, 20, 25]


def brief(setup: dict, *, focus: str = "", is_technical: bool = True, count: int = 12):
    return _plan_brief(
        track_name=setup["track_name"],
        program=setup["program"],
        company=setup["company"],
        focus=focus,
        is_technical=is_technical,
        question_count=count,
    )


class TestTheRoundTheCandidateIsActuallySitting:
    def test_the_syllabus_drives_the_cognizant_brief(self):
        # Not the curated Java bank. If this is False the candidate is back on the
        # sixteen-Java-topics path and every assertion below is vacuous.
        assert brief(COGNIZANT).from_syllabus is True

    @pytest.mark.parametrize(
        "area",
        [
            "Core Java",
            "OOP & Class Design",
            "React & Frontend",
            "SQL & Data Modelling",
            "Spring Boot & REST",
        ],
    )
    def test_every_area_the_real_round_covers_reaches_the_brief(self, area: str):
        """
        THE ONE THAT WOULD HAVE CAUGHT REPORT (3). React and SQL were absent entirely —
        SQL appeared only as the string "DBMS & SQL — 15% of the assessment", a percentage
        with no sub-topics and nothing to generate a question from.

        Asserted against the syllabus itself rather than a literal list, so adding an area
        to the round cannot leave this test passing while the brief omits it.
        """
        assert area in brief(COGNIZANT).must_cover

    def test_a_spoken_coding_row_exists(self):
        # "Basic coding" is a third of the reported round and there was no register for it
        # at all — the editor round was the only place code appeared.
        assert "code aloud" in brief(COGNIZANT).must_cover.lower()

    def test_the_candidates_own_work_and_a_behavioural_row_both_survive(self):
        text = brief(COGNIZANT).must_cover.lower()
        assert "project deep-dive" in text
        assert "hr / behavioural" in text


class TestTheShapeIsNoLongerTwoThirdsSituations:
    def test_a_campus_round_is_a_viva(self):
        """
        REPORT (1). The mix is now arithmetic per interview kind rather than a bolded
        sentence, so this asserts the arithmetic: direct questions and cross-questions
        together must outnumber situations by a wide margin.
        """
        counts = question_shape.allocation(question_shape.InterviewKind.CAMPUS_FUNDAMENTALS, 12)
        fundamentals = counts[question_shape.Register.RECALL] + counts[question_shape.Register.CROSS]
        assert fundamentals > counts[question_shape.Register.SCENARIO] * 2

    def test_the_cross_question_is_a_first_class_form_and_not_an_afterthought(self):
        # The texture the candidate asked for — "can you override a static method?" — was
        # capped at four per interview and gated behind a 12-word answer and every third
        # turn. At plan time it is now a row like any other.
        counts = question_shape.allocation(question_shape.InterviewKind.CAMPUS_FUNDAMENTALS, 12)
        assert counts[question_shape.Register.CROSS] >= 2
        assert "cross-question" in brief(COGNIZANT).must_cover.lower()

    def test_a_non_technical_round_is_still_mostly_situations(self):
        """
        THE OTHER HALF OF THE PRODUCT. Deleting the scenario mandate outright would have
        broken this: for a sales or consulting screen, a definition tells you nothing about
        whether somebody can do the job, and the mandate was right there.
        """
        counts = question_shape.allocation(question_shape.InterviewKind.ROLE_SCENARIO, 12)
        assert counts[question_shape.Register.SCENARIO] > counts[question_shape.Register.RECALL]

    @pytest.mark.parametrize("count", COUNTS)
    def test_the_mix_is_rendered_as_counts_derived_from_the_setting(self, count: int):
        # "3 of 12" written as a literal anywhere is the bug where raising
        # INTERVIEW_QUESTION_COUNT moves the dashboard's promise and not the interview.
        text = brief(COGNIZANT, count=count).question_mix
        assert str(max(count - 1, 0)) in text
        assert "counts rather than preferences" in text


class TestTheBoxTheCandidateTyped:
    def test_a_named_subject_becomes_a_guaranteed_count(self):
        """REPORT (2), in one assertion."""
        text = brief(COGNIZANT, focus="Focus on React hooks and SQL joins").focus_directive
        assert "React & Frontend" in text
        assert "SQL & Data Modelling" in text
        assert "guarantee and not a preference" in text

    def test_the_reserved_rows_appear_in_the_grid_and_not_only_in_the_prose(self):
        # A directive promising three React questions over a grid that has none is worse
        # than the original bug: it is a promise the brief itself contradicts.
        text = brief(COGNIZANT, focus="React").must_cover
        assert text.count("React & Frontend") >= 2

    def test_something_the_syllabus_does_not_have_is_not_forced_in(self):
        text = brief(COGNIZANT, focus="Kubernetes and service meshes").focus_directive
        assert "names no subject" in text
        assert "must not be treated as one" in text

    def test_nerves_are_not_turned_into_a_topic_list(self):
        # "go easy on me" is not a syllabus. Reading it as one is a worse failure than
        # ignoring the box was, because it silently replaces what they came to practise.
        text = brief(COGNIZANT, focus="please go easy on me, I'm nervous").focus_directive
        assert "how to pitch" in text

    def test_an_empty_box_says_so_rather_than_rendering_a_placeholder(self):
        assert "did not fill in the box" in brief(COGNIZANT, focus="").focus_directive

    @pytest.mark.parametrize("count", COUNTS)
    def test_the_focus_never_takes_the_whole_interview(self, count: int):
        from app.services.interview.focus import slots

        assert 2 <= slots(count) <= 3


class TestTheNonTechnicalPathIsUntouched:
    def test_a_sales_role_does_not_reach_the_syllabus(self):
        assert brief(SALES, is_technical=False).from_syllabus is False

    def test_it_is_still_told_the_role_is_not_technical(self):
        assert "NOT a technical role" in brief(SALES, is_technical=False).must_cover

    def test_the_explicit_non_technical_answer_decides_the_shape(self):
        """
        `is_technical` used to be resolved AFTER this prompt was built and written only to
        session_metadata — so ticking "non-technical" changed whether a code editor appeared
        and changed nothing about what was asked. It is now an input to the brief.
        """
        assert brief(SALES, is_technical=False).kind is question_shape.InterviewKind.ROLE_SCENARIO
        assert brief(SALES, is_technical=True).kind is not question_shape.InterviewKind.ROLE_SCENARIO

    def test_a_non_technical_brief_carries_no_coding_row(self):
        assert "code aloud" not in brief(SALES, is_technical=False).must_cover.lower()


class TestNoCannedQuestionsReachTheModel:
    @pytest.mark.parametrize("count", COUNTS)
    def test_the_brief_contains_no_question_sentence(self, count: int):
        """
        The candidate's constraint, enforced on the rendered output rather than only on the
        data file: "do not copy past or harcode anything". A descriptor is a subject, not a
        question, so nothing in the grid may be a sentence ending in a question mark that a
        model could simply read out.

        Scoped to the grid rows, because the surrounding instructions legitimately contain
        questions about how to write questions.
        """
        text = brief(COGNIZANT, count=count).must_cover
        rows = [line for line in text.splitlines() if line.startswith("| ") and "|" in line[2:]]
        assert rows, "the grid rendered no rows at all"
        for row in rows:
            assert "?" not in row, f"a grid row reads as a question, not a subject: {row}"

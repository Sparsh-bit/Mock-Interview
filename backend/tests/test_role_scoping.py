"""
Questions must match the ROLE — tests/test_role_scoping.py

Reported: "for the role of an analyst why it is asking everytime the same thing i told you
that i want questions according to the role strictly."

It was, and there were three separate causes, all pointing the same way:

  1. `_must_cover_block` handed the planner the curated JAVA fundamentals list whatever the
     role was. A Deloitte Analyst — a consulting role screened on case reasoning, DBMS and a
     group discussion — was briefed to cover core Java, and covered core Java.
  2. `_ensure_seed_questions` seeded the same Java bank for every track when planning failed
     or the bank was empty. The same ~37 questions, in the same order, forever. That is the
     "everytime the same thing" part exactly.
  3. The skill check asked every candidate to rate themselves in Java, including the ones
     whose role never touches it.

The catalogue already carried the right answer per company and always had. These tests pin
that it is now the thing being used.
"""

from __future__ import annotations

import pytest

from app.api.v1.panel import _pivot_order_for, _rating_subject
from app.data import domains
from app.services.interview.context import InterviewContext, decide_technical
from app.services.interview.orchestrator import _is_java_role, _must_cover_block


def ctx(role: str, company: str = "") -> InterviewContext:
    """
    An InterviewContext built the way the app builds one — from what the CANDIDATE typed.

    These used to pass a bare track name, which is precisely the bug that made a sales
    interview for Morani Plastics greet the candidate as an "Advanced ASE at Accenture": the
    catalogue track and what they actually asked for are two different things, and the panel
    was reading the wrong one. Going through the same resolver the app uses means a test
    cannot pass while the real call site reads the other source.
    """
    return InterviewContext(
        company=company,
        role=role,
        domain=domains.resolve(role, ""),
        is_technical=decide_technical(role),
        domain_matched=domains.matched(role, ""),
    )



class TestWhichRolesGetJava:
    @pytest.mark.parametrize(
        "track",
        ["Digital Nurture — Java FSE", "Java Full Stack Engineer", "Backend Developer",
         "Power Programmer", "Digital Specialist Engineer (DSE)"],
    )
    def test_java_and_backend_roles_do(self, track: str):
        assert _is_java_role(track, "") is True

    @pytest.mark.parametrize(
        "track", ["Analyst", "Senior Analyst", "Business Analyst", "Data Analyst"]
    )
    def test_analyst_roles_do_not(self, track: str):
        # The whole complaint in one assertion.
        assert _is_java_role(track, "") is False


class TestWhatThePlannerIsTold:
    def test_an_analyst_is_not_briefed_on_java(self):
        brief = _must_cover_block("Analyst", "", "Deloitte")
        # Asserted on intent, not on a phrase. The brief used to open with the literal
        # "NOT a Java/backend role"; what has to hold is that the planner is told not to fall
        # back to Java, however that is worded.
        assert "not default to Java" in brief
        # No Java topic names anywhere. Mentioning one IS an instruction to ask about it.
        low = brief.lower()
        for java_only in ("jvm", "hashmap", "string pool", "garbage collection", "spring"):
            assert java_only not in low, f"the analyst brief still mentions {java_only}"

    def test_an_analyst_is_briefed_on_what_the_company_actually_assesses(self):
        brief = _must_cover_block("Analyst", "", "Deloitte")
        # Straight out of the catalogue, which validates these to sum to 100.
        assert "Aptitude & Case Reasoning" in brief
        assert "DBMS & SQL" in brief
        assert "22%" in brief

    def test_a_java_role_still_gets_the_curated_bank(self):
        # The fix must not cost the role it was built for.
        #
        # STILL TRUE OF THIS FUNCTION, NO LONGER THE PATH PRODUCTION TAKES for Cognizant.
        # `_plan_brief` now prefers an authored syllabus where one exists, because this bank
        # is sixteen Java topics with no React and no SQL area — which is what a Digital
        # Nurture candidate reported as "the interview is not covering all the topics". The
        # bank remains the fallback for every role without a syllabus, so this assertion is
        # about a live code path; see tests/test_plan_brief.py for what Cognizant now gets.
        brief = _must_cover_block("Digital Nurture — Java FSE", "", "Cognizant")
        assert "Collections framework" in brief
        assert "OOP & class design" in brief

    def test_an_unknown_company_still_produces_a_usable_brief(self):
        # A candidate typing any firm must still get a working interview.
        brief = _must_cover_block("Analyst", "", "Some Startup Nobody Has Heard Of")
        assert brief.strip()
        assert "Do not default to Java" in brief


class TestThePivotOffersSomethingRelevant:
    def test_an_analyst_is_not_offered_the_jvm_as_a_lifeline(self):
        # A pivot is offered to somebody who has just admitted they do not know something.
        # Offering them a topic from the wrong job, at that moment, is worse than nothing.
        offered = _pivot_order_for(ctx("Analyst", "Deloitte"))
        assert offered
        assert not any("JVM" in t or "String pool" in t for t in offered)

    def test_it_offers_what_the_company_weights_most_first(self):
        assert _pivot_order_for(ctx("Analyst", "Deloitte"))[0] == "Aptitude & Case Reasoning"
        assert _pivot_order_for(ctx("Analyst", "Capgemini"))[0] == "Aptitude & Logical Reasoning"

    def test_it_never_offers_to_talk_about_hr_instead(self):
        # A pivot finds technical ground the candidate can stand on. "Shall we talk about
        # your project instead?" reads as giving up on the technical round.
        for company in ("Deloitte", "Capgemini", "Infosys"):
            for topic in _pivot_order_for(ctx("Analyst", company)):
                assert "hr" not in topic.lower()

    def test_a_java_role_still_gets_the_curated_order(self):
        assert _pivot_order_for(ctx("Digital Nurture — Java FSE", "Cognizant"))[0] == (
            "OOP & class design"
        )

    def test_an_unknown_company_falls_back_to_universal_topics(self):
        # Every Indian campus technical round covers these whatever the employer.
        offered = _pivot_order_for(ctx("Analyst", "Some Startup"))
        assert "DBMS & SQL" in offered
        assert "Programming fundamentals" in offered


class TestThePromptAsksAboutTheRightSubject:
    def test_the_skill_check_is_not_hardcoded_to_java(self):
        import re
        from pathlib import Path

        # Whitespace collapsed: the prompt is hard-wrapped markdown, so a phrase genuinely
        # spans a line break. Matching raw text would fail whenever somebody reflows a
        # paragraph, which is how tests get deleted rather than fixed.
        raw = (
            Path(__file__).resolve().parents[1] / "app" / "prompts" / "interview_panel.md"
        ).read_text()
        prompt = re.sub(r"\s+", " ", raw)
        # The prompt no longer REASONS about the subject at all — it is handed one.
        #
        # Asking the model to infer it from the role title was the bug: every branch it could
        # be given was technical, so a sales role fell through to "programming fundamentals".
        # The model is not the thing that knows what a role is screened on; domains.py is.
        assert "THE SUBJECT IS GIVEN TO YOU" in prompt
        assert "What to ask them to rate themselves on" in prompt
        assert "Do not substitute your own idea of what the role needs" in prompt
        # And the consequence, stated, because a rule with a reason is followed.
        assert "does not know what job they applied for" in prompt


class TestANonTechnicalRoleGetsANonTechnicalInterview:
    """
    Reported, with a screenshot: "the role is sales/business development and the topics are
    technical".

    They were, and the cause was one sentence. When the company was not on the catalogue —
    Asian Paints is not, the catalogue is twelve IT recruiters — `_must_cover_block` fell
    through to a branch that told the planner to cover "programming fundamentals, DBMS and
    SQL, data structures". The plan that came back was Programming Fundamentals, Data
    Structures, DBMS & SQL and Version Control, for a sales candidate. The model did as it
    was told; the brief was the bug.

    `app.data.domains` now answers "what is this role" for every role, so the fallback has a
    real weighting to hand over.
    """

    SALES = ("Sales / Business Development", "", "Asian Paints")

    def test_a_sales_role_is_briefed_on_sales(self):
        brief = _must_cover_block(*self.SALES)
        assert "Sales & Business Development" in brief
        # Straight from the domain profile, whose weights are validated to sum to 100.
        assert "Objection Handling" in brief
        assert "Channel & Distribution" in brief

    def test_a_sales_role_is_not_briefed_on_computer_science(self):
        # The assertion the screenshot deserves — scoped to the MUST-COVER LIST rather than
        # the whole brief. Naming a CS topic in the list of things to cover is an instruction
        # to ask about it; naming one inside the explicit "do not ask about these" prohibition
        # is the opposite, and asserting over the whole brief cannot tell those apart.
        from app.data import domains

        brief = domains.topic_block("Sales / Business Development").lower()
        for cs_only in (
            "programming fundamentals",
            "data structures",
            "dbms",
            "version control",
            "oop",
        ):
            assert cs_only not in brief, f"the sales brief still names {cs_only}"

    def test_a_non_technical_role_is_told_so_outright(self):
        assert "NOT a technical role" in _must_cover_block(*self.SALES)

    def test_a_technical_role_keeps_its_technical_brief(self):
        # The fix must not quietly strip CS content from roles that are screened on it.
        brief = _must_cover_block("Data Analyst", "", "Some Startup Nobody Has Heard Of")
        assert "SQL & Data Modelling" in brief
        assert "NOT a technical role" not in brief

    def test_an_unmatched_title_does_not_get_a_domain_invented_for_it(self):
        # "Analyst" alone is genuinely ambiguous — a Deloitte Analyst is consulting, a
        # Capgemini Analyst is technical. Asserting either would be inventing one, and
        # asserting a HARD prohibition on a guess could shut down a legitimate technical
        # interview.
        brief = _must_cover_block("Analyst", "", "Some Startup Nobody Has Heard Of")
        assert "did not match a known domain" in brief
        assert "NOT a technical role" not in brief


class TestThePanelHoldsTheRightJob:
    """
    Reported: "the postion and the department of the panalyst must get changed according to
    the role and comapny give to them".

    The two designations were hardcoded to "Senior Engineering Manager" and "Technical Lead"
    for every interview, so a sales candidate's first impression of the room was two
    engineering titles.
    """

    def test_a_sales_panel_is_a_sales_panel(self):
        from app.api.v1.panel import panel_for

        roles = [i.role for i in panel_for("Sales / Business Development")]
        assert roles == ["Regional Sales Manager", "Area Sales Lead"]

    def test_an_engineering_panel_is_unchanged(self):
        from app.api.v1.panel import INTERVIEWERS, panel_for

        assert [i.role for i in panel_for("Java Full Stack Engineer")] == [
            i.role for i in INTERVIEWERS
        ]

    def test_names_and_genders_never_move(self):
        # They are bound to the voice ids. A panel whose names shifted by role would put
        # Priya in Anil's voice.
        from app.api.v1.panel import INTERVIEWERS, panel_for

        for role in ("HR Executive", "Civil Site Engineer", "Marketing Intern", ""):
            panel = panel_for(role)
            assert [i.name for i in panel] == [i.name for i in INTERVIEWERS]
            assert [i.gender for i in panel] == [i.gender for i in INTERVIEWERS]


class TestTheDomainRegistryResolvesAmbiguousTitles:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Sales / Business Development", "sales"),
            # "business analyst" must beat "business development", and "data analyst" must
            # beat the generic analyst titles. Both are ordering, not luck — see _KEYWORDS.
            ("Business Analyst", "consulting"),
            ("Data Analyst", "data"),
            ("Financial Analyst", "finance"),
            ("Chemical Process Engineer", "chemical"),
            ("Civil Site Engineer", "civil"),
            ("HR Executive", "hr"),
            ("Supply Chain Executive", "operations"),
            ("Embedded Systems Engineer", "electrical"),
            ("Mechanical Design Engineer", "mechanical"),
        ],
    )
    def test_resolution(self, title: str, expected: str):
        from app.data import domains

        assert domains.resolve(title) == expected

    def test_short_keywords_do_not_over_match(self):
        # "hr " and "it " are two characters plus a space and would fire on "through" and
        # "unit" if the matcher were naive.
        from app.data import domains

        assert domains.resolve("Through-put Improvement Engineer") != "hr"

    def test_every_profile_is_usable(self):
        from app.data import domains

        for key, profile in domains.PROFILES.items():
            assert profile["scenarios"], f"{key} has no seed questions"
            assert profile["lead_role"] and profile["specialist_role"], key
            assert sum(w for _, w in profile["topics"]) == 100, key

    def test_seed_questions_are_scenarios_not_definitions(self):
        """
        Reported: "make sure most of them are scnerio based questions".

        Pinned on the seed bank because that is the half the planner cannot override — a
        definitional seed set drags every fallback interview back into viva shape. Counted
        rather than asserted per question: a domain is allowed a few direct questions where a
        definition really is what gets asked.
        """
        import re

        from app.data import domains

        # Counted by exclusion, and that is deliberate. Two earlier versions of this test tried
        # to recognise a situational question positively — first from a list of literal
        # phrasings, then from a question-word pattern — and both scored real scenarios as
        # definitions ("What could be happening?" has no "you" in it; "Tell me about a project"
        # is not "tell me about a time"). Enumerating every way English can pose a situation is
        # the wrong problem. A DEFINITION, by contrast, has a small and stable set of openers,
        # so the test asks how many questions open like a textbook and requires it to stay a
        # minority.
        definitional = re.compile(
            r"^\s*(?:explain\b|define\b|what\s+is\b|what\s+are\b|what\s+do\s+you\s+mean\b"
            r"|describe\s+the\s+difference\b|state\s+the\b|list\s+the\b)",
            re.IGNORECASE,
        )
        for key, profile in domains.PROFILES.items():
            scenarios = profile["scenarios"]
            textbook = [q for q in scenarios if definitional.match(q["content"])]
            assert len(textbook) * 3 <= len(scenarios), (
                f"{key}: {len(textbook)} of {len(scenarios)} seed questions open like a "
                "definition; the bank has drifted back toward a viva"
            )


class TestTheRatingSubjectComesFromTheRole:
    """
    The sales bug, pinned. "in the sales interview the interviewer is still asking for the
    rate in java" — reported after the role scoping was supposedly fixed, because the
    scoping fixed what was ASKED and not what the candidate was asked to rate themselves on.
    """

    def test_a_java_role_is_asked_about_java(self):

        assert _rating_subject(ctx("Digital Nurture — Java FSE")) == "Java"

    @pytest.mark.parametrize(
        ("role", "expected"),
        [
            ("Sales Executive", "Sales & Business Development"),
            ("Business Development", "Sales & Business Development"),
            ("Marketing", "Marketing & Brand"),
            ("HR Executive", "Human Resources"),
        ],
    )
    def test_a_non_technical_role_is_asked_about_its_own_field(self, role, expected):

        assert _rating_subject(ctx(role)) == expected

    def test_no_role_is_ever_asked_about_a_technology_it_does_not_use(self):
        # The assertion that would have caught the original report.

        for role in ("Sales", "Sales Executive", "HR Executive", "Marketing", "Recruiter"):
            subject = _rating_subject(ctx(role)).lower()
            for tech in ("java", "python", "sql", "programming", "data structure"):
                assert tech not in subject, f"{role} would be asked to rate itself on {tech}"

    def test_an_unknown_role_names_no_technology_at_all(self):
        # The old fallback said "programming fundamentals", which is a guess dressed as an
        # answer. Naming nothing is honest; naming the wrong thing is disqualifying.

        subject = _rating_subject(ctx("Something Nobody Has Heard Of")).lower()
        assert "java" not in subject
        assert "programming" not in subject


class TestTheEditorFollowsTheRole:
    """A sales candidate must not be shown a code editor."""

    @pytest.mark.parametrize("role", ["Sales Executive", "HR Executive", "Marketing"])
    def test_non_technical_roles_get_no_editor(self, role):
        from app.data import domains

        technical = not domains.matched(role, "") or domains.is_technical(role, "")
        assert technical is False

    @pytest.mark.parametrize(
        "role", ["Digital Nurture — Java FSE", "Mechanical Engineer", "Data Analyst"]
    )
    def test_technical_roles_keep_it(self, role):
        from app.data import domains

        assert not domains.matched(role, "") or domains.is_technical(role, "")

    def test_an_unrecognised_role_keeps_the_editor(self):
        # The forgiving direction. A missing editor costs a technical candidate the question;
        # a spurious one costs everybody else a glance.
        from app.data import domains

        role = "Something Nobody Has Heard Of"
        assert (not domains.matched(role, "") or domains.is_technical(role, "")) is True


class TestTheExplicitTechnicalChoice:
    """
    The setup form asks "technical or not" and the answer beats the inference.

    Inference is keyword matching over a free-text role. It cannot know that "Civil Services"
    is the IAS exam rather than civil engineering — only that it matches something. It matched
    civil ENGINEERING, and a UPSC aspirant was offered "Site Execution" and "Structural
    Design" as the thing to talk about instead.
    """

    def test_civil_services_no_longer_matches_civil_engineering(self):
        # The keyword was bare "civil". A substring list is only as good as its least
        # specific entry, and this product's largest future audience is UPSC.
        assert domains.resolve("Civil Services", "") != "civil"
        assert domains.resolve("Civil Engineer", "") == "civil"
        assert domains.resolve("Structural Engineer", "") == "civil"

    def test_a_stated_non_technical_role_is_never_offered_technical_topics(self):
        from app.api.v1.panel import _pivot_order_for

        for role in ("Civil Services", "UPSC aspirant", "Something Nobody Has Heard Of"):
            ctx = InterviewContext(
                company="",
                role=role,
                domain=domains.resolve(role, ""),
                is_technical=False,
                domain_matched=domains.matched(role, ""),
            )
            offered = " ".join(_pivot_order_for(ctx)).lower()
            for technical in ("programming", "dbms", "sql", "data structures", "structural"):
                assert technical not in offered, f"{role} was offered {technical}"

    def test_the_statement_wins_even_when_a_domain_matched(self):
        # The general form of the bug. If they say it is not technical and the matched domain
        # IS technical, the match is simply wrong — trusting it over the person is what
        # produced structural design for a UPSC candidate.
        from app.api.v1.panel import _pivot_order_for

        ctx = InterviewContext(
            company="",
            role="Civil Engineer",  # genuinely matches a technical domain
            domain="civil",
            is_technical=False,  # …but the candidate says it is not
            domain_matched=True,
        )
        assert "Situational judgement" in _pivot_order_for(ctx)

    def test_a_non_software_technical_role_gets_its_own_field(self):
        # The other direction: mechanical and civil are technical and neither is asked about
        # DBMS. This branch used to go straight from "not a Java role" to a computer-science
        # fallback.
        from app.api.v1.panel import _pivot_order_for

        for role, expected in [
            ("Civil Engineer", "Site Execution"),
            ("Mechanical Engineer", "Design & Materials"),
            ("Data Analyst", "Data Analysis"),
        ]:
            ctx = InterviewContext(
                company="",
                role=role,
                domain=domains.resolve(role, ""),
                is_technical=True,
                domain_matched=True,
            )
            assert _pivot_order_for(ctx)[0] == expected

    def test_the_general_list_assumes_no_industry(self):
        # A UPSC aspirant, a hotel-management fresher and a logistics trainee must all be
        # askable about every one of these without it landing as absurd.
        from app.api.v1.panel import _GENERAL_NON_TECHNICAL_TOPICS

        joined = " ".join(_GENERAL_NON_TECHNICAL_TOPICS).lower()
        for industry_word in ("sales", "hr", "marketing", "code", "engineering"):
            assert industry_word not in joined

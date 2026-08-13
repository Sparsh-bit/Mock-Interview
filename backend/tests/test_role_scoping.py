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

from app.api.v1.panel import _pivot_order_for
from app.services.interview.orchestrator import _is_java_role, _must_cover_block


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
        offered = _pivot_order_for("Analyst", "Deloitte")
        assert offered
        assert not any("JVM" in t or "String pool" in t for t in offered)

    def test_it_offers_what_the_company_weights_most_first(self):
        assert _pivot_order_for("Analyst", "Deloitte")[0] == "Aptitude & Case Reasoning"
        assert _pivot_order_for("Analyst", "Capgemini")[0] == "Aptitude & Logical Reasoning"

    def test_it_never_offers_to_talk_about_hr_instead(self):
        # A pivot finds technical ground the candidate can stand on. "Shall we talk about
        # your project instead?" reads as giving up on the technical round.
        for company in ("Deloitte", "Capgemini", "Infosys"):
            for topic in _pivot_order_for("Analyst", company):
                assert "hr" not in topic.lower()

    def test_a_java_role_still_gets_the_curated_order(self):
        assert _pivot_order_for("Digital Nurture — Java FSE", "Cognizant")[0] == (
            "OOP & class design"
        )

    def test_an_unknown_company_falls_back_to_universal_topics(self):
        # Every Indian campus technical round covers these whatever the employer.
        offered = _pivot_order_for("Analyst", "Some Startup")
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
        # It must reason from the role rather than naming one language for everybody.
        assert "ASK ABOUT THE SUBJECT THIS ROLE IS ACTUALLY SCREENED ON" in prompt
        assert "Analyst or consulting role" in prompt
        assert "Never invent a technology the role has nothing to do with" in prompt


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

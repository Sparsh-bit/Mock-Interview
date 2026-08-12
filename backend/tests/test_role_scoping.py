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
        assert "NOT a Java/backend role" in brief
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

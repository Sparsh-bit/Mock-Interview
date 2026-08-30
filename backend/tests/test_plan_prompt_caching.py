"""
The interview prompts became cacheable, and nothing about them changed — tests/test_plan_prompt_caching.py

`cache_system=True` was already paying for itself on the GD panel: 59% off the round. It was
off everywhere else for one reason — those prompts interpolated per-request variables into
the system block, so no two requests shared a prefix and a cache marker would have billed a
1.25x WRITE on every call and never scored a read. Costing 25% more, silently, forever.

TWO PROMPTS HAVE NOW MOVED THEIR VARIABLES INTO THE USER TURN.

  interview_plan.md — 6,546 tokens, the largest prompt in this product, and it carried
  ELEVEN placeholders. Every interview created re-sent and re-paid for the whole document.

  question_generator.md — 2,850 tokens and eight placeholders. Smaller, and worth more per
  token, because it is called repeatedly WITHIN one interview: the first question of a
  session pays the write and every question after it reads, inside the cache's own
  five-minute window. The plan only hits when another candidate arrives in that window.

WHAT THESE TESTS ARE FOR IS THE RISK OF THE MOVE, NOT THE MOVE.

  1. A PROMPT EDIT SMUGGLED INSIDE A PLUMBING EDIT. The instruction was to change where the
     variable data sits, not what the model is asked. Rules, headings and ordering are
     pinned below — tests/test_plan_brief.py already pins a great deal of the plan's
     content, and this adds the structural half: every section the rules refer to exists in
     the brief, and every section the brief emits is referred to by the rules.

  2. A PLACEHOLDER CREEPING BACK. `chat_static` loads the file VERBATIM, so a returning
     dollar-token is not substituted — it ships to the model as the literal text
     "$question_mix", inside a section headed "How many questions of each kind". Nothing
     fails. The interview runs. This is the failure test_prompt_caching.py exists for, and
     these tests cover the half it cannot see: the value that stopped arriving.

  3. THE TENANCY RULE SURVIVING THE MOVE. The shared-pool question batch is cached and
     served to OTHER candidates on the same track, so it must never carry what one
     candidate typed into the setup box. That rule used to be enforced on a keyword
     argument; it is now enforced on a brief section, and it is exactly as binding.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import re

import pytest

from app.services.interview import orchestrator as orch

PROMPTS = pathlib.Path(orch.__file__).resolve().parents[2] / "prompts"
BACKEND = pathlib.Path(__file__).resolve().parents[1]

_MOVED = ("interview_plan", "question_generator")


def _prompt(name: str) -> str:
    return (BACKEND / "app" / "prompts" / f"{name}.md").read_text(encoding="utf-8")


class TestTheSystemBlockIsByteIdenticalNow:
    @pytest.mark.parametrize("name", _MOVED)
    def test_the_template_carries_no_dollar_token_at_all(self, name):
        """
        Including inside a comment, and that is not pedantry.

        The loader returns the raw file — comments and all — as the system block, so a
        `$company` written in a header note is shipped to the model exactly like one in the
        body. report_summary.md's own header says the same thing, having learned it first.
        """
        found = sorted(set(re.findall(r"\$[a-zA-Z_]\w*", _prompt(name))))
        assert not found, (
            f"{name}.md still contains {found}. It is loaded verbatim by chat_static, so "
            "these ship to the model as literal text AND every request gets a unique "
            "prefix — the cache marker then bills a 1.25x write on every call and never "
            "reads. Move the value into the user brief."
        )

    @pytest.mark.parametrize("name", _MOVED)
    def test_the_same_template_loads_identically_every_time(self, name):
        # The actual property caching depends on, asserted directly rather than inferred
        # from the absence of tokens. `chat_static` is documented to load rather than
        # render; if that ever changes, this is what says so.
        from app.prompts.prompt_loader import get_prompt_loader

        loader = get_prompt_loader()
        assert loader.load(name) == loader.load(name)

    @pytest.mark.parametrize("name", _MOVED)
    def test_it_is_long_enough_for_the_provider_to_cache_at_all(self, name):
        """
        Sonnet only caches prefixes of 1024 tokens or more, and a shorter one fails SILENTLY
        — no error, no charge, no cache. Measured with Anthropic's own token counter:
        interview_plan 6,546 and question_generator 2,850. A rough 4-chars-per-token floor
        is enough to catch somebody halving one of these files and quietly losing the
        saving they thought they still had.
        """
        assert len(_prompt(name)) // 4 > 1024


class TestEveryCallSiteMovedTogether:
    """
    A template and its call sites have to change in the same commit. `chat` on a
    variable-free template is not an error — it substitutes nothing and works — it just
    means the caller is not asking for the cache, so the whole change buys nothing.
    """

    def test_the_plan_is_built_static_and_asks_for_the_cache(self):
        src = inspect.getsource(orch.InterviewOrchestrator.create_plan)
        assert 'chat_static(\n                system_template="interview_plan"' in src
        assert "cache_system=True" in src

    def test_both_question_call_sites_are_static_and_ask_for_the_cache(self):
        """
        TWO SITES, ONE CACHE ENTRY. `_bank_question`'s shared-pool batch of five and the
        per-session single question load the same template verbatim, so whichever runs
        first writes the prefix the other reads. Their briefs differ completely; their
        rules do not, and that is the entire point.
        """
        src = pathlib.Path(orch.__file__).read_text()
        static_calls = src.count('system_template="question_generator"')
        assert static_calls == 2, "question_generator should have exactly two call sites"
        assert src.count('chat_static(\n            system_template="question_generator"') == 2

        tree = ast.parse(src)
        opted_in = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == "context" and isinstance(kw.value, ast.Constant):
                    if kw.value.value not in {"question_bank", "question_generation"}:
                        continue
                    if any(
                        k.arg == "cache_system"
                        and isinstance(k.value, ast.Constant)
                        and k.value.value is True
                        for k in node.keywords
                    ):
                        opted_in += 1
        assert opted_in == 2, (
            "both question-generating calls must pass cache_system=True — one of them "
            "writing the prefix and the other not reading it is the worst of both"
        )

    def test_no_interview_prompt_is_still_built_with_the_substituting_builder(self):
        # `chat` remains correct for prompts that genuinely vary. What must not happen is
        # one of these two quietly going back to it, because that reverts the saving
        # without reverting anything a test would otherwise notice.
        src = pathlib.Path(orch.__file__).read_text()
        for name in _MOVED:
            assert f'chat(\n            system_template="{name}"' not in src
            assert f'chat(\n                system_template="{name}"' not in src


class TestTheRulesAndTheBriefStillAgree:
    """
    The coupling that replaced substitution: the rules name a section, the brief emits it.

    Neither half fails loudly on its own. A rule pointing at a section the brief does not
    write leaves the model looking for context that is not there; a section nobody refers to
    is tokens paid for and ignored. Both look like a working interview.
    """

    PLAN_SECTIONS = (
        "## Who the candidate is preparing for",
        "## The candidate's resume",
        "## What this company actually does",
        "## Researched intelligence on this company's real interview",
        "## Questions this candidate has already been asked",
        "## The topics that actually get asked",
        "## How many questions of each kind",
        "## What the candidate asked for",
    )

    QUESTION_SECTIONS = (
        "## Interview Context",
        "## What this candidate asked to practise",
    )

    @staticmethod
    def _plan_brief(**over) -> str:
        args: dict = {
            "company": "Cognizant",
            "program": "Programmer Analyst",
            "focus": "I want more SQL",
            "resume": "Built a Spring Boot claims service.",
            "business_context": "Healthcare claims processing.",
            "research": "Two rounds, DBMS-heavy.",
            "already_asked": "- What is a HashMap?",
            "must_cover": "1. DBMS — direct — easy",
            "question_mix": "Direct: 6, Cross: 3",
            "focus_directive": "Guarantee 2 SQL questions.",
            "question_count": 11,
        }
        args.update(over)
        return orch._plan_user_brief(**args)

    @pytest.mark.parametrize("section", PLAN_SECTIONS)
    def test_every_section_the_plan_rules_name_is_written_by_the_brief(self, section):
        assert section in _prompt("interview_plan"), f"the rules stopped naming {section!r}"
        assert section in self._plan_brief(), f"the brief stopped writing {section!r}"

    @pytest.mark.parametrize("section", QUESTION_SECTIONS)
    def test_every_section_the_question_rules_name_is_written_by_the_brief(self, section):
        brief = orch._question_user_brief(
            track_name="Java FSE",
            topics="Collections, JPA",
            difficulty="medium",
            question_number="3",
            candidate_experience_years="not specified",
            candidate_focus="(none)",
            already_asked="(none)",
            focus_concepts="(none)",
            task="Generate the next question.",
        )
        assert section in _prompt("question_generator")
        assert section in brief

    def test_the_brief_carries_every_value_it_is_given(self):
        # The other half of the coupling: a section that exists but is empty is a value
        # that stopped arriving, and safe_substitute used to at least leave a visible
        # "$token" behind when that happened. Nothing does now, so this is the check.
        brief = self._plan_brief()
        for value in (
            "Cognizant",
            "Programmer Analyst",
            "I want more SQL",
            "Spring Boot claims service",
            "Healthcare claims processing",
            "Two rounds, DBMS-heavy",
            "What is a HashMap?",
            "1. DBMS — direct — easy",
            "Direct: 6, Cross: 3",
            "Guarantee 2 SQL questions",
            "11",
        ):
            assert value in brief, f"{value!r} no longer reaches the model"

    def test_the_question_count_is_stated_as_a_number_the_rules_can_point_at(self):
        # `$question_count` appeared twice in the rules — once in the task and once in the
        # output format. Both now refer to this line, so it has to exist and be a number.
        assert "**Questions to produce**: 11" in self._plan_brief(question_count=11)
        assert "**Questions to produce**" in _prompt("interview_plan")

    def test_the_task_is_the_last_thing_the_model_reads(self):
        # It is the imperative the model acts on. Burying it above six sections of context
        # is how an instruction gets lost in a long brief.
        assert self._plan_brief().rstrip().endswith(
            "Design the interview plan now, following the rules and output format."
        )
        brief = orch._question_user_brief(
            track_name="Java FSE",
            topics="Collections",
            difficulty="easy",
            question_number="1",
            candidate_experience_years="not specified",
            candidate_focus="(none)",
            already_asked="(none)",
            focus_concepts="(none)",
            task="Generate FIVE distinct interview questions.",
        )
        assert brief.rstrip().endswith("Generate FIVE distinct interview questions.")

    def test_an_empty_section_still_appears_with_its_heading(self):
        # An omitted heading is a heading the rules still refer to and the model cannot
        # find — strictly worse than one saying there is nothing here. The callers pass an
        # explanatory sentence for each, exactly as the old placeholders did.
        brief = self._plan_brief(
            already_asked="(this is their first interview — nothing to avoid)",
            resume="(no resume on file)",
        )
        assert "## Questions this candidate has already been asked" in brief
        assert "nothing to avoid" in brief
        assert "## The candidate's resume" in brief


class TestNothingAboutTHEASKChanged:
    """
    The instruction was to move where variable data sits, not to edit the prompt.

    test_plan_brief.py already pins a great deal of the plan's content. These are the rules
    most at risk from a careless move, because each one sat immediately next to a variable
    that was being cut out of the file.
    """

    @pytest.mark.parametrize(
        "rule",
        [
            "Never ask this candidate something they have already been asked",
            "The must-cover block governs subjects and forms",
            "The candidate's own request is guaranteed, not optional",
            "The research tells you topic, emphasis, difficulty and style — never wording",
            "The company's domain is the setting for a question, never its subject",
        ],
    )
    def test_the_precedence_order_is_intact(self, rule):
        # The five-rule ordering at the top is what stops a later, more forcefully worded
        # instruction overriding an earlier one. Every one of them governs an input that
        # just moved into the brief.
        assert rule in _prompt("interview_plan")

    @pytest.mark.parametrize(
        "rule",
        [
            "EVERY TECHNOLOGY NAMED ON A RESUME IS A CLAIM",
            "NEVER INVENT ANYTHING",
            "Never reuse the literal wording of a researched question",
            "Do not repeat any of these, or ask the same thing in different words",
            "Do not invent subjects this role does not have",
            "**never `\"coding\"`**",
        ],
    )
    def test_the_rules_that_sat_beside_a_moved_variable_are_intact(self, rule):
        assert rule in _prompt("interview_plan")

    @pytest.mark.parametrize(
        "rule",
        [
            "Ask exactly ONE focused question",
            "Paraphrase counts as a repeat",
            "Difficulty is how DEMANDING the question is, not which",
            "Write the wording fresh, every time",
            "never `\"coding\"`",
        ],
    )
    def test_the_question_generator_rules_are_intact(self, rule):
        assert rule in _prompt("question_generator")


class TestTheTenancyRuleSurvivedTheMove:
    """
    `_bank_question` generates five questions cached in `question_bank` and served to OTHER
    candidates on the same track. CLAUDE.md's tenancy rule is that nothing derived from one
    candidate may reach another, and the setup box is candidate input.

    That rule used to be enforced on a keyword argument and is now enforced on a brief
    section. tests/test_question_tenancy.py owns the question in general; this asserts the
    specific thing the move could have broken.
    """

    def test_the_shared_pool_brief_carries_a_sentinel_not_a_candidates_words(self):
        src = inspect.getsource(orch.InterviewOrchestrator._bank_question)
        assert 'candidate_focus="(shared pool — no candidate, no preferences)"' in src

    def test_the_shared_pool_brief_names_no_session(self):
        # The batch is generated without a candidate, so nothing candidate-shaped may reach
        # the brief at all — not the focus, not an already-asked list from one person's
        # session, not their scorer's focus concepts.
        src = inspect.getsource(orch.InterviewOrchestrator._bank_question)
        brief = src.split("_question_user_brief(")[1].split("task=")[0]
        # Comments stripped — prose about the rule is not the rule, and the comment here
        # explains the rule by naming the per-session call site it contrasts with.
        code = "\n".join(
            line for line in brief.splitlines() if not line.strip().startswith("#")
        )
        assert "_candidate_focus_block" not in code
        assert "session" not in code

    def test_the_per_session_brief_does_carry_what_they_typed(self):
        # The other half. This is the path that used to lose the typed focus entirely once
        # the plan was exhausted, and the move must not have quietly undone the fix.
        src = pathlib.Path(orch.__file__).read_text()
        assert "candidate_focus=_candidate_focus_block(session)" in src

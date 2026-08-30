"""
An interview for a field nobody authored — tests/test_open_domain.py

THE GAP. `data/domains.py` resolves a role title against a hand-written keyword list of
twelve families. It is right for every family it names, and for everything else it returns the
default — software — with `matched()` False so a caller can tell the two apart. Five callers
then each did something reasonable with "unmatched", and together they produced a software
interview wearing the candidate's job title:

    stream typed                                is_technical   panel               asked to rate
    "Sommelier and wine list curation"          True (!)       Senior Eng Manager  "the core skills for this role"
    "Bharatanatyam choreography"                True (!)       Technical Lead      "the core skills for this role"

with a code editor on screen, a must-cover block that was a paragraph of prose asking the
model to infer the role, and "Programming fundamentals, DBMS & SQL" offered as the lifeline
when the candidate admitted a gap.

WHAT THESE TESTS PIN, in the order the pipeline runs:

  1. THE CURATED PATH IS UNTOUCHED AND PREFERRED. The generator is never invoked for a stream
     the catalogue names — asserted by counting calls, not by reading the code, because "it
     is guarded" and "the guard fires" are different claims.
  2. The schema rejects what a free-form path is most likely to produce: a weighting that is
     not a distribution, and question text where an area name should be.
  3. A generated profile produces a real brief — for a technical field AND a non-technical
     one — and the non-technical one carries no computer science anywhere in it.
  4. The brief substitutes cleanly into the REAL `interview_plan.md`, leaving no `$token`
     behind. That is the same guarantee `test_plan_brief.py` gives the curated paths, and it
     is what "the rest of the pipeline works unmodified" actually means.
  5. The plan the model returns is validated by exactly the same `InterviewPlan` schema the
     curated path uses. The open-domain path is more free-form in what it can be ABOUT; it is
     not more permissive in what it may return.
  6. The profile survives onto the session and the panel reads it — designations, rating
     subject, pivot topics and the code editor all come from the field that was resolved.
  7. End to end against a real database: `create_plan` for an uncatalogued stream persists a
     full-length plan and pins the profile.

WHAT IS DELIBERATELY NOT ASSERTED. No test here pins a question sentence or an area name that
a model produced, for the reason `syllabus.py` gives at length: this path exists to stop
canned content, and a test asserting a generated phrase would put it back. Every assertion
below is about SHAPE, about which path ran, or about a subject that must be ABSENT.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.data import domains, question_shape
from app.data import syllabus as syllabus_data
from app.services.ai.schemas import InterviewPlan, OpenDomainProfile
from app.services.interview import open_domain
from app.services.interview.context import InterviewContext
from app.services.interview.open_domain import OpenDomain
from app.services.interview.orchestrator import _must_cover_block, _plan_brief

# ─── The streams under test ───────────────────────────────────────────────────
#
# CHECKED AGAINST THE RESOLVER RATHER THAN ASSUMED, by test_the_premise_of_this_file below.
# Two of these were named in the request as examples of "arbitrary" streams and are in fact
# already on the catalogue — "embedded" is an electrical keyword and "strategy" a consulting
# one — so they belong in the curated column. Writing them down as open would have produced a
# file whose central assertion was vacuous.

#: Streams the hand-authored catalogue covers. These must never reach the generator.
CURATED = {
    "cognizant_java_fse": ("Digital Nurture — Java FSE", "Cognizant"),
    "sales": ("Sales Executive", "Morani Plastics"),
    # Named in the request as a "clearly technical" arbitrary stream. It matches `embedded`,
    # so the catalogue answers it, and the catalogue's answer is the better one.
    "embedded_systems_debugging": ("Embedded Systems Debugging", "Bosch"),
    # Named in the request as a "clearly non-technical" one. Matches `strategy` → consulting,
    # which is right: a brand-strategy case interview IS a case interview.
    "brand_strategy_case": ("Brand Strategy Case Interview", "Ogilvy"),
}

#: Streams nothing in the catalogue names. These are what the open path exists for.
OPEN_TECHNICAL = "Firmware bring-up for RISC-V microcontrollers"
OPEN_NON_TECHNICAL = "Museum curation and archival conservation"


# ─── Profiles a model plausibly returns, used as generator output ─────────────
#
# Hand-written stand-ins for a model response, and they are the shape the model is asked for
# rather than a shape convenient for the test: `_the_model_returns` below pushes each through
# the real `OpenDomainProfile` validator before any test sees it, so a fixture that could not
# have come off the wire fails here rather than passing a test it should not.

FIRMWARE_JSON = {
    "label": "Embedded Firmware Engineering",
    "is_technical": True,
    "lead_role": "Firmware Engineering Manager",
    "specialist_role": "Senior Embedded Engineer",
    "rating_subject": "bare-metal firmware and hardware bring-up",
    "topics": [
        {"name": "Board Bring-Up & Boot Flow", "weight": 20},
        {"name": "Peripheral Drivers & Buses", "weight": 18},
        {"name": "Interrupts & Real-Time Constraints", "weight": 17},
        {"name": "Memory Maps & Linker Scripts", "weight": 15},
        {"name": "On-Target Debugging & Tracing", "weight": 15},
        {"name": "Ownership & Working Under Pressure", "weight": 15, "behavioural": True},
    ],
}

CURATION_JSON = {
    "label": "Museum Curation & Conservation",
    "is_technical": False,
    "lead_role": "Head of Collections",
    "specialist_role": "Senior Conservator",
    "rating_subject": "collection care and exhibition practice",
    "topics": [
        {"name": "Provenance & Acquisition", "weight": 20},
        {"name": "Preventive Conservation", "weight": 20},
        {"name": "Exhibition Interpretation", "weight": 18},
        {"name": "Cataloguing & Documentation", "weight": 15},
        {"name": "Public Engagement", "weight": 12},
        {"name": "Ownership & Collaboration", "weight": 15, "behavioural": True},
    ],
}


def _areas(pairs: list[tuple[str, int]]) -> list[dict]:
    """
    Areas for a schema test, with the LAST one marked behavioural.

    Every profile must declare exactly one, so a test about weights or names would otherwise
    fail on the behavioural rule and say nothing about the rule it was written for.
    """
    return [
        {"name": name, "weight": weight, "behavioural": i == len(pairs) - 1}
        for i, (name, weight) in enumerate(pairs)
    ]


def _profile(raw: dict) -> OpenDomain:
    """A generated profile, through the real validator, as `_generate` builds it."""
    validated = OpenDomainProfile(**raw)
    return OpenDomain(
        label=validated.label,
        lead_role=validated.lead_role,
        specialist_role=validated.specialist_role,
        is_technical=validated.is_technical,
        rating_subject=validated.rating_subject,
        topics=tuple((t.name, t.weight) for t in validated.topics),
        behavioural_area=next(t.name for t in validated.topics if t.behavioural),
    )


FIRMWARE = _profile(FIRMWARE_JSON)
CURATION = _profile(CURATION_JSON)

#: Subjects that must not appear in an interview for a field that is not computing. This is
#: the Asian Paints failure — a sales candidate briefed on "Programming Fundamentals, Data
#: Structures, DBMS & SQL, Version Control" — asserted for the open path.
COMPUTER_SCIENCE = (
    "programming fundamental",
    "data structure",
    "dbms",
    "sql",
    "java",
    "version control",
    "algorithm",
    "aptitude",
)


class TestThePremiseOfThisFile:
    """
    The catalogue's own answer about each stream, asserted rather than assumed.

    If `domains._KEYWORDS` grows an entry for firmware or curation, these fail and say so —
    which is the correct outcome. A curated family is better than a generated one, and the
    right response would be to move that stream to CURATED, not to keep testing an open path
    it no longer takes.
    """

    @pytest.mark.parametrize("stream,company", list(CURATED.values()), ids=list(CURATED))
    def test_a_curated_stream_is_recognised(self, stream: str, company: str):
        recognised = domains.matched(stream, "") or (
            syllabus_data.resolve(company, stream) is not None
        )
        assert recognised, f"{stream!r} is listed as curated but the catalogue does not name it"

    @pytest.mark.parametrize("stream", [OPEN_TECHNICAL, OPEN_NON_TECHNICAL])
    def test_an_open_stream_is_not_recognised(self, stream: str):
        assert not domains.matched(stream, "")
        assert open_domain.is_open(stream)

    def test_the_unmatched_default_is_the_thing_being_fixed(self):
        # Both of these are what today's code concludes about a sommelier, and they are why
        # the open path exists. Pinned so the fix cannot be mistaken for a no-op.
        assert domains.resolve(OPEN_NON_TECHNICAL, "") == "software"
        assert domains.matched(OPEN_NON_TECHNICAL, "") is False


class TestTheCatalogueWins:
    """
    RULE 1. A curated stream must be structurally unable to reach a generated profile.

    Asserted by counting generator invocations, because the failure this guards against is
    the one where the guard exists and does not fire — which reading the source cannot rule
    out and a call count can.
    """

    @pytest.fixture
    def never_generates(self, monkeypatch):
        calls: list[str] = []

        async def _boom(subject: str):
            calls.append(subject)
            raise AssertionError(
                f"the generator was invoked for {subject!r}, which the catalogue covers"
            )

        monkeypatch.setattr(open_domain, "_generate", _boom)
        return calls

    @pytest.mark.parametrize("stream,company", list(CURATED.values()), ids=list(CURATED))
    async def test_a_curated_stream_never_reaches_the_generator(
        self, stream: str, company: str, never_generates: list[str], monkeypatch
    ):
        monkeypatch.setattr(open_domain, "_read_cache", _never_cached)
        resolved = await open_domain.resolve(stream, program=stream, company=company)
        assert resolved is None
        assert never_generates == []

    async def test_a_company_and_program_with_an_authored_syllabus_short_circuits(
        self, never_generates: list[str], monkeypatch
    ):
        """
        The syllabus guard is separate from the keyword guard and needs its own test: a
        syllabus is resolved from (company, program) and can exist for a program whose title
        happens to match no keyword at all.
        """
        monkeypatch.setattr(open_domain, "_read_cache", _never_cached)
        assert syllabus_data.resolve("Cognizant", "Digital Nurture — Java FSE") is not None
        assert (
            await open_domain.resolve(
                "Digital Nurture — Java FSE",
                program="Digital Nurture — Java FSE",
                company="Cognizant",
            )
            is None
        )

    def test_the_curated_brief_is_byte_identical_with_and_without_the_new_parameter(self):
        """
        NO BLENDING, asserted at the only place the two paths meet. `_must_cover_block` grew
        an `open_profile` keyword; a curated call must produce exactly what it produced
        before, to the byte.
        """
        for stream, company in CURATED.values():
            assert _must_cover_block(stream, stream, company) == _must_cover_block(
                stream, stream, company, open_profile=None
            )


async def _never_cached(_key: str) -> None:
    """A cache that always misses, so a test measures the guard and not a warm Redis."""
    return None


def _no_plan_cache(monkeypatch) -> None:
    """
    Force `create_plan` to actually build a brief instead of reusing a stored plan.

    NOT TIDINESS — this file failed without it, on the third run and not the first. The plan
    variant cache lives in Postgres and is keyed by a SEMANTIC signature of
    (company, program, focus), so once a couple of runs of this test have registered
    "Firmware bring-up for RISC-V microcontrollers", the next run is served a stored plan,
    `generate_structured` is never called, and the assertion about what the planner was told
    fails with a KeyError about the test's own capture dict.

    That is a genuinely good behaviour of the product — the second candidate to ask for a
    field should not pay to plan it again — and a genuinely bad dependency for a test, because
    it makes the result a function of how many times the suite has been run before. What is
    under test here is the brief, so the cache is taken out of the picture rather than worked
    around with a unique company name, which would only move the accumulation somewhere else.
    """
    from app.services.ai import semantic_cache

    async def _miss(*_a, **_kw):
        return None

    async def _register(*_a, **_kw):
        return "test-signature-not-stored"

    monkeypatch.setattr(semantic_cache, "find_similar_key", _miss)
    monkeypatch.setattr(semantic_cache, "register", _register)


class TestTheSchemaIsNotRelaxedForBeingOpenDomain:
    """
    RULE 2. Free-form in SUBJECT is not free-form in SHAPE.

    Every case here is something a model actually does, and every one of them would reach the
    planner as a valid brief if this schema let it through.
    """

    def test_a_weighting_that_is_not_a_distribution_is_rejected(self):
        raw = dict(FIRMWARE_JSON)
        raw["topics"] = _areas([(f"Area {i}", 5) for i in range(6)])
        with pytest.raises(ValidationError, match="not a distribution"):
            OpenDomainProfile(**raw)

    def test_weights_that_nearly_sum_are_reallocated_to_exactly_a_hundred(self):
        """
        Rounding is fixed, not waived. A model asked for six integer percentages returns 97
        often enough that rejecting it would spend a retry on arithmetic.
        """
        raw = dict(FIRMWARE_JSON)
        raw["topics"] = _areas([(f"Area {i}", 16) for i in range(6)])
        assert sum(t.weight for t in OpenDomainProfile(**raw).topics) == 100

    @pytest.mark.parametrize(
        "name",
        [
            "What is a linker script",
            "Explain interrupt latency",
            "Describe the boot flow",
            "How would you debug a hard fault?",
            "Memory maps?",
        ],
    )
    def test_question_text_in_an_area_name_is_rejected(self, name: str):
        """
        The `syllabus.py` anti-hardcode contract, applied to model output. An area is the
        INPUT that decides what questions get written; a question there is output fed back in,
        and the same candidate would meet it in every sitting.
        """
        raw = dict(FIRMWARE_JSON)
        raw["topics"] = _areas([(name, 20)] + [(f"Area {i}", 20) for i in range(4)])
        with pytest.raises(ValidationError):
            OpenDomainProfile(**raw)

    def test_the_same_area_under_two_names_is_rejected(self):
        raw = dict(FIRMWARE_JSON)
        raw["topics"] = _areas(
            [("Drivers", 25), ("drivers", 25), ("Boot", 25), ("Ownership", 25)]
        )
        with pytest.raises(ValidationError, match="repeat"):
            OpenDomainProfile(**raw)

    @pytest.mark.parametrize("n", [3, 9])
    def test_too_few_and_too_many_areas_are_both_rejected(self, n: int):
        raw = dict(FIRMWARE_JSON)
        share = 100 // n
        weights = [(f"Area {i}", share) for i in range(n)]
        weights[0] = (weights[0][0], share + 100 - share * n)
        raw["topics"] = _areas(weights)
        with pytest.raises(ValidationError):
            OpenDomainProfile(**raw)

    def test_a_valid_profile_survives(self):
        # The counterweight. A schema that rejects everything passes every test above.
        for raw in (FIRMWARE_JSON, CURATION_JSON):
            assert sum(t.weight for t in OpenDomainProfile(**raw).topics) == 100


def _areas_section(must_cover: str) -> str:
    """
    The part of a must-cover block that says what to ASK ABOUT, lower-cased.

    The prohibition that follows it necessarily names the subjects it is prohibiting — "do not
    ask about programming, data structures, SQL" — so a naive scan of the whole block finds
    "data structures" in the sentence forbidding them. Splitting on the prohibition is what
    makes "no computer science reached this brief" a claim about the syllabus rather than
    about the wording of the ban.
    """
    head = must_cover.split("This is NOT a technical role.", 1)[0]
    return head.lower()


class TestTheBriefAnOpenStreamProduces:
    """RULE 3. A real weighting, and — for a non-technical field — no computer science."""

    def _brief(self, stream: str, profile: OpenDomain, **kw):
        return _plan_brief(
            track_name="",
            program=stream,
            company=kw.pop("company", "A company not on the catalogue"),
            focus=kw.pop("focus", ""),
            is_technical=profile.is_technical,
            question_count=12,
            open_profile=profile,
        )

    def test_the_technical_field_gets_its_own_areas_and_not_a_paragraph_of_prose(self):
        must_cover = self._brief(OPEN_TECHNICAL, FIRMWARE).must_cover
        for name, weight in FIRMWARE.topics:
            assert f"**{name}** — {weight}%" in must_cover
        # The sentence the unmatched branch used to emit instead of a weighting.
        assert "did not match a known domain" not in must_cover

    def test_the_non_technical_field_gets_no_computer_science_anywhere(self):
        """
        THE ASIAN PAINTS ASSERTION, for the open path. A museum conservator briefed on data
        structures is the same failure as a sales candidate briefed on version control.
        """
        areas = _areas_section(self._brief(OPEN_NON_TECHNICAL, CURATION).must_cover)
        for subject in COMPUTER_SCIENCE:
            assert subject not in areas, f"{subject!r} reached a curation brief"

    def test_the_non_technical_field_is_told_outright_it_is_not_technical(self):
        must_cover = self._brief(OPEN_NON_TECHNICAL, CURATION).must_cover
        assert "This is NOT a technical role." in must_cover

    def test_the_technical_field_is_not_told_that(self):
        assert "NOT a technical role" not in self._brief(OPEN_TECHNICAL, FIRMWARE).must_cover

    def test_no_other_fields_syllabus_is_imported_to_fill_the_interview_out(self):
        # The company weighting is deliberately withheld on this path — the catalogue's
        # weights describe an IT-services assessment and would put DSA back underneath a
        # correct brief. Asserted through a company that IS on the catalogue.
        must_cover = self._brief(OPEN_NON_TECHNICAL, CURATION, company="Cognizant").must_cover
        assert "do not import areas from any other field" in must_cover
        for subject in COMPUTER_SCIENCE:
            assert subject not in _areas_section(must_cover)

    def test_the_technical_field_is_shaped_as_a_technical_interview(self):
        brief = self._brief(OPEN_TECHNICAL, FIRMWARE)
        assert brief.kind is question_shape.InterviewKind.GENERAL_TECHNICAL
        assert brief.from_syllabus is False

    def test_the_non_technical_field_is_shaped_as_a_situational_one(self):
        brief = self._brief(OPEN_NON_TECHNICAL, CURATION)
        assert brief.kind is question_shape.InterviewKind.ROLE_SCENARIO
        counts = question_shape.allocation(brief.kind, 12)
        assert counts[question_shape.Register.CODE_ALOUD] == 0
        assert counts[question_shape.Register.SCENARIO] > counts[question_shape.Register.RECALL]

    def test_a_campus_program_in_an_open_technical_field_is_still_a_fundamentals_round(self):
        # `resolve_kind` reads the program text for a campus keyword. An open field does not
        # opt out of that — a graduate trainee scheme is a fresher round whatever it is in.
        brief = _plan_brief(
            track_name="",
            program=f"Graduate Engineer Trainee — {OPEN_TECHNICAL}",
            company="A company not on the catalogue",
            focus="",
            is_technical=True,
            question_count=12,
            open_profile=FIRMWARE,
        )
        assert brief.kind is question_shape.InterviewKind.CAMPUS_FUNDAMENTALS

    def test_the_focus_box_is_still_honoured_with_a_count(self):
        brief = self._brief(OPEN_NON_TECHNICAL, CURATION, focus="textile conservation")
        assert "textile conservation" in brief.focus_directive
        assert "must be on it" in brief.focus_directive

    @pytest.mark.parametrize("count", [4, 8, 12, 20, 25])
    def test_the_mix_is_still_stated_as_counts_for_every_interview_length(self, count: int):
        brief = _plan_brief(
            track_name="",
            program=OPEN_TECHNICAL,
            company="",
            focus="",
            is_technical=True,
            question_count=count,
            open_profile=FIRMWARE,
        )
        assert "these are counts rather than preferences" in brief.question_mix


class TestTheRestOfThePipelineIsUnmodified:
    """
    RULES 4 AND 5. The brief renders into the real template, and the plan that comes back is
    validated by exactly the same schema the curated path uses.
    """

    @pytest.mark.parametrize(
        "stream,profile", [(OPEN_TECHNICAL, FIRMWARE), (OPEN_NON_TECHNICAL, CURATION)]
    )
    def test_the_real_plan_template_renders_with_no_token_left_behind(
        self, stream: str, profile: OpenDomain
    ):
        """
        `safe_substitute` does not raise on a missing key — it ships the literal "$must_cover"
        to the model. So the only way this can fail loudly is a test that renders the real
        template with the real brief and looks for a surviving token.
        """
        import re

        from app.prompts.prompt_loader import get_prompt_loader
        from app.services.ai.prompt_builder import PromptBuilder
        from app.services.interview.orchestrator import _plan_user_brief

        brief = _plan_brief(
            track_name="",
            program=stream,
            company="An employer not on the catalogue",
            focus="",
            is_technical=profile.is_technical,
            question_count=12,
            open_profile=profile,
        )
        rendered = _plan_user_brief(
            company="An employer not on the catalogue",
            program=stream,
            focus="(no specific focus)",
            resume="(No resume on file)",
            business_context="",
            research="(no research on file)",
            already_asked="(first interview)",
            must_cover=brief.must_cover,
            question_mix=brief.question_mix,
            focus_directive=brief.focus_directive,
            question_count=12,
        )
        system, user = PromptBuilder(get_prompt_loader()).chat_static(
            system_template="interview_plan", user_content=rendered
        )
        leftovers = re.findall(r"\$[a-zA-Z_]\w*", system.content + user.content)
        assert not leftovers, f"unsubstituted tokens reached the model: {sorted(set(leftovers))}"
        assert profile.label in user.content

    def test_a_plan_for_an_open_field_goes_through_the_same_schema(self):
        """
        RULE 5. The open path is more free-form about what an interview can be ABOUT. It is
        not more permissive about what the model may return — the plan is the same
        `InterviewPlan`, validated the same way, or it is rejected.
        """
        plan = InterviewPlan(
            topics=[name for name, _ in CURATION.topics],
            questions=[
                {
                    "content": "Walk me through how you would rehouse a water-damaged textile.",
                    "topic_name": "Preventive Conservation",
                    "difficulty": "medium",
                    "question_type": "scenario",
                    "expected_keywords": ["stabilise", "humidity", "documentation"],
                    "ideal_answer": "Stabilise before moving; document condition first.",
                }
            ],
        )
        assert plan.questions[0].question_type == "scenario"

        with pytest.raises(ValidationError):
            InterviewPlan(
                topics=["Preventive Conservation"],
                questions=[{"content": "x", "difficulty": "trivial"}],
            )


class TestThePanelReadsTheResolvedField:
    """RULE 6. One resolver, five callers, and none of them falls back to software."""

    def _ctx(self, profile: OpenDomain, role: str) -> InterviewContext:
        return InterviewContext(
            company="An employer not on the catalogue",
            role=role,
            domain=domains.resolve(role, ""),
            is_technical=profile.is_technical,
            domain_matched=domains.matched(role, ""),
            open_domain=profile,
        )

    def test_the_profile_survives_a_round_trip_through_session_metadata(self):
        # JSONB gives back lists where the dataclass holds tuples. Asserted because the panel
        # reads this on every turn and a shape change would surface as a missing designation.
        for profile in (FIRMWARE, CURATION):
            assert OpenDomain.from_metadata(profile.to_metadata()) == profile

    @pytest.mark.parametrize("junk", [None, {}, {"label": "X"}, {"topics": []}, "nonsense", 7])
    def test_unreadable_metadata_is_no_open_domain_rather_than_an_exception(self, junk):
        # Every caller is mid-interview and none can handle an exception. A session written
        # before this feature existed has no key at all and must behave exactly as it did.
        assert OpenDomain.from_metadata(junk) is None

    def test_the_panel_is_designated_from_the_field(self):
        from app.api.v1.panel import panel_for

        roles = [i.role for i in panel_for(OPEN_NON_TECHNICAL, CURATION)]
        assert roles == [CURATION.lead_role, CURATION.specialist_role]
        assert not any("Engineering" in r for r in roles)

    def test_without_a_profile_the_panel_is_exactly_what_it_was(self):
        from app.api.v1.panel import panel_for

        assert [i.role for i in panel_for("Sales Executive")] == [
            i.role for i in panel_for("Sales Executive", None)
        ]

    def test_the_self_rating_subject_comes_from_the_field(self):
        from app.api.v1.panel import _rating_subject

        assert _rating_subject(self._ctx(CURATION, OPEN_NON_TECHNICAL)) == CURATION.rating_subject
        assert _rating_subject(self._ctx(FIRMWARE, OPEN_TECHNICAL)) == FIRMWARE.rating_subject

    def test_without_a_profile_the_rating_subject_is_exactly_what_it_was(self):
        from app.api.v1.panel import _rating_subject

        bare = InterviewContext(
            company="X",
            role=OPEN_NON_TECHNICAL,
            domain=domains.resolve(OPEN_NON_TECHNICAL, ""),
            is_technical=False,
            domain_matched=False,
            open_domain=None,
        )
        assert _rating_subject(bare) == "the core skills for this role"

    def test_the_pivot_offers_the_fields_own_areas_and_not_computer_science(self):
        """
        The pivot is the moment a candidate has just admitted a gap, so it is the worst
        moment to hand them a topic from another field. This branch used to offer
        "Programming fundamentals, DBMS & SQL, Data structures".
        """
        from app.api.v1.panel import _pivot_order_for

        offered = _pivot_order_for(self._ctx(CURATION, OPEN_NON_TECHNICAL))
        assert offered[0] == "Provenance & Acquisition"
        joined = " ".join(offered).lower()
        for subject in COMPUTER_SCIENCE:
            assert subject not in joined
        # The behavioural area is dropped — a pivot looks for ground in the subject — and it
        # is found by the model's own flag, not by its name containing "behavioural".
        assert CURATION.behavioural_area == "Ownership & Collaboration"
        assert CURATION.behavioural_area not in offered

    def test_a_technical_open_field_pivots_within_its_own_field_too(self):
        from app.api.v1.panel import _pivot_order_for

        offered = _pivot_order_for(self._ctx(FIRMWARE, OPEN_TECHNICAL))
        assert offered[0] == "Board Bring-Up & Boot Flow"
        assert "Programming fundamentals" not in offered

    def test_the_field_label_is_available_for_both_paths(self):
        assert self._ctx(CURATION, OPEN_NON_TECHNICAL).field_label == CURATION.label
        bare = InterviewContext(
            company="X",
            role="Sales Executive",
            domain="sales",
            is_technical=False,
            domain_matched=True,
        )
        assert bare.field_label == domains.PROFILES["sales"]["label"]


class TestTheCacheIsSharedByFieldAndCarriesNoPersonalText:
    async def test_a_second_candidate_for_the_same_field_does_not_pay_for_it_again(
        self, monkeypatch
    ):
        store: dict[str, OpenDomain] = {}
        calls: list[str] = []

        async def _read(key: str):
            return store.get(key)

        async def _write(key: str, profile: OpenDomain):
            store[key] = profile

        async def _generate(subject: str):
            calls.append(subject)
            return CURATION

        monkeypatch.setattr(open_domain, "_read_cache", _read)
        monkeypatch.setattr(open_domain, "_write_cache", _write)
        monkeypatch.setattr(open_domain, "_generate", _generate)

        first = await open_domain.resolve(OPEN_NON_TECHNICAL, program=OPEN_NON_TECHNICAL)
        # Different punctuation and case, same field. One entry, one call.
        second = await open_domain.resolve(
            "Museum Curation & Archival Conservation",
            program="Museum Curation & Archival Conservation",
        )
        assert first == second == CURATION
        assert len(calls) == 1

    async def test_the_focus_box_never_changes_the_shared_key(self, monkeypatch):
        """
        The focus box invites first-person text — "I struggle with...", "I interned at X" —
        and this cache is global. Keying on it would put one candidate's sentence where
        another candidate's lookup could reach it. Same leak `_is_personal_focus` stops for
        the plan cache.
        """
        calls: list[str] = []

        async def _generate(subject: str):
            calls.append(subject)
            return CURATION

        monkeypatch.setattr(open_domain, "_generate", _generate)
        monkeypatch.setattr(open_domain, "_read_cache", _never_cached)

        async def _write(_key: str, _profile: OpenDomain) -> None:
            return None

        monkeypatch.setattr(open_domain, "_write_cache", _write)

        await open_domain.resolve(
            OPEN_NON_TECHNICAL,
            program=OPEN_NON_TECHNICAL,
            focus="I interned at the National Museum and I struggle with textiles",
        )
        assert calls == [OPEN_NON_TECHNICAL], "the focus text reached the generator"
        assert open_domain._cache_key(OPEN_NON_TECHNICAL) == open_domain._cache_key(
            "museum curation and archival conservation"
        )


class TestFailingMeansFailingToTodaysBehaviour:
    """
    RULE 3 of the module header. An open-domain profile is an improvement on a bad default;
    it is never worth costing somebody the interview they paid for.
    """

    async def test_a_provider_outage_leaves_the_caller_with_todays_brief(self, monkeypatch):
        from app.core.exceptions import AIProviderUnavailableError

        async def _down(*_a, **_kw):
            raise AIProviderUnavailableError("both providers exhausted")

        monkeypatch.setattr(open_domain, "_read_cache", _never_cached)
        monkeypatch.setattr("app.services.ai.generate.generate_structured", _down)

        assert await open_domain.resolve(OPEN_TECHNICAL, program=OPEN_TECHNICAL) is None
        # And the brief with no profile is exactly the one that shipped before.
        brief = _plan_brief(
            track_name="",
            program=OPEN_TECHNICAL,
            company="",
            focus="",
            is_technical=True,
            question_count=12,
            open_profile=None,
        )
        assert "did not match a known domain" in brief.must_cover

    async def test_a_malformed_profile_is_a_miss_and_not_a_crash(self, monkeypatch):
        """
        `generate_structured` raises AIProviderUnavailableError once every attempt fails
        validation, so a model that will not produce a distribution reaches the caller as a
        miss. Asserted through the real validator rather than by stubbing the outcome.
        """
        from app.core.exceptions import AIProviderUnavailableError

        async def _garbage(*_a, **_kw):
            OpenDomainProfile(**{**FIRMWARE_JSON, "topics": _areas([("One", 1)])})
            raise AssertionError("unreachable — validation must have rejected that")

        async def _as_generate_structured_would(*a, **kw):
            try:
                await _garbage(*a, **kw)
            except ValidationError as exc:
                raise AIProviderUnavailableError("no valid result") from exc

        monkeypatch.setattr(open_domain, "_read_cache", _never_cached)
        monkeypatch.setattr(
            "app.services.ai.generate.generate_structured", _as_generate_structured_would
        )
        assert await open_domain.resolve(OPEN_TECHNICAL, program=OPEN_TECHNICAL) is None

    async def test_a_redis_that_is_down_costs_one_extra_call_and_nothing_else(
        self, monkeypatch
    ):
        calls: list[str] = []

        async def _generate(subject: str):
            calls.append(subject)
            return FIRMWARE

        def _explode(*_a, **_kw):
            raise RuntimeError("redis is not reachable")

        monkeypatch.setattr(open_domain, "_generate", _generate)
        monkeypatch.setattr("app.db.redis.get_redis", _explode)

        assert await open_domain.resolve(OPEN_TECHNICAL, program=OPEN_TECHNICAL) == FIRMWARE
        assert calls == [OPEN_TECHNICAL]


class TestEndToEndAgainstARealDatabase:
    """
    RULE 7. `create_plan` for an uncatalogued stream, all the way to persisted questions.

    Self-contained schema handling rather than reusing `test_integration.py`'s fixtures, for
    the reason `test_vector_cache_db.py` gives: those are session-scoped and autouse within
    their own module, and importing them here would either not apply or would drag the whole
    suite's schema lifecycle into this file.
    """

    @pytest.fixture
    async def db(self):
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        from app.db.session import AsyncSessionFactory, engine
        from app.models.base import Base

        try:
            async with engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await conn.run_sync(Base.metadata.create_all)
            async with AsyncSessionFactory() as session:
                yield session
                await session.rollback()
        except (SQLAlchemyError, OSError) as exc:
            pytest.skip(f"no Postgres for the end-to-end plan test: {type(exc).__name__} {exc}")

    @pytest.fixture
    async def candidate(self, db):
        """
        A real user row. `interview_sessions.user_id` is a foreign key, so a bare uuid4 is
        rejected by the database rather than by anything this test is about.
        """
        from app.models.user import Profile, User

        user_id = uuid.uuid4()
        db.add(
            User(
                id=user_id,
                supabase_uid=str(user_id),
                email=f"open-domain-{uuid.uuid4().hex[:8]}@example.com",
                is_active=True,
                is_admin=False,
            )
        )
        db.add(Profile(user_id=user_id, full_name="Test Candidate", timezone="UTC"))
        await db.flush()
        return user_id

    @pytest.fixture
    def carrier_track(self):
        """
        The track id the setup form must send whatever the candidate typed.

        `InterviewSession.track_id` is a non-null foreign key, so a custom setup arrives
        carrying an arbitrary catalogue track — which is exactly the shape of the Morani
        Plastics bug. Using one here is the point: the plan must come from the typed stream
        and not from this.
        """
        from app.models.company import Company, InterviewTrack

        company = Company(
            id=uuid.uuid4(), name="Carrier Co", slug=f"carrier-{uuid.uuid4().hex[:8]}"
        )
        track = InterviewTrack(
            id=uuid.uuid4(),
            company_id=company.id,
            name="Advanced ASE",
            slug=f"advanced-ase-{uuid.uuid4().hex[:8]}",
        )
        return company, track

    @pytest.mark.parametrize(
        "stream,profile",
        [(OPEN_TECHNICAL, FIRMWARE), (OPEN_NON_TECHNICAL, CURATION)],
        ids=["technical", "non_technical"],
    )
    async def test_an_uncatalogued_stream_produces_a_full_plan_and_pins_its_field(
        self, db, candidate, carrier_track, monkeypatch, stream: str, profile: OpenDomain
    ):
        from app.models.session import InterviewSession
        from app.services.interview import orchestrator as orch
        from app.services.interview.orchestrator import InterviewOrchestrator

        company, track = carrier_track
        db.add(company)
        db.add(track)
        await db.flush()

        # The two model calls, stubbed at their own import sites so each can be asserted
        # separately: the profile call and the plan call are genuinely different decisions.
        async def _profile_call(subject: str):
            assert subject == stream
            return profile

        captured: dict[str, str] = {}

        async def _plan_call(_schema, messages, **_kw):
            captured["brief"] = messages[-1].content
            return (
                InterviewPlan(
                    topics=[name for name, _ in profile.topics],
                    questions=[
                        {
                            "content": f"Question {i} for this role, in its own field.",
                            "topic_name": profile.topics[i % len(profile.topics)][0],
                            "difficulty": "medium",
                            "question_type": "scenario",
                            "expected_keywords": ["judgement"],
                            "ideal_answer": "A defensible answer.",
                        }
                        for i in range(orch._PLANNED_QUESTION_COUNT)
                    ],
                ),
                "{}",
            )

        monkeypatch.setattr(open_domain, "_generate", _profile_call)
        monkeypatch.setattr(open_domain, "_read_cache", _never_cached)

        async def _no_write(_key, _profile):
            return None

        monkeypatch.setattr(open_domain, "_write_cache", _no_write)
        monkeypatch.setattr(orch, "generate_structured", _plan_call)
        _no_plan_cache(monkeypatch)

        result = await InterviewOrchestrator(db).create_plan(
            user_id=candidate,
            track_id=track.id,
            company="An employer not on the catalogue",
            program=stream,
            focus="",
            custom_setup=True,
        )

        assert result["question_count"] == orch._PLANNED_QUESTION_COUNT

        session = await db.get(InterviewSession, result["session_id"])
        meta = session.session_metadata
        # PINNED, so the panel reads the same field on every turn.
        assert OpenDomain.from_metadata(meta["open_domain"]) == profile
        # And the code editor follows the field rather than the "unmatched means technical"
        # default that would have put one in front of a conservator.
        assert meta["is_technical"] is profile.is_technical

        # The brief the planner actually received names this field and, when the field is not
        # a computing one, no computer science at all.
        assert profile.label in captured["brief"]

        # The AREAS the planner was told to cover, as bullets. Scanned rather than the whole
        # brief because the prohibition necessarily names the subjects it forbids — "do not
        # ask about programming, data structures, SQL" — so a whole-brief scan finds them in
        # the sentence banning them and proves nothing.
        bullets = " ".join(
            line for line in captured["brief"].splitlines() if line.startswith("- **")
        ).lower()
        for name, _weight in profile.topics:
            assert name.lower() in bullets
        if not profile.is_technical:
            assert "This is NOT a technical role." in captured["brief"]
            for subject in COMPUTER_SCIENCE:
                assert subject not in bullets, f"{subject!r} was planned into this interview"

    async def test_a_curated_stream_end_to_end_still_never_generates_a_profile(
        self, db, candidate, carrier_track, monkeypatch
    ):
        """
        The control. Same path, same stubs, a stream the catalogue names — and the profile
        generator must not be reached at all.
        """
        from app.models.session import InterviewSession
        from app.services.interview import orchestrator as orch
        from app.services.interview.orchestrator import InterviewOrchestrator

        company, track = carrier_track
        db.add(company)
        db.add(track)
        await db.flush()

        async def _boom(subject: str):
            raise AssertionError(f"generated a profile for the curated stream {subject!r}")

        async def _plan_call(_schema, messages, **_kw):
            return (
                InterviewPlan(
                    topics=["Core Java"],
                    questions=[
                        {
                            "content": f"Java question {i}.",
                            "topic_name": "Core Java",
                            "difficulty": "medium",
                            "question_type": "conceptual",
                            "expected_keywords": ["jvm"],
                            "ideal_answer": "An answer.",
                        }
                        for i in range(orch._PLANNED_QUESTION_COUNT)
                    ],
                ),
                "{}",
            )

        monkeypatch.setattr(open_domain, "_generate", _boom)
        monkeypatch.setattr(open_domain, "_read_cache", _never_cached)
        monkeypatch.setattr(orch, "generate_structured", _plan_call)
        _no_plan_cache(monkeypatch)

        result = await InterviewOrchestrator(db).create_plan(
            user_id=candidate,
            track_id=track.id,
            company="Cognizant",
            program="Digital Nurture — Java FSE",
            focus="",
            custom_setup=True,
        )
        session = await db.get(InterviewSession, result["session_id"])
        assert session.session_metadata["open_domain"] is None

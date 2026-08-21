"""
The syllabus, and the promise that it never becomes a question bank —
tests/test_syllabus.py

WHAT WAS REPORTED. A candidate sat a Cognizant Digital Nurture 5.0 Java FSE mock
in preparation for the real technical interview and reported three things: it was
"mostly covering the scenario based questions only"; it was "not looking at what i
have filled in the blocks for additional topics"; and it did not cover the round
they are actually sitting — Java and OOP, React, SQL, Spring Boot and REST, basic
coding aloud, the project, HR. They were also explicit about the fix they did NOT
want: "do not copy past or harcode anything ... i want questions LIKE these ...
and do not ask dsame questions again and again."

So `app/data/syllabus.py` encodes what the interview COVERS and never what it
ASKS, and this file pins both halves of that sentence.

WHAT IS PINNED HERE, and why each of these is a test rather than a code comment:

  · **No canned questions, enforced from inside the repo.** No authored string in
    the syllabus may share a five-word content phrase with any question in
    `java_fundamentals`, any `domains.PROFILES` scenario, or the quiz banks. This
    is the one anti-hardcode rule that cannot live in `syllabus._validate`,
    because it needs the other banks imported and `syllabus` must not import
    them. It is deliberately tolerant of shared VOCABULARY — "overriding a static
    method" is three content words, forms no five-gram, and *should* be shared.
    The syllabus and the bank are allowed to name the same concept and forbidden
    from sharing a sentence. It also closes the specific hole this change opened
    by deleting `knowledge/interview_patterns/cognizant_java_fse.md`, whose
    "Commonly Asked Questions (must ask every session)" lists were exactly the
    material at risk of being pasted back in.
  · **The schema key freeze.** `Area` and `Syllabus` are asserted to have exactly
    the keys they have today. The primary anti-hardcode mechanism is that there is
    NOWHERE to put a question — no `content`, `question`, `text`, `example` or
    `prompt` field — and a mechanism whose whole strength is an absence needs
    something that fails when the absence ends. With this test, the diff that adds
    a `content:` field has to also edit the test that forbids it, in front of a
    reviewer.
  · **The mix is arithmetic, not rhetoric.** `interview_plan.md` used to say, in
    bold capitals, "MOST QUESTIONS MUST BE SCENARIO-BASED. At least two thirds of
    them" — unconditionally, for every role — and the model obeyed it over every
    softer instruction in the file, because it was the only QUANTIFIED one. The
    replacement is `plan_grid` handing the prompt N-1 numbered rows with a fixed
    subject and form each. These tests check the rows against the allocation at
    every question count the setting allows (4–25), because a mix that says one
    thing while the grid does another is the reported bug wearing a new hat.
  · **The typed focus buys an integer number of questions.** Not a courteous
    clause in a prompt. `reserved={area: slots}` must produce exactly that many
    rows on that area, and must never take them out of the introduction, the
    project rows or the HR row — which is what makes the free-text box additive to
    the interview rather than carved out of the parts that make it one.
  · **Resolution never widens across a program.** `resolve("cognizant", "genc")`
    is `None`. This is the direct counter-example to `research_lookup`'s
    `or rows[0]`, which hands a Java FSE candidate GenC Next's DSA research over
    an unordered SELECT and then tells the prompt to trust it as the primary
    source of truth. Wrong data wearing a confident label is worse than no data.

Everything here is pure — no database, no Redis, no AI provider. The syllabus is
authored data plus integer arithmetic, and if any test in this file ever needs a
fixture, something has grown an I/O dependency it should not have.
"""

from __future__ import annotations

import copy
import math
import re

import pytest

from app.data import domains, syllabus
from app.data.java_fundamentals import ALL_TOPICS, JAVA_QUESTION_BANK
from app.data.question_shape import (
    PERSONAL_REGISTERS,
    SHAPE_MIX,
    SUBJECT_REGISTERS,
    InterviewKind,
    Register,
    allocate,
    mix_total,
)
from app.data.quiz_bank import QUIZ_BANK
from app.services.prep.catalogue import load_catalogue

#: Every question count the setting allows. `INTERVIEW_QUESTION_COUNT` is a
#: pydantic field with ge=4, le=25, and the whole grid is derived from it — so the
#: interesting failures are at the ends, not at the default twelve. The
#: code-aloud starvation bug that `_area_budget`'s third pass exists to fix was
#: invisible at twelve and real at five.
COUNTS = tuple(range(4, 26))

#: The one authored syllabus, fetched the way a caller fetches it rather than
#: reached for as a private global — a test that imported `_COGNIZANT_DN_JAVA_FSE`
#: directly would keep passing after `resolve` stopped finding it.
COGNIZANT = syllabus.resolve("Cognizant", "Digital Nurture — Java FSE")


def test_the_cognizant_syllabus_resolves_at_all() -> None:
    """Guard for every test below, which would otherwise fail as a TypeError."""
    assert COGNIZANT is not None
    assert COGNIZANT["company"] == "cognizant"
    assert COGNIZANT["program"] == "digital-nurture-java-fse"


# ─── The anti-hardcode contract ───────────────────────────────────────────────

#: Dropped before shingling. Function words only: an aggressive list would make
#: two different sentences look like the same phrase and turn this test into a
#: source of false failures, which is how a test gets deleted instead of fixed.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "of", "on", "in", "to", "is", "are", "was", "were",
        "be", "been", "being", "am", "and", "or", "but", "if", "then", "than",
        "that", "this", "these", "those", "with", "without", "for", "from",
        "by", "as", "at", "it", "its", "into", "over", "under", "about", "not",
        "no", "do", "does", "did", "can", "could", "will", "would", "should",
        "shall", "have", "has", "had", "you", "your", "yours", "i", "we",
        "they", "he", "she", "them", "what", "which", "who", "whom", "how",
        "why", "when", "where", "there", "here", "also", "very", "more",
        "most", "much", "many", "any", "some", "all", "both", "each",
    }
)


def _content_words(text: str) -> list[str]:
    return [
        word
        for word in re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
        if word and word not in _STOPWORDS
    ]


def _shingles(text: str, size: int = 5) -> set[str]:
    words = _content_words(text)
    return {" ".join(words[index : index + size]) for index in range(len(words) - size + 1)}


def _authored_strings() -> list[tuple[str, str]]:
    """(where, text) for every string a human typed into the syllabus module."""
    out: list[tuple[str, str]] = []
    for entry in syllabus.SYLLABI:
        label = f"{entry['company']}/{entry['program']}"
        for area in entry["areas"]:
            for subtopic in area["subtopics"]:
                out.append((f"{label} {area['name']} subtopic", subtopic))
            for theme in area["cross_themes"]:
                out.append((f"{label} {area['name']} cross_theme", theme))
        for shape in entry["code_shapes"]:
            out.append((f"{label} code_shape", shape))
        for probe in entry["project_probes"]:
            out.append((f"{label} project_probe", probe))
        for theme in entry["hr_themes"]:
            out.append((f"{label} hr_theme", theme))
    return out


def _bank_shingles() -> set[str]:
    """Every five-word phrase that appears in a question anywhere in the repo."""
    out: set[str] = set()
    for question in JAVA_QUESTION_BANK:
        out |= _shingles(question["content"])
        out |= _shingles(question["ideal"])
    for profile in domains.PROFILES.values():
        for scenario in profile["scenarios"]:
            out |= _shingles(scenario["content"])
            out |= _shingles(scenario["ideal"])
    for questions in QUIZ_BANK.values():
        for question in questions:
            out |= _shingles(str(question["question"]))
            out |= _shingles(str(question.get("explanation", "")))
    return out


def test_no_authored_string_shares_a_five_word_phrase_with_any_question_bank() -> None:
    """
    The rule that makes smuggling a canned question in from INSIDE the repo
    structurally impossible.

    The banks are the nearest source of ready-made interview sentences — 37 Java
    questions with `content` and `ideal`, eleven domains' worth of scenarios, and
    the quiz banks — and the deleted `interview_patterns/cognizant_java_fse.md`
    was a second one. If a descriptor ever shares five consecutive content words
    with any of them, somebody pasted rather than described.
    """
    banned = _bank_shingles()
    assert banned, "the banks produced no shingles at all — this test is not testing anything"

    offenders = [
        (where, text, sorted(_shingles(text) & banned))
        for where, text in _authored_strings()
        if _shingles(text) & banned
    ]
    assert not offenders, (
        "syllabus strings share a five-word phrase with a question bank, which means "
        f"question text was pasted into the syllabus: {offenders}"
    )


def test_the_area_schema_has_nowhere_to_put_a_question() -> None:
    """
    Frozen key set. The primary anti-hardcode mechanism is an ABSENCE — no field
    on which "Can you override a static method?" can be hung — and an absence
    needs a test that fails when it ends. Adding a field here is fine; adding one
    without editing this list is not.
    """
    assert set(syllabus.Area.__annotations__) == {
        "name",
        "weight",
        "depth",
        "registers",
        "subtopics",
        "cross_themes",
        "bank_topics",
    }


def test_the_syllabus_schema_has_nowhere_to_put_a_question() -> None:
    """As above, for the outer record."""
    assert set(syllabus.Syllabus.__annotations__) == {
        "company",
        "program",
        "label",
        "kind",
        "shape_mix",
        "areas",
        "code_shapes",
        "project_probes",
        "hr_themes",
        "sourced",
        "verified",
    }


def test_no_schema_field_is_named_like_question_text() -> None:
    """
    The rule behind the two key freezes above, stated as itself so that a NEW
    TypedDict in this module inherits it without anybody remembering to extend a
    literal list.
    """
    forbidden = {"content", "question", "questions", "text", "example", "examples", "prompt"}
    for name in ("Area", "Syllabus"):
        keys = set(getattr(syllabus, name).__annotations__)
        assert not keys & forbidden, (
            f"{name} has a field that invites question text: {sorted(keys & forbidden)}. "
            "Descriptors steer generation; questions are generated. Put it nowhere."
        )


@pytest.mark.parametrize(
    "text",
    [
        # The two the candidate named as the shape they want ASKED — and therefore
        # exactly the two most likely to be pasted in here as "examples".
        "Can you override a static method?",
        "Can we overload a method by changing only the return type?",
        # From the deleted interview_patterns file's "must ask every session" list.
        "Write a SQL query to find the second highest salary",
        "Explain the difference between abstract class and interface",
        "How does Spring Boot auto-configuration work?",
        # The de-punctuated sneak: mark stripped, shortened, still an instruction.
        "explain abstract class and interface",
        "list the four pillars",
        # Second person, which is what makes a phrase a question to somebody.
        "the difference you must explain",
    ],
)
def test_the_import_guard_rejects_a_question_dressed_as_a_descriptor(text: str) -> None:
    """
    `_check_phrase` runs over every authored string at import. This pins that it
    actually rejects the material at risk, rather than merely that today's data
    happens to be clean.

    Honest about its limit: the guard cannot tell a five-word noun phrase from a
    five-word question with its interrogative opener removed, and it is not meant
    to. It is defence in depth. The load-bearing rule is that the schema has no
    field to put a question in, which the three tests above pin.
    """
    with pytest.raises(ValueError):
        syllabus._check_phrase(text, where="test", cap=syllabus._DESCRIPTOR_WORDS)


def _bad_syllabus(**overrides: object) -> syllabus.Syllabus:
    """A deep copy of the real syllabus with one thing broken, for guard tests."""
    entry = copy.deepcopy(dict(COGNIZANT))
    entry.update(overrides)
    return entry  # type: ignore[return-value]


def test_the_import_validator_raises_on_a_question_in_the_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    An import-time raise, not a warning, following `domains.py`'s sum-to-100
    check. A syllabus carrying question text renders perfectly and is briefed
    wrongly, and nobody reads the logs of something that appears to work.
    """
    areas = copy.deepcopy(list(COGNIZANT["areas"]))
    areas[0]["subtopics"] = (*areas[0]["subtopics"], "What is the difference between X and Y?")
    monkeypatch.setattr(syllabus, "SYLLABI", (_bad_syllabus(areas=tuple(areas)),))
    with pytest.raises(ValueError, match="question mark"):
        syllabus._validate()


def test_the_import_validator_raises_on_weights_that_do_not_sum_to_100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A set summing to 90 does not fail — it silently under-plans every interview,
    for months, from a typo. Same reason `catalogue.load_catalogue` and
    `domains` both check their own distributions.
    """
    areas = copy.deepcopy(list(COGNIZANT["areas"]))
    areas[0]["weight"] = 5
    monkeypatch.setattr(syllabus, "SYLLABI", (_bad_syllabus(areas=tuple(areas)),))
    with pytest.raises(ValueError, match="area weights sum to"):
        syllabus._validate()


def test_the_import_validator_raises_on_a_bank_topic_that_no_longer_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    `Area.bank_topics` is a CLAIM about offline coverage that `bank_gaps` reads
    and the fallback planner acts on. Renaming a topic in `java_fundamentals` must
    break the build here, not quietly turn the claim into a lie.
    """
    areas = copy.deepcopy(list(COGNIZANT["areas"]))
    areas[0]["bank_topics"] = ("Topic That Was Renamed",)
    monkeypatch.setattr(syllabus, "SYLLABI", (_bad_syllabus(areas=tuple(areas)),))
    with pytest.raises(ValueError, match="ALL_TOPICS"):
        syllabus._validate()


def test_the_import_validator_raises_on_a_cross_row_with_nothing_to_trap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A cross-question needs a rule underneath it to trap. An area declaring CROSS
    with no themes produces a row the model cannot write, which is how "cross
    questions" quietly become more recall questions.
    """
    areas = copy.deepcopy(list(COGNIZANT["areas"]))
    for area in areas:
        if Register.CROSS in area["registers"]:
            area["cross_themes"] = ()
            break
    monkeypatch.setattr(syllabus, "SYLLABI", (_bad_syllabus(areas=tuple(areas)),))
    with pytest.raises(ValueError, match="no cross_themes"):
        syllabus._validate()


def test_the_import_validator_raises_on_a_personal_register_in_an_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    PROJECT and BEHAVIOURAL are about the CANDIDATE. An area that claimed one
    would let the planner steer "tell me about your project" onto SQL, which is
    the category error the two-axis design exists to make impossible.
    """
    areas = copy.deepcopy(list(COGNIZANT["areas"]))
    areas[0]["registers"] = (*areas[0]["registers"], Register.PROJECT)
    monkeypatch.setattr(syllabus, "SYLLABI", (_bad_syllabus(areas=tuple(areas)),))
    with pytest.raises(ValueError, match="not a subject register"):
        syllabus._validate()


def test_the_import_validator_raises_on_a_code_shape_with_a_concrete_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shape with an input baked in is a canned question with extra steps."""
    monkeypatch.setattr(
        syllabus,
        "SYLLABI",
        (_bad_syllabus(code_shapes=("a single pass over the array 1024 wide",)),),
    )
    with pytest.raises(ValueError, match="concrete input"):
        syllabus._validate()


def test_no_cross_theme_is_a_restatement_of_a_subtopic() -> None:
    """
    A theme states what goes WRONG; a subtopic names the concept. An identical
    string means the field was filled to satisfy the schema rather than because
    somebody knew a trap — and a "trap" that is just the topic again produces a
    cross-question indistinguishable from a recall question.
    """
    for entry in syllabus.SYLLABI:
        for area in entry["areas"]:
            overlap = set(area["cross_themes"]) & set(area["subtopics"])
            assert not overlap, f"{area['name']}: theme repeats a subtopic: {sorted(overlap)}"


def test_the_briefs_the_model_receives_contain_no_question_at_all() -> None:
    """
    The rendered `$must_cover` block is what the model actually reads. The old
    renderer emitted `- **{topic}** — e.g. {contents[0]}`, i.e. a real interview
    question as an example, under a heading reading "questions actually asked in
    past interviews" — which is how verbatim reuse got licensed in the first
    place. Nothing this renderer produces may be reusable as a question.
    """
    assert COGNIZANT is not None
    for count in COUNTS:
        text = syllabus.render(COGNIZANT, syllabus.plan_grid(COGNIZANT, count))
        assert "?" not in text, f"the brief at N={count} contains a question mark"
        assert '"' not in text and "e.g." not in text


# ─── The mix is arithmetic ────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", list(InterviewKind))
def test_every_shape_mix_sums_to_100(kind: InterviewKind) -> None:
    """Checked at import too. Pinned here so the failure names the kind."""
    assert mix_total(SHAPE_MIX[kind]) == 100


@pytest.mark.parametrize("kind", list(InterviewKind))
@pytest.mark.parametrize("count", COUNTS)
def test_allocate_spends_every_question_except_the_introduction(
    kind: InterviewKind, count: int
) -> None:
    """
    Largest remainder, so the counts sum EXACTLY to `count - 1`. The minus one is
    question 1, the mandated introduction, which belongs to no register. A mix
    that summed to less would silently produce a short interview, which is the
    "it said 20 questions and asked me 8" bug this repo already has a test file
    for.
    """
    counts = allocate(SHAPE_MIX[kind], count)
    assert sum(counts.values()) == count - 1
    assert all(value >= 0 for value in counts.values())


@pytest.mark.parametrize("count", COUNTS)
def test_the_grid_is_exactly_one_row_short_of_the_question_count(count: int) -> None:
    """Every number in the grid derives from the caller's `question_count`."""
    assert COGNIZANT is not None
    grid = syllabus.plan_grid(COGNIZANT, count)
    assert len(grid) == count - 1
    assert [slot.position for slot in grid] == list(range(1, count))


@pytest.mark.parametrize("count", COUNTS)
def test_the_placed_rows_match_the_allocation_exactly(count: int) -> None:
    """
    THE REGRESSION PIN FOR THE REPORTED BUG, at every question count.

    The mix is the whole fix: six of eleven rows fundamentals asked directly or
    cross-questioned, against ONE scenario, where the prompt used to demand two
    thirds scenario. A grid that quietly traded one register for another would be
    that same bug — a mix saying one thing and an interview doing another —
    arriving through the back door.

    It has already happened once. At sixteen questions, Coding Fundamentals holds
    two budgeted slots and accepts only CODE_ALOUD; spreading the two code-aloud
    rows across Coding Fundamentals and SQL left Coding Fundamentals with a slot
    it could fill only with CODE_ALOUD, so the interview came out with three
    code-aloud rows and one cross-question fewer than the mix demanded. Hence
    `_place_registers` preferring areas that can carry nothing else, and hence
    this test running over the whole 4–25 range rather than the default alone.
    """
    assert COGNIZANT is not None
    demanded = allocate(syllabus.mix_for(COGNIZANT), count)
    placed: dict[str, int] = {}
    for slot in syllabus.plan_grid(COGNIZANT, count):
        placed[slot.register.value] = placed.get(slot.register.value, 0) + 1
    assert placed == {key: value for key, value in demanded.items() if value}


@pytest.mark.parametrize("count", COUNTS)
def test_no_row_asks_a_form_its_subject_cannot_carry(count: int) -> None:
    """
    `Area.registers` is a RULE, not a value. A CROSS row on an area with no traps
    or a code-aloud row on OOP is a question the model cannot write, and what it
    writes instead is whatever it feels like — which is where "mostly scenario"
    came from.
    """
    assert COGNIZANT is not None
    areas = {area["name"]: area for area in COGNIZANT["areas"]}
    for slot in syllabus.plan_grid(COGNIZANT, count):
        if slot.area is None:
            continue
        assert slot.register in areas[slot.area]["registers"], (
            f"row {slot.position}: {slot.area} cannot carry {slot.register}"
        )


@pytest.mark.parametrize("count", COUNTS)
def test_personal_rows_carry_no_area_and_subject_rows_always_do(count: int) -> None:
    """
    The two-axis split, pinned. PROJECT and BEHAVIOURAL are about the candidate,
    so steering them onto a syllabus topic is a category error; every other row
    must name its subject or the model chooses one.
    """
    assert COGNIZANT is not None
    for slot in syllabus.plan_grid(COGNIZANT, count):
        if slot.register in PERSONAL_REGISTERS:
            assert slot.area is None and slot.subtopic is None and slot.theme is None
            assert slot.reason == "mandated"
        else:
            assert slot.register in SUBJECT_REGISTERS
            assert slot.area is not None
            assert slot.subtopic is not None


@pytest.mark.parametrize("count", COUNTS)
def test_every_cross_row_carries_the_trap_it_is_meant_to_test(count: int) -> None:
    """A cross-question with no theme is a recall question with a longer label."""
    assert COGNIZANT is not None
    for slot in syllabus.plan_grid(COGNIZANT, count):
        if slot.register is Register.CROSS:
            assert slot.theme, f"row {slot.position} is a cross-question with nothing to trap"


def test_a_campus_interview_is_a_viva_and_not_a_run_of_scenarios() -> None:
    """
    The numeric answer to report (1), at the default question count.

    `interview_plan.md` demanded at least two thirds scenario. A Cognizant campus
    round is the other way round, and this is that inversion as an assertion
    rather than an adjective: fundamentals asked directly or cross-questioned must
    outnumber situations several times over.
    """
    assert COGNIZANT is not None
    counts = allocate(syllabus.mix_for(COGNIZANT), 12)
    fundamentals = counts["recall"] + counts["cross"]
    assert counts["scenario"] == 1
    assert fundamentals >= 5 * counts["scenario"]
    assert syllabus.kind_for(COGNIZANT) is InterviewKind.CAMPUS_FUNDAMENTALS


def test_a_domain_role_keeps_its_scenario_majority() -> None:
    """
    The risk this change had to avoid. `domains.py`'s entire seed design is
    situational — a sales interview asked in definitions is the bug that file was
    written to fix, and `test_role_scoping.py` pins it. Removing the scenario
    mandate from the prompt must therefore not remove it from the roles it was
    correct for.
    """
    counts = allocate(SHAPE_MIX[InterviewKind.ROLE_SCENARIO], 12)
    assert counts["scenario"] > sum(
        counts[key] for key in ("recall", "cross", "coding_aloud")
    )
    assert counts["cross"] == 0, "a domain profile has topics, not rules to trap"


def test_the_grid_is_deterministic() -> None:
    """
    Identical inputs, identical grid. The variation a candidate should see comes
    from `covered` growing and from the model's wording — not from a shuffle,
    which would make every test in this file probabilistic and every bug report
    unreproducible.
    """
    assert COGNIZANT is not None
    first = syllabus.plan_grid(COGNIZANT, 12, reserved={"React & Frontend": 3})
    second = syllabus.plan_grid(COGNIZANT, 12, reserved={"React & Frontend": 3})
    assert first == second


# ─── The typed focus ─────────────────────────────────────────────────────────


def _focus_slots(count: int) -> int:
    """
    The focus allocator's fraction, restated here rather than imported.

    Three of twelve, and three is a ceiling rather than a fraction rounded up:
    the introduction, the project rows and the HR row already claim four of
    twelve, and a fourth focus slot would leave the must-cover core with four
    subject rows, which hollows out the thing the candidate came for.
    """
    return min(max(2, math.ceil(count / 4)), 3)


@pytest.mark.parametrize("count", COUNTS)
@pytest.mark.parametrize(
    "area", ["React & Frontend", "SQL & Data Modelling", "Core Java", "Coding Fundamentals"]
)
def test_the_typed_focus_buys_exactly_the_rows_it_reserved(count: int, area: str) -> None:
    """
    Report (2), as arithmetic. The candidate typed topics into "Anything
    specific?" and nothing changed, because the prompt gave the box one courteous
    clause against "draw the majority of your questions from this list" and "stay
    inside it". A clause loses to a list; an integer does not.

    At low question counts the ask is clamped to the subject rows that exist —
    honestly, and reported as what was actually granted, because a review screen
    that claimed three focus questions in a four-question interview would be
    lying to the candidate about the same box twice.
    """
    assert COGNIZANT is not None
    wanted = _focus_slots(count)
    grid = syllabus.plan_grid(COGNIZANT, count, reserved={area: wanted})
    subject_rows = sum(
        allocate(syllabus.mix_for(COGNIZANT), count)[register.value]
        for register in SUBJECT_REGISTERS
    )
    focused = [slot for slot in grid if slot.reason == "focus"]
    assert len(focused) == min(wanted, subject_rows)
    assert all(slot.area == area for slot in focused)


@pytest.mark.parametrize("count", COUNTS)
def test_a_focus_row_never_comes_out_of_the_intro_the_project_or_hr(count: int) -> None:
    """
    The guarantee that makes the focus ADDITIVE rather than carved out of the
    parts that make this an interview. Reserved rows are taken from the
    lowest-weighted AREAS, and the personal registers are on the other axis
    entirely, so no arithmetic in `_area_budget` can reach them.
    """
    assert COGNIZANT is not None
    demanded = allocate(syllabus.mix_for(COGNIZANT), count)
    grid = syllabus.plan_grid(
        COGNIZANT, count, reserved={"React & Frontend": _focus_slots(count)}
    )
    for register in PERSONAL_REGISTERS:
        assert sum(1 for slot in grid if slot.register is register) == demanded[register.value]
    assert all(slot.reason == "mandated" for slot in grid if slot.register in PERSONAL_REGISTERS)
    assert len(grid) == count - 1


def test_an_unknown_reserved_area_is_ignored_rather_than_crashing() -> None:
    """
    `reserved` keys come from free text the candidate typed. A term the allocator
    could not place must produce no reservation — the caller then passes it
    through as a note about the candidate — and must never take the interview
    down, because the input is a sentence, not a configuration.
    """
    assert COGNIZANT is not None
    grid = syllabus.plan_grid(COGNIZANT, 12, reserved={"Kubernetes": 3, "": 2})
    assert len(grid) == 11
    assert not [slot for slot in grid if slot.reason == "focus"]


@pytest.mark.parametrize(
    ("term", "area"),
    [
        ("reactjs", "React & Frontend"),
        ("react", "React & Frontend"),
        ("hooks", "React & Frontend"),
        ("useEffect cleanup", "React & Frontend"),
        ("oops", "OOP & Class Design"),
        ("overriding", "OOP & Class Design"),
        ("sql", "SQL & Data Modelling"),
        ("sql joins", "SQL & Data Modelling"),
        ("normalisation", "SQL & Data Modelling"),
        ("dbms", "SQL & Data Modelling"),
        ("spring boot", "Spring Boot & REST"),
        ("springboot", "Spring Boot & REST"),
        ("rest api", "Spring Boot & REST"),
        ("multithreading", "Core Java"),
        ("collections", "Core Java"),
        ("recursion", "Coding Fundamentals"),
        ("revise my sql joins please", "SQL & Data Modelling"),
    ],
)
def test_the_words_candidates_actually_type_land_on_an_area(term: str, area: str) -> None:
    """
    The vocabulary gap is the practical half of report (2). "hooks", "oops",
    "joins", "springboot" and "multithreading" are what candidates type, and none
    of them appears verbatim in an area name — so a match on area names alone
    finds nothing and the box looks ignored even once the prompt is fixed.
    """
    assert COGNIZANT is not None
    hit = syllabus.match_focus(COGNIZANT, term)
    assert hit is not None, f"{term!r} matched nothing"
    assert hit.area == area
    if hit.subtopic is not None:
        area_entry = next(a for a in COGNIZANT["areas"] if a["name"] == hit.area)
        assert hit.subtopic in area_entry["subtopics"]


@pytest.mark.parametrize(
    "term",
    [
        "go easy on me",
        "i am nervous",
        "please",
        "",
        "   ",
        "kubernetes",
        "channel sales targets",
    ],
)
def test_an_off_syllabus_term_matches_nothing_rather_than_something_close(term: str) -> None:
    """
    A miss must be a miss. `match_focus` returning the nearest area for "go easy
    on me" would spend a guaranteed slot on a topic the candidate never named,
    and the honest handling — zero slots plus a note saying this was read as
    context about the candidate and not as a topic — is only possible if the miss
    is reported as one.
    """
    assert COGNIZANT is not None
    assert syllabus.match_focus(COGNIZANT, term) is None


def test_an_alias_cannot_conjure_an_area_the_syllabus_does_not_have() -> None:
    """
    The alias table is global; the syllabus is not. A React alias resolving
    against a syllabus with no React area would invent coverage — the same class
    of lie as `research_lookup` handing over a sibling program's research.
    """
    assert COGNIZANT is not None
    without_react = copy.deepcopy(dict(COGNIZANT))
    without_react["areas"] = tuple(
        area for area in COGNIZANT["areas"] if area["name"] != "React & Frontend"
    )
    assert syllabus.match_focus(without_react, "reactjs") is None  # type: ignore[arg-type]
    assert syllabus.match_focus(without_react, "sql") is not None  # type: ignore[arg-type]


# ─── Resolution never widens across a program ────────────────────────────────


@pytest.mark.parametrize(
    ("company", "program"),
    [
        ("Cognizant", "GenC"),
        ("Cognizant", "GenC Next"),
        ("Cognizant", "GenC Pro"),
        ("Cognizant", ""),
        ("Infosys", "Digital Nurture — Java FSE"),
        ("TCS", "Ninja"),
        ("", "Digital Nurture — Java FSE"),
        ("Some Startup", "Backend Engineer"),
    ],
)
def test_an_unauthored_interview_gets_no_syllabus_at_all(company: str, program: str) -> None:
    """
    `None` is the important return: it means "we have no field research for this
    interview", and the caller falls back to exactly today's machinery.

    This is the direct counter-example to `research_lookup.py`'s
    `by_program.get(slug) or by_program.get("") or rows[0]` over a query with no
    ORDER BY, which hands a Java FSE candidate either GenC's forty-minute viva or
    GenC Next's three-hour DSA round at random and then tells the prompt to treat
    it as the primary source of truth. A GenC candidate must keep the behaviour
    they have, and no company may inherit Cognizant's shape by adjacency.
    """
    assert syllabus.resolve(company, program) is None


@pytest.mark.parametrize(
    "program",
    [
        "Digital Nurture — Java FSE",
        "digital-nurture-java-fse",
        "Digital Nurture",
        "Digital Nurture 5.0",
        "DN Java FSE",
        "Java FSE",
        "Java Full Stack",
        "Java Full Stack Engineer",
    ],
)
def test_the_program_forms_a_candidate_types_all_resolve(program: str) -> None:
    """
    The aliases `research_lookup._PROGRAM_ALIASES` is missing. Their absence there
    is why the research lookup fell through to `rows[0]` in the first place, and a
    syllabus nobody can address is a syllabus nobody gets.
    """
    found = syllabus.resolve("Cognizant", program)
    assert found is not None and found["program"] == "digital-nurture-java-fse"


def test_every_syllabus_names_a_real_catalogue_company_and_program() -> None:
    """
    The one seam back to `knowledge/companies/catalogue.yaml`. The catalogue keeps
    its own — correctly different — weights for the eight-week STUDY ROADMAP,
    where Aptitude at 15% is right because round one exists. This test is what
    stops the two files drifting into describing different programs while both
    claim to describe the same one.
    """
    catalogue = load_catalogue()
    companies = {company.slug: company for company in catalogue.companies}
    for entry in syllabus.SYLLABI:
        company = companies.get(entry["company"])
        assert company is not None, f"{entry['company']} is not a catalogue slug"
        programs = {syllabus._slugify(program.name) for program in company.programs}
        assert entry["program"] in programs, (
            f"{entry['program']} is not a program of {company.slug}: {sorted(programs)}"
        )


def test_the_kind_and_mix_accessors_agree_with_the_authored_data() -> None:
    """
    `mix_for` exists so that `syllabus["shape_mix"] or SHAPE_MIX[...]` is written
    once. Nothing overrides its kind's mix today, and this is what will fail
    loudly the day something does and gets it wrong.
    """
    assert COGNIZANT is not None
    assert COGNIZANT["shape_mix"] is None
    assert syllabus.mix_for(COGNIZANT) == SHAPE_MIX[InterviewKind.CAMPUS_FUNDAMENTALS]
    assert mix_total(syllabus.mix_for(COGNIZANT)) == 100


# ─── Coverage, repetition and honest gaps ────────────────────────────────────


def test_the_syllabus_covers_the_round_the_candidate_is_actually_sitting() -> None:
    """
    Report (3). The old must-cover block was `java_fundamentals.ALL_TOPICS` —
    sixteen Java topics, no React, no SQL area (only the string "DBMS & SQL — 15%
    of the assessment", a percentage with nothing under it) and no spoken coding
    at all. A Java FSE candidate was briefed on two thirds of their own syllabus.
    """
    assert COGNIZANT is not None
    names = {area["name"] for area in COGNIZANT["areas"]}
    assert names == {
        "Core Java",
        "OOP & Class Design",
        "React & Frontend",
        "SQL & Data Modelling",
        "Spring Boot & REST",
        "Coding Fundamentals",
    }
    # Aptitude is round one, not this round, and a DSA block would reimpose the
    # GenC Next shape the wrong research row was already imposing on this program.
    assert not any("aptitude" in name.lower() for name in names)
    assert not any("algorithms" in name.lower() for name in names)


def test_the_rendered_brief_names_react_and_sql_subtopics() -> None:
    """
    The end-to-end version of the test above: it is not enough for the data to
    hold React and SQL, the text the model receives has to.
    """
    assert COGNIZANT is not None
    brief = syllabus.render(
        COGNIZANT,
        syllabus.plan_grid(
            COGNIZANT, 12, reserved={"React & Frontend": 2, "SQL & Data Modelling": 1}
        ),
    )
    assert "React & Frontend" in brief
    assert "SQL & Data Modelling" in brief
    react = next(a for a in COGNIZANT["areas"] if a["name"] == "React & Frontend")
    sql = next(a for a in COGNIZANT["areas"] if a["name"] == "SQL & Data Modelling")
    assert any(subtopic in brief for subtopic in react["subtopics"])
    assert any(subtopic in brief for subtopic in sql["subtopics"])
    # And the candidate must be able to see that their box bought something.
    assert "because the candidate asked for them" in brief


def test_bank_gaps_admits_what_an_ai_timeout_cannot_cover() -> None:
    """
    Not a defect to paper over. `java_fundamentals` has no React question, no SQL
    question and nothing to ask aloud, so the fallback path — which the
    orchestrator's own docstring calls "not the rare exception it reads as" —
    physically cannot cover half this syllabus. A reduced interview the candidate
    is TOLD about beats a complete-looking one that quietly dropped three areas.
    """
    assert COGNIZANT is not None
    gaps = syllabus.bank_gaps(COGNIZANT)
    assert set(gaps) == {"React & Frontend", "SQL & Data Modelling", "Coding Fundamentals"}
    brief = syllabus.render(COGNIZANT, syllabus.plan_grid(COGNIZANT, 12))
    assert "no offline question bank" in brief


def test_every_claimed_bank_topic_really_exists_in_the_bank() -> None:
    """
    The other half of the same honesty. Validated at import; pinned here so the
    failure says which topic and which area rather than "import error".
    """
    for entry in syllabus.SYLLABI:
        for area in entry["areas"]:
            unknown = set(area["bank_topics"]) - set(ALL_TOPICS)
            assert not unknown, f"{area['name']} claims {sorted(unknown)}, absent from the bank"


def test_subtopic_id_survives_an_insertion_in_the_middle_of_the_list() -> None:
    """
    The id is persisted against answered questions and compared across sittings.
    Derived from an index, inserting a subtopic would reassign every id after it,
    and a candidate would be served subtopics they had already had — forever, and
    silently. Same reason `catalogue.subtopic_id` hashes the name.
    """
    assert COGNIZANT is not None
    area = COGNIZANT["areas"][0]
    subtopic = area["subtopics"][-1]
    before = syllabus.subtopic_id(COGNIZANT, area["name"], subtopic)

    shifted = copy.deepcopy(dict(COGNIZANT))
    areas = copy.deepcopy(list(COGNIZANT["areas"]))
    areas[0]["subtopics"] = (
        areas[0]["subtopics"][0],
        "a newly authored descriptor",
        *areas[0]["subtopics"][1:],
    )
    shifted["areas"] = tuple(areas)
    after = syllabus.subtopic_id(shifted, area["name"], subtopic)  # type: ignore[arg-type]
    assert before == after


def test_a_concept_already_asked_one_way_is_still_available_the_other_way() -> None:
    """
    "I want questions LIKE these ... and do not ask the same questions again and
    again", as a mechanism. Coverage is keyed on (subtopic_id, REGISTER), not on
    the subtopic, precisely so that overloading-against-overriding asked as a
    direct question in one sitting can come back as a cross-question in the next.
    That is "the same concept in a genuinely different form".
    """
    assert COGNIZANT is not None
    first = syllabus.plan_grid(COGNIZANT, 12)
    covered = frozenset(
        (slot.subtopic_id, slot.register) for slot in first if slot.subtopic_id is not None
    )
    second = syllabus.plan_grid(COGNIZANT, 12, covered=covered)

    repeats = [
        (slot.subtopic_id, slot.register)
        for slot in second
        if slot.subtopic_id is not None and (slot.subtopic_id, slot.register) in covered
    ]
    assert not repeats, f"the second sitting repeats {repeats}"
    # Same subjects are fair game; same (subject, form) pairs are not.
    assert {slot.area for slot in second if slot.area} & {
        slot.area for slot in first if slot.area
    }


def test_there_are_enough_distinct_forms_for_a_dozen_sittings() -> None:
    """
    The repetition arithmetic, asserted rather than asserted-in-a-comment. A
    subtopic times each register its area permits is one distinct FORM; the
    candidate is preparing for one interview and will sit this mock repeatedly, so
    the space has to be big enough that `covered` is not exhausted in a week.
    """
    assert COGNIZANT is not None
    forms = sum(
        len(area["subtopics"]) * len(area["registers"]) for area in COGNIZANT["areas"]
    )
    subject_rows = sum(
        allocate(syllabus.mix_for(COGNIZANT), 12)[register.value]
        for register in SUBJECT_REGISTERS
    )
    assert forms >= 12 * subject_rows, (
        f"{forms} distinct forms against {subject_rows} subject rows a sitting is not "
        "enough to keep a candidate from seeing repeats within a fortnight"
    )

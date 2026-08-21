"""
The question-shape vocabulary — app/data/question_shape.py

WHAT FORM A QUESTION TAKES, as opposed to what subject it is about. Six
registers, three kinds of interview, and the integer arithmetic that turns a
percentage mix into "row 4 of 11".

WHY THIS FILE EXISTS. A candidate sat a Cognizant Digital Nurture Java FSE mock
and reported that it was "mostly covering the scenario based questions only".
That was not a model failure. `prompts/interview_plan.md` contained, in bold
capitals, "MOST QUESTIONS MUST BE SCENARIO-BASED. At least two thirds of them."
— unconditionally, for every role. Forty-five lines earlier the same file called
the research block "the primary source of truth" and told the model to let it
drive "the *style* of question", and the Cognizant research block says in so many
words that definition-style questions are what get asked. So the prompt held two
contradictory instructions about question style and the scenario one won, because
it was later, bolded, all-caps and — decisively — QUANTIFIED. A model will
negotiate with an adjective and obey a number.

The fix is therefore not a better adjective. It is to move the number out of
prose and into Python, and to make it conditional on what kind of interview this
actually is. A campus fundamentals viva and a sales interview want opposite
mixes; the two-thirds line was written for the second and was being applied to
the first.

THREE KINDS, AND WHY NOT MORE. `ROLE_SCENARIO` preserves today's behaviour
exactly for the non-technical domain roles the two-thirds line was written for —
`tests/test_role_scoping.py` requires scenario-majority across every
`domains.PROFILES` seed bank, and a sales interview that regressed into a viva
would be a worse bug than the one being fixed. `CAMPUS_FUNDAMENTALS` is the
fresher technical round: fundamentals asked directly, then cross-questioned.
`GENERAL_TECHNICAL` is the middle — technical, but experienced or product-company
shaped, where a situation is a fair opening. A fourth kind would need evidence
that its mix differs from all three, and there is none.

INTEGER COUNTS, NEVER FRACTIONS. `allocate` uses largest-remainder over
`question_count - 1` — the minus one is the mandated introduction, which is
question 1 of every interview and is not part of any register's budget. Every
count derives from the caller's `question_count` (in practice
`settings.INTERVIEW_QUESTION_COUNT`, default 12, range 4–25). Writing "3 of 12"
as a literal anywhere reintroduces precisely the bug
`test_the_adaptive_path_uses_the_setting_not_a_hardcoded_number` exists to catch:
raising the setting moves the dashboard and not the interview.

WHAT THIS FILE DELIBERATELY DOES NOT DO. It holds no data about any company,
program, role or topic, and it must not grow any. That is what keeps
`app/data/syllabus.py` able to import from here without a cycle: `syllabus`
imports the shape vocabulary and may override the mix for one program;
`question_shape` never imports `syllabus` and never learns what a syllabus is.
It also does not contain a single sentence a candidate could be asked — the
registers describe forms, not questions.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import TypedDict


class Register(StrEnum):
    """
    The FORM a question takes. Orthogonal to its subject.

    The values are deliberately identical to the `ShapeMix` keys, so the mapping
    between the enum and the authored percentages lives in exactly one function
    (`_as_counts`) and a mismatch fails at import rather than at plan time.

    A note on vocabulary, because the design discussion used two words for one
    thing: `SCENARIO` is what the fix contract and the prompts call it, and what
    a sales interview means by it — a business situation. The syllabus tables
    describe the same register as "applied" for a technical area, where the
    situation is a bug or a slow query rather than a dealer dispute. Same
    register, same budget line; only the framing differs, and the framing is the
    area's business, not this file's.
    """

    #: Ask the fundamental directly. "The difference between X and Y." The
    #: backbone of a campus technical round and the thing the reported bug had
    #: squeezed down to almost nothing.
    RECALL = "recall"
    #: The trap follow-up, which is the distinctive Cognizant move: the candidate
    #: has just said something true-sounding and gets asked the case where it
    #: stops being true. Always needs a rule underneath it to trap, which is why
    #: `Area.cross_themes` exists and why an area that declares CROSS must
    #: declare themes.
    CROSS = "cross"
    #: A situation, and what the candidate would do about it.
    SCENARIO = "scenario"
    #: Code reasoned about out loud, with no editor. Approach, dry-run, edge
    #: case. Not a DSA round — there is a separate coding round for that — and
    #: the sixty seconds a spoken answer gets is the reason.
    CODE_ALOUD = "coding_aloud"
    #: The candidate's own work. Subject is the candidate, not the syllabus,
    #: which is why a PROJECT slot carries no area.
    PROJECT = "project"
    #: Behavioural and HR. Same reason it carries no area.
    BEHAVIOURAL = "hr"


class ShapeMix(TypedDict):
    """
    Percentages, summing to 100, of the non-introduction questions.

    Percentages rather than counts because `question_count` is configurable
    (4–25) and a count authored here would be right for exactly one setting.
    `allocate` is the only thing that turns these into integers.
    """

    recall: int
    cross: int
    scenario: int
    coding_aloud: int
    project: int
    hr: int


class InterviewKind(StrEnum):
    """Which of the three shapes of interview this session is."""

    #: Fresher, technical, campus recruiter. Fundamentals viva plus
    #: cross-questions. Cognizant Digital Nurture, TCS NQT, Infosys SE.
    CAMPUS_FUNDAMENTALS = "campus_fundamentals"
    #: Non-technical or domain role. Sales, marketing, HR, finance, operations,
    #: consulting. Overwhelmingly situational, and the mix below is the one
    #: today's prompt already produces — this branch is a no-op by design.
    ROLE_SCENARIO = "role_scenario"
    #: Technical, but not a campus fundamentals round.
    GENERAL_TECHNICAL = "general_technical"


#: The authored mixes. Each sums to 100, checked at import for the same reason
#: `domains.PROFILES` checks its topic weights and the company catalogue checks
#: its own: a mix summing to 90 does not fail, it silently under-plans every
#: interview, and it does so months after the typo was committed.
SHAPE_MIX: dict[InterviewKind, ShapeMix] = {
    # Six of eleven questions are fundamentals asked directly or cross-questioned,
    # against ONE scenario. That 6:1 inversion of interview_plan.md's roughly 7:4
    # the other way is the whole of the reported fix, and it is now a number in a
    # table rather than an adjective in a prompt.
    InterviewKind.CAMPUS_FUNDAMENTALS: {
        "recall": 30,
        "cross": 25,
        "scenario": 10,
        "coding_aloud": 10,
        "project": 15,
        "hr": 10,
    },
    # Unchanged behaviour for the roles the two-thirds line was actually written
    # for. `cross` is zero here not because a follow-up never happens in a sales
    # interview but because the trap-follow-up register needs a rule to trap, and
    # a domain profile has topics rather than rules.
    InterviewKind.ROLE_SCENARIO: {
        "recall": 15,
        "cross": 0,
        "scenario": 60,
        "coding_aloud": 0,
        "project": 15,
        "hr": 10,
    },
    InterviewKind.GENERAL_TECHNICAL: {
        "recall": 20,
        "cross": 15,
        "scenario": 30,
        "coding_aloud": 10,
        "project": 15,
        "hr": 10,
    },
}

#: Registers whose subject is a syllabus area. The other two — PROJECT and
#: BEHAVIOURAL — are about the candidate, so a planner must not try to steer them
#: onto a topic. Exported because `syllabus.plan_grid` needs exactly this split.
SUBJECT_REGISTERS: tuple[Register, ...] = (
    Register.RECALL,
    Register.CROSS,
    Register.SCENARIO,
    Register.CODE_ALOUD,
)

#: The remaining two, in the order a real interview reaches them.
PERSONAL_REGISTERS: tuple[Register, ...] = (Register.PROJECT, Register.BEHAVIOURAL)


def _as_counts(mix: ShapeMix) -> dict[str, int]:
    """
    A `ShapeMix` as a plain dict keyed by `Register` value.

    Written out by hand rather than with `dict(mix)` so that the correspondence
    between the enum and the TypedDict keys is a single explicit list that mypy
    checks, instead of an assumption that holds until somebody renames a key.
    """
    return {
        Register.RECALL.value: mix["recall"],
        Register.CROSS.value: mix["cross"],
        Register.SCENARIO.value: mix["scenario"],
        Register.CODE_ALOUD.value: mix["coding_aloud"],
        Register.PROJECT.value: mix["project"],
        Register.BEHAVIOURAL.value: mix["hr"],
    }


def mix_total(mix: ShapeMix) -> int:
    """
    A mix's percentages added up, for a validator to compare against 100.

    This exists because `sum(mix.values())` does not typecheck: mypy types a
    TypedDict's `.values()` as `object`, so the only way to add the numbers up
    with the checker's blessing is to name the six keys — and naming them in two
    files is how two files come to disagree about which keys there are.
    `_as_counts` is the one place that knows the correspondence, so the sum goes
    through it too. Called by `_validate` below for the authored defaults and by
    `syllabus._validate` for a per-program `shape_mix` override, which is a
    `ShapeMix` authored somewhere this module cannot see.
    """
    return sum(_as_counts(mix).values())


def largest_remainder(weights: dict[str, float], total_slots: int) -> dict[str, int]:
    """
    Apportion `total_slots` whole slots across `weights`, summing exactly.

    Largest remainder (Hare quota): floor everything, then hand the leftovers to
    whoever was robbed hardest by the flooring. Ties broken by weight and then by
    key, so the result is fully deterministic — a plan that differed between two
    identical requests would make every test here probabilistic and every bug
    report unreproducible.

    Shared by the register mix and by the syllabus's per-area budget, because
    they are the same apportionment problem and having two implementations of it
    is how the two of them come to disagree about a total.
    """
    if total_slots <= 0 or not weights:
        return dict.fromkeys(weights, 0)

    total_weight = sum(weights.values())
    if total_weight <= 0:
        return dict.fromkeys(weights, 0)

    exact = {key: value * total_slots / total_weight for key, value in weights.items()}
    out = {key: int(math.floor(value)) for key, value in exact.items()}

    # Hand out the shortfall one slot at a time rather than slicing a sorted list.
    # A slice silently under-allocates if the shortfall ever exceeds the number of
    # keys, and "the grid is one row short" is exactly the class of bug that is
    # invisible until a candidate counts their questions.
    order = sorted(weights, key=lambda key: (-(exact[key] - out[key]), -weights[key], key))
    index = 0
    while sum(out.values()) < total_slots:
        key = order[index % len(order)]
        out[key] += 1
        index += 1
    return out


def allocate(mix: ShapeMix, question_count: int) -> dict[str, int]:
    """
    A mix as integer question counts, keyed by `Register` value.

    Sums to `question_count - 1`. The missing one is question 1, the mandated
    introduction, which belongs to no register — it is not a "recall" question
    about the syllabus, it is "tell me about yourself", and counting it against a
    register's budget would quietly cost the interview one real question.

    At the default twelve and `CAMPUS_FUNDAMENTALS` this returns recall 3,
    cross 3, scenario 1, coding_aloud 1, project 2, hr 1 — eleven rows.
    """
    return largest_remainder(
        {key: float(value) for key, value in _as_counts(mix).items()},
        max(question_count - 1, 0),
    )


def allocation(kind: InterviewKind, question_count: int) -> dict[str, int]:
    """`allocate` for a kind's default mix. The common case."""
    return allocate(SHAPE_MIX[kind], question_count)


def resolve_kind(
    *,
    is_technical: bool,
    domain: str,
    domain_matched: bool,
    company_tier: str,
    program: str,
) -> InterviewKind:
    """
    Which kind of interview this is. Resolve ONCE and pin it.

    The intended caller writes the result into `session_metadata` beside
    `is_technical` and never re-derives it, for the reason `is_technical` is
    pinned: a value re-computed per request from mutable inputs is a value that
    can change halfway through an interview, and an interview that changed shape
    at question seven is indistinguishable from a bug.

    Order of the decision, and why:

    1. Not technical wins outright. A sales, HR, marketing, finance, operations
       or consulting interview is `ROLE_SCENARIO` regardless of who is hiring,
       because the register mix follows the ROLE and a mass recruiter hiring for
       sales is still hiring for sales. This branch is what keeps today's
       behaviour for `domains.PROFILES` intact.
    2. A mass recruiter or a named campus program means a fresher round, which is
       a fundamentals viva. `company_tier` comes from the catalogue
       (`mass_recruiter` | `consulting` | `product`); the program check is a
       keyword match rather than a program allowlist for the same reason
       `java_fundamentals._wants_frameworks` is — the catalogue has twelve
       companies and dozens of programs and a candidate can type anything at all,
       so a list is wrong the moment a new program appears.
    3. Everything else technical is `GENERAL_TECHNICAL`.

    `domain` and `domain_matched` are accepted and mostly unused on purpose: they
    are the caller's evidence about how confident the role resolution was, and an
    unmatched domain is the case where `is_technical` is a guess at the default
    rather than a finding. Today that guess does not change the answer — an
    unmatched role still gets whatever `is_technical` says — but the parameters
    exist so that decision has somewhere to live if it ever needs to.
    """
    if not is_technical:
        return InterviewKind.ROLE_SCENARIO

    haystack = f"{program} {domain if domain_matched else ''}".lower()
    campus_program = any(
        keyword in haystack
        for keyword in (
            "genc",
            "gen c",
            "digital nurture",
            "nurture",
            "nqt",
            "ninja",
            "system engineer",
            "power programmer",
            "specialist programmer",
            "elite",
            "fresher",
            "trainee",
            "graduate engineer",
            "get",
        )
    )
    if company_tier == "mass_recruiter" or campus_program:
        return InterviewKind.CAMPUS_FUNDAMENTALS
    return InterviewKind.GENERAL_TECHNICAL


#: Prose for each register, for the prompt. One clause each, stating the form and
#: not an example — an example question in a template is how canned wording gets
#: back into generated output, which is the disease being cured here.
_REGISTER_BRIEF: dict[Register, str] = {
    Register.RECALL: "ask the fundamental directly, and expect a crisp answer",
    Register.CROSS: (
        "follow a claim into the case where it stops holding, without stating the trap"
    ),
    Register.SCENARIO: "put the candidate in a situation and ask what they would do",
    Register.CODE_ALOUD: "ask for an approach and a dry-run out loud, with no editor",
    Register.PROJECT: "dig into the candidate's own work, not the syllabus",
    Register.BEHAVIOURAL: "ask a behavioural question about the candidate, not the syllabus",
}


def shape_block(kind: InterviewKind, question_count: int) -> str:
    """
    The mix as a prompt block. THE one renderer for question shape.

    Counts, not proportions, and stated as an exact requirement — this text
    replaces `interview_plan.md`'s bolded "at least two thirds of them" and
    `question_generator.md`'s separate difficulty-to-shape mapping, which were a
    third and fourth opinion about the same question. Anything that needs to tell
    a model what shape a question should be calls this.
    """
    counts = allocate(SHAPE_MIX[kind], question_count)
    lines = [
        f"- **{count} {'question' if count == 1 else 'questions'}** — "
        f"{_REGISTER_BRIEF[Register(register)]}"
        for register, count in counts.items()
        if count > 0
    ]
    body = "\n".join(lines)
    return (
        f"Question 1 is the introduction and is not counted below. "
        f"The remaining {max(question_count - 1, 0)} questions break down as exactly this, "
        f"and these are counts rather than preferences:\n"
        f"{body}\n"
        f"Do not trade one of these counts for another. If a shape does not appear "
        f"above, this interview does not use it."
    )


def _validate() -> None:
    """
    Fail at import on a malformed mix.

    An import-time raise rather than a test, following `domains.py`: a mis-summed
    distribution must stop the process starting, because the alternative is an
    interview that renders correctly and is shaped wrongly, and nobody reads the
    logs of something that appears to work.
    """
    mix_keys = set(ShapeMix.__annotations__)
    register_values = {register.value for register in Register}
    if mix_keys != register_values:
        raise ValueError(
            f"ShapeMix keys {sorted(mix_keys)} do not match Register values "
            f"{sorted(register_values)} — _as_counts cannot be correct for both"
        )

    for kind in InterviewKind:
        if kind not in SHAPE_MIX:
            raise ValueError(f"interview kind '{kind}' has no shape mix")
        total = mix_total(SHAPE_MIX[kind])
        if total != 100:
            raise ValueError(f"shape mix for '{kind}' sums to {total}, expected 100")

    if set(SUBJECT_REGISTERS) | set(PERSONAL_REGISTERS) != set(Register):
        raise ValueError("SUBJECT_REGISTERS and PERSONAL_REGISTERS must partition Register")
    if set(SUBJECT_REGISTERS) & set(PERSONAL_REGISTERS):
        raise ValueError("SUBJECT_REGISTERS and PERSONAL_REGISTERS overlap")


_validate()

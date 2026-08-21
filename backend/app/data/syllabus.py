"""
The interview syllabus — app/data/syllabus.py

WHAT A REAL INTERVIEW AT ONE COMPANY, FOR ONE PROGRAM, ACTUALLY COVERS.
Areas, weights, sub-topic descriptors, cross-question themes, register affinity.
No question text. Not one sentence a candidate could be asked. The model writes
every sentence, fresh, every session; this file only decides what it is allowed
to write about and in what form.

────────────────────────────────────────────────────────────────────────────────
THE REPORT THAT CAUSED THIS FILE
────────────────────────────────────────────────────────────────────────────────

A candidate sat a Cognizant Digital Nurture 5.0 Java FSE mock, in preparation for
the real technical interview, and reported three things.

  1. It was "mostly covering the scenario based questions only". The real round is
     a fundamentals viva with cross-questions — "can you override a static
     method?", "can we overload by changing only the return type?" — and they got
     situational questions instead.
  2. It was "not looking at what i have filled in the blocks for additional
     topics". The setup screen has a free-text box labelled "Anything specific?".
     They filled it in. Nothing changed.
  3. The interview did not cover the round they are actually sitting: Java and
     OOP, React, SQL, Spring Boot and REST, basic coding aloud, the project, HR.

All three had the same shape of cause: the knowledge of what this interview
covers did not exist anywhere in the codebase as data, so every path that needed
it improvised.

  · `prompts/interview_plan.md` carried, in bold capitals, "MOST QUESTIONS MUST
    BE SCENARIO-BASED. At least two thirds of them." Unconditionally. For every
    role, including this one. Forty-five lines earlier the same file called the
    research block the primary source of truth and told the model to let it drive
    the *style* of question — and the Cognizant research block says definition-
    style questions are what get asked. The prompt contradicted itself and the
    scenario instruction won, because it was later, bolded and QUANTIFIED. That
    is report (1), and it is fixed by `question_shape.py` plus `plan_grid` below,
    not by softening an adjective.
  · The must-cover list came from `java_fundamentals.ALL_TOPICS`, sixteen Java
    topics with no React, no SQL area and no spoken-coding area at all. A Java
    FSE candidate was therefore briefed on two thirds of their own syllabus. That
    is report (3).
  · The typed focus reached exactly one of the four paths that produce a
    question, and even there it got one courteous clause against "draw the
    majority of your questions from this list" and "stay inside it". That is
    report (2), and this file's contribution to the fix is `match_focus` plus
    `plan_grid(reserved=...)`, which turn the box into an integer number of
    guaranteed slots.

────────────────────────────────────────────────────────────────────────────────
THE ANTI-HARDCODE CONTRACT — READ THIS BEFORE ADDING ANYTHING
────────────────────────────────────────────────────────────────────────────────

The candidate was explicit: "do not copy past or hardcode anything ... i want
questions LIKE these ... and do not ask the same questions again and again."

So this file encodes the SYLLABUS and never the questions. The mechanism is not a
policy anybody has to remember — it is that **there is nowhere to put a
question**. No TypedDict here has a `content`, `question`, `text`, `example`,
`prompt` or `questions` field. Someone who wants to add "Can you override a
static method?" has no key to hang it on, and adding one is a schema change in a
reviewed diff rather than a data edit buried in a four-hundred-line literal.
`tests/test_syllabus.py` freezes both key sets so that diff cannot pass quietly.

Everything below that is defence in depth, for the case where somebody stuffs a
question into `subtopics` instead. `_validate()` runs at import — following
`domains.py`, which raises when its topic weights do not sum to 100 — and rejects
any authored string that:

  · contains a question mark (the signature of question text, and the prompt
    requires generated questions to end in one, so its presence here means
    output was pasted back into the input);
  · runs longer than nine words for a descriptor or fourteen for a claim or a
    shape (this repo's own shortest real interview question is twelve words);
  · opens with an interrogative or an imperative — this is the rule that catches
    the determined sneak, because the obvious way past the first two rules is to
    strip the mark and shorten, and "explain abstract class and interface" is
    five words with no question mark and dies here;
  · addresses the candidate in the second person (a question addresses the
    candidate; a descriptor names a concept);
  · carries quotation marks, an "e.g.", a trailing colon or a code fence — quotes
    are how a copied question survives de-punctuation, and "e.g." is the tell
    that an example question follows, which is exactly the disease being cured.

And one rule that can only live in the test suite, because it needs the other
banks loaded: no descriptor may share a five-word content shingle with any
question in `java_fundamentals`, `domains.PROFILES` or the quiz banks. That is
what makes it structurally impossible to smuggle canned questions in from inside
the repo — including out of the deleted
`knowledge/interview_patterns/cognizant_java_fse.md`, whose "Commonly Asked
Questions" lists were precisely the material at risk. It is deliberately tolerant
of shared vocabulary: "overriding a static method" is three content words, forms
no five-gram, and *should* be shared. The syllabus and the bank are allowed to
name the same concept and forbidden from sharing a sentence.

Staleness is deliberately NOT a hard failure. A `verified` date older than
eighteen months logs a warning at import and does not raise. A date-triggered
test failure is a time bomb that blocks unrelated work months later and gets
deleted rather than fixed, which loses the signal entirely.

────────────────────────────────────────────────────────────────────────────────
WHERE THIS FILE SITS — THE THREE-WAY OWNERSHIP SPLIT
────────────────────────────────────────────────────────────────────────────────

Three files in `app/data/` now answer three different questions, and the whole
point of the split is that none of them can hold a second opinion about another's
answer.

  `domains.py`            what a ROLE FAMILY is about when we have no
                          company-and-program syllabus: the fallback topic
                          weighting, the panel designations, the situational seed
                          bank, and the prohibition that keeps CS questions out
                          of a sales interview.
  `java_fundamentals.py`  the offline Java question TEXT. Literal `content`,
                          `ideal` and `keywords`, used to seed the database and to
                          top up when the model is short or unavailable. It is the
                          only one of the three allowed to contain a sentence a
                          candidate could be asked.
  `syllabus.py`           what a real interview at ONE COMPANY for ONE PROGRAM
                          covers. Areas, weights, descriptors, cross-themes,
                          register affinity, offline-coverage claims, stable
                          subtopic ids. No question text at all.

They meet at exactly two seams and nowhere else. `Area.bank_topics` names
`java_fundamentals` topics, validated at import so a rename cannot rot silently.
And `resolve()` returning `None` is the handoff to `domains`.

PRECEDENCE, in the order a caller must apply it:

  1. `resolve(company, program)` — a syllabus authored from field reports for
     this exact company and program. Wins outright when it exists.
  2. `resolve(company, "")` — a program-agnostic company row, if one is ever
     authored. None is today.
  3. `None` → the caller falls back to the machinery that already works:
     `domains.topic_block` refined by the company's catalogue weighting.

`resolve` returns `None` and NEVER a sibling program's syllabus. This is the same
defect as `research_lookup`'s `or rows[0]`, which hands a Java FSE candidate GenC
Next's three-hour DSA research over an unordered SELECT and then tells the prompt
it is the primary source of truth. Wrong data wearing a confident label is worse
than no data. `resolve("cognizant", "genc")` is `None` today, and the GenC
candidate keeps exactly today's behaviour.

It also takes no `track_name`. The carrier track cannot reach this decision at
all, which structurally closes the `context.py` hole — where a candidate who
typed "Morani Plastics / Sales" onto a Java carrier track was briefed on the Java
bank — rather than guarding it with a flag somebody can forget to pass.

────────────────────────────────────────────────────────────────────────────────
WHY PYTHON, AND WHY NOT A NEW FIELD ON THE CATALOGUE
────────────────────────────────────────────────────────────────────────────────

The obvious alternative was `areas:` on `catalogue.Program` in
`knowledge/companies/catalogue.yaml`. Four reasons it is not that, in order of
weight.

  1. mypy covers a TypedDict and covers nothing in a YAML file. This is the same
     reason CLAUDE.md gives for the question banks being Python. The syllabus is
     read by the planner, the generator, the fallback, the focus allocator, the
     dedup path and the plan-review screen; a renamed key surfaces in YAML as a
     KeyError in production and in Python as a red CI.
  2. It carries behaviour. `Area.registers` is not a value, it is a rule about
     which form may be paired with which subject, and `plan_grid` consumes it as
     a constraint. `Area.bank_topics` is a claim about offline fillability that
     `bank_gaps` consumes. `java_fundamentals.for_track()` is the precedent:
     data whose meaning is a function rather than a string.
  3. `catalogue.yaml` is the STUDY ROADMAP's source of truth and its weights are
     correctly different from the interview's. Cognizant's catalogue entry
     weights Aptitude at 15 and DSA at 15 because an eight-week study plan must
     cover round one and the coding round. The technical interview covers
     neither. Making one document answer two questions with two incompatible
     distributions is how a candidate ended up with Aptitude in a technical
     interview's weighting in the first place. Leaving `catalogue.yaml`
     byte-identical also means `build_roadmap`, `test_company_catalogue` and the
     other eleven companies carry zero risk from this change.
  4. The anti-hardcode rule is enforceable at import in Python and only in a test
     in YAML.

The link back to the catalogue is `_ALIASES` in this module, which does the job
`research_lookup._PROGRAM_ALIASES` does and carries the entries that table is
missing. A test asserts every `SYLLABI` entry names a real company slug and a
real `Program.name` in the catalogue, so the two files cannot drift into
describing different programs.

────────────────────────────────────────────────────────────────────────────────
TWO ORTHOGONAL AXES, WHICH IS THE DECISION THAT MATTERS MOST
────────────────────────────────────────────────────────────────────────────────

Areas say what SUBJECT is asked. Registers (`question_shape.Register`) say what
FORM. They are separate because "project" and "HR" are forms whose subject is the
candidate rather than entries in a syllabus — a single flat weighted list that
contains both "SQL 15" and "Project 12" double-counts, and a plan built from it
spends the shape mix's project budget and then an area's project weight on top.

The cross-tabulation is also the interesting requirement. OOP must be askable as
RECALL *and* as CROSS, and the same subtopic asked in a different register is
precisely the "same concept in a genuinely different form" the candidate asked
for. That is why cross-sitting coverage is keyed on `(subtopic_id, register)` and
not on the subtopic alone. Counted rather than estimated: the fifty-seven
descriptors below, each times the registers its area permits, are 147 distinct
forms, against the eight SUBJECT rows of a twelve-question sitting — the other
three being the introduction, the project and HR, which are not drawn from this
space at all. That is around eighteen sittings before a repeat is arithmetically
forced, and `covered` spends them in a deterministic order rather than
reshuffling. `tests/test_syllabus.py` pins the ratio, so adding an area or
narrowing a register set cannot quietly shrink it.

WHAT THIS FILE DELIBERATELY DOES NOT DO. It does not decide the shape mix per
kind (`question_shape.py`). It does not classify an off-syllabus focus term as
plausible-but-adjacent or as contradictory — that needs the resolved interview
kind and `domains.is_technical`, and it is the focus allocator's business, not
this file's. It does not touch `_is_personal_focus`, which is a privacy control
and not a shape control. It does not touch the semantic cache. Every one of those
boundaries exists so that this file's single job is to answer "what does this
interview cover", and every extra opinion it held would be a second place for
that answer to disagree with itself.

Adding a syllabus: append a `Syllabus` to `SYLLABI`, add its program aliases to
`_ALIASES`, and check `bank_gaps()` — an area with no offline coverage is not a
blocker, but the fallback path needs to be able to say so.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict

import structlog

from app.data.java_fundamentals import ALL_TOPICS as _BANK_TOPICS
from app.data.question_shape import (
    SHAPE_MIX,
    SUBJECT_REGISTERS,
    InterviewKind,
    Register,
    ShapeMix,
    allocate,
    largest_remainder,
    mix_total,
)

logger = structlog.get_logger(__name__)

#: Deliberately no "hard". A spoken round gives the candidate sixty seconds and
#: no editor, so a hard multi-part design question measures nothing but nerve.
#: This mirrors `java_fundamentals`, which is easy/medium only for the same
#: reason, and leaves `hard` where it belongs — the quiz banks.
Difficulty = Literal["easy", "medium"]


# ─── Authored data ────────────────────────────────────────────────────────────
#
# TypedDict, because that is what this repo's data files already are:
# `BankQuestion` in java_fundamentals.py, `DomainProfile` and `ScenarioQuestion`
# in domains.py. Literal dicts with no behaviour of their own, checked by mypy at
# every read site.


class Area(TypedDict):
    """One subject-matter block of the interview. Never a question, never a form."""

    #: Human-readable, and the key `reserved` and `FocusHit` use. Not a slug —
    #: it is rendered into the prompt and shown on the plan-review screen.
    name: str
    #: Share of the SUBJECT-MATTER slots. Areas sum to 100. Not a share of the
    #: interview: project, HR, coding-aloud and the introduction are allocated by
    #: the shape mix, on the other axis.
    weight: float
    #: Ceiling for a spoken round, mirroring java_fundamentals' easy/medium.
    depth: Difficulty
    #: The forms this area can legitimately carry, most characteristic first.
    #: This is a rule, not a value: it is what stops `plan_grid` pairing a
    #: register with an area that cannot bear it — HR is not an area at all, and
    #: an area with no traps in it must not be handed a CROSS row. The ordering
    #: matters too: it is how a CODE_ALOUD slot lands on Coding Fundamentals
    #: rather than on SQL, which can carry one but is not defined by it.
    registers: tuple[Register, ...]
    #: Noun-phrase descriptors. Nine words maximum, no question mark, no
    #: interrogative opener. What the model is steered ONTO, never what it says.
    subtopics: tuple[str, ...]
    #: The distinctive Cognizant move, stored as the TRAP STATED AS A CLAIM.
    #: Fourteen words maximum. The renderer instructs the model to write a
    #: question that TESTS the claim and never to restate it — the candidate has
    #: to walk into it for the answer to be worth anything.
    cross_themes: tuple[str, ...]
    #: `java_fundamentals` topic names that can fill this area offline. An empty
    #: tuple means "no offline coverage" and is READ, by `bank_gaps`, rather than
    #: ignored: three of the six areas below have none, and an AI timeout must
    #: produce an interview the candidate knows was reduced instead of a
    #: complete-looking one that quietly dropped half the syllabus.
    bank_topics: tuple[str, ...]


class Syllabus(TypedDict):
    """One company, one program, as much of it as a human has verified."""

    #: Catalogue slug, e.g. "cognizant".
    company: str
    #: Slug of the catalogue `Program.name`.
    program: str
    #: Human string for the plan-review screen.
    label: str
    #: `InterviewKind` value. Resolved once and pinned into `session_metadata`,
    #: never re-derived per request — an interview that changed shape at question
    #: seven is indistinguishable from a bug.
    kind: str
    #: Per-program override of the kind's default mix. `None` means the kind's
    #: mix is right for this program, which is the case everywhere today. The
    #: field exists because a program is the level at which a mix would ever
    #: legitimately differ (GenC Next's coding-heavy round against GenC's viva).
    shape_mix: ShapeMix | None
    areas: tuple[Area, ...]
    #: SHAPES of spoken coding tasks, fourteen words maximum. A shape, not a
    #: problem: "a hash map tally over characters" steers, "reverse the string
    #: interviewos" is a canned question with extra steps.
    code_shapes: tuple[str, ...]
    #: What to dig at in the candidate's own work.
    project_probes: tuple[str, ...]
    #: Behavioural themes, nine words maximum.
    hr_themes: tuple[str, ...]
    #: Provenance, in prose. Where this came from, so the next person to edit it
    #: knows what evidence they are arguing with.
    sourced: str
    #: ISO date a human last checked it against a first-party or candidate report.
    verified: str


# ─── Computed values ──────────────────────────────────────────────────────────
#
# Frozen dataclasses rather than TypedDicts, because these are outputs of
# `plan_grid` and never authored. Frozen because the same grid is rendered into
# the prompt, persisted onto the Question rows and shown on the review screen,
# and a caller that mutated a slot between two of those three would produce an
# interview whose plan, whose database and whose review screen disagreed.


@dataclass(frozen=True, slots=True)
class Slot:
    """One question the planner must produce, fully specified except for its words."""

    #: Row number in the grid, 1-based. The interview's question number is
    #: `position + 1`, because question 1 is the mandated introduction and
    #: belongs to no register.
    position: int
    #: `None` for PROJECT and BEHAVIOURAL rows: the subject is the candidate, not
    #: the syllabus.
    area: str | None
    register: Register
    difficulty: Difficulty
    #: The descriptor this row is steered onto.
    subtopic: str | None
    #: Stable id, persisted so a later sitting can avoid the same
    #: (subtopic, register) pair. Derived from names — see `subtopic_id`.
    subtopic_id: str | None
    #: A `cross_themes` entry, on CROSS rows only.
    theme: str | None
    #: Why this row exists. "focus" is what the plan-review screen shows the
    #: candidate so the free-text box can be seen to have bought something.
    reason: Literal["weight", "focus", "mandated"]


@dataclass(frozen=True, slots=True)
class FocusHit:
    """A focus term located on the syllabus."""

    term: str
    area: str
    subtopic: str | None
    how: Literal["area", "subtopic", "alias"]


# ─── The syllabus ─────────────────────────────────────────────────────────────
#
# One entry. Cognizant Digital Nurture — Java FSE, which is the interview the
# candidate is actually sitting and the only one anybody has field reports for.
#
# Structure carried over from the orphaned
# `knowledge/interview_patterns/cognizant_java_fse.md`, which held per-round
# focus areas, a weight table and a difficulty ceiling and was read by NOTHING —
# no reference to it existed in app/, scripts/, tests/ or docs/. Its structure is
# here; its "Commonly Asked Questions" lists are not, and the file is deleted in
# the same change. Leaving it on disk would leave a tempting copy-paste source of
# exactly the literal question text the candidate forbade, with no reader to keep
# it honest.

_CORE_JAVA: Area = {
    "name": "Core Java",
    "weight": 20,
    "depth": "medium",
    "registers": (Register.RECALL, Register.CROSS, Register.SCENARIO),
    "subtopics": (
        "platform independence and the bytecode step",
        "JDK, JRE, JVM boundaries",
        "stack against heap allocation",
        "garbage collection and eligibility",
        "final on a variable, method, class",
        "static members and initialisation order",
        "String, StringBuilder, StringBuffer",
        "wrapper classes and autoboxing",
        "checked against unchecked exceptions",
        "try, catch, finally control flow",
        "thread creation and lifecycle basics",
        "access modifier visibility",
    ),
    "cross_themes": (
        "String immutability and the pool that depends on it",
        "finally against finalize",
        "a checked exception swallowed to satisfy the compiler",
        "garbage collection cannot be forced",
        "a wrapper cached below 128 compares equal by reference",
        "static initialisation runs before any constructor",
        "a thread started twice raises rather than restarting",
    ),
    "bank_topics": (
        "JVM, JDK & JRE",
        "Memory: stack & heap",
        "Strings & the String pool",
        "Collections framework",
        "Exception handling",
        "Java 8 & lambdas",
        "Multithreading",
        "Input & output",
    ),
}

_OOP: Area = {
    "name": "OOP & Class Design",
    # Tied with Core Java at the top, and that is on purpose. The cross-question
    # move is the DISTINCTIVE Cognizant behaviour the candidate reported wanting,
    # and every cross-question needs an OOP rule underneath it to trap.
    "weight": 20,
    "depth": "easy",
    "registers": (Register.RECALL, Register.CROSS),
    "subtopics": (
        "the four pillars",
        "class against object",
        "encapsulation through accessors",
        "inheritance and the extends relation",
        "compile-time against runtime polymorphism",
        "abstraction as an interface boundary",
        "interface against abstract class",
        "overloading against overriding",
        "extends against implements",
        "the absence of multiple class inheritance",
    ),
    "cross_themes": (
        "a static method is hidden, not overridden",
        "the return type alone does not distinguish an overload",
        "a private method is not inherited, so not overridden",
        "a final method cannot be overridden",
        "constructors overload but never override",
        "null argument between two overloaded reference types",
    ),
    "bank_topics": (
        "OOP & class design",
        "SOLID principles",
        "Design patterns",
    ),
}

_REACT: Area = {
    "name": "React & Frontend",
    # React, SQL and Spring/REST sit equal at 16 because the candidate's report
    # has all three asked in every sitting and there is no evidence to rank them.
    # An invented ranking would be a worse lie than parity.
    "weight": 16,
    "depth": "easy",
    "registers": (Register.RECALL, Register.CROSS, Register.SCENARIO),
    "subtopics": (
        "component as a function of props",
        "functional against class components",
        "useState and the state it holds",
        "useEffect dependencies and cleanup",
        "useRef as DOM handle and as mutable store",
        "Virtual DOM and reconciliation",
        "mount, update, unmount phases",
        "let, var, const scoping",
        "consuming a REST endpoint from a component",
        "PUT against PATCH semantics",
    ),
    "cross_themes": (
        "array index as a key across a reorder",
        "a setState value read back in the same render",
        "a cleanup that never runs because dependencies change every render",
        "useRef mutation does not re-render",
    ),
    # Nothing. There is no React question anywhere in the backend banks — the
    # only occurrences of the word are synonym tokens in the semantic cache.
    "bank_topics": (),
}

_SQL: Area = {
    "name": "SQL & Data Modelling",
    "weight": 16,
    "depth": "medium",
    "registers": (Register.RECALL, Register.CODE_ALOUD, Register.CROSS),
    "subtopics": (
        "SELECT, WHERE, ORDER BY, DISTINCT",
        "GROUP BY with HAVING",
        "aggregate functions",
        "INNER, LEFT, RIGHT joins",
        "FULL OUTER JOIN conceptually",
        "ranking for an nth-highest value",
        "per-group counts and maxima",
        "1NF, 2NF, 3NF and their anomalies",
        "relational against document storage",
    ),
    "cross_themes": (
        "an index that makes a write slower",
        "nth-highest salary when the top salary repeats",
        "HAVING against WHERE on an aggregate",
        "LEFT JOIN row count after filtering the right table",
    ),
    # JDBC and Hibernate are in the bank, but they are data ACCESS, not SQL. A
    # candidate asked to reason about a LEFT JOIN's row count gets nothing from a
    # PreparedStatement question, so claiming them here would be a false claim of
    # offline coverage and would hide this area from `bank_gaps`.
    "bank_topics": (),
}

_SPRING: Area = {
    "name": "Spring Boot & REST",
    "weight": 16,
    "depth": "medium",
    "registers": (Register.RECALL, Register.CROSS, Register.SCENARIO),
    "subtopics": (
        "inversion of control",
        "dependency injection styles",
        "the bean as a managed object",
        "the application context",
        "the stereotype and mapping annotations",
        "running the app and changing the port",
        "HTTP verbs and status codes",
        "the six REST constraints",
        "controller to service to repository to JSON",
    ),
    "cross_themes": (
        "field injection against constructor injection",
        "a bean outside the scanned package",
        "200 returned for a failed operation",
    ),
    "bank_topics": (
        "Spring Boot",
        "Spring REST",
        "REST APIs",
        "Hibernate & JPA",
        "JDBC",
    ),
}

_CODING: Area = {
    "name": "Coding Fundamentals",
    # Smallest at 12, and only CODE_ALOUD. The candidate said "basic coding", and
    # a separate automated coding round already exists in this program — here it
    # is only "say the approach out loud". Deliberately NOT a DSA area: a DSA
    # block would reintroduce the GenC Next shape that the wrong research row was
    # already imposing on this program.
    "weight": 12,
    "depth": "easy",
    "registers": (Register.CODE_ALOUD,),
    "subtopics": (
        "single-pass aggregation over an array",
        "hash map tally for frequency",
        "two-pointer traversal on sorted input",
        "string reversal and palindrome checking",
        "recursion base case and step",
        "linear search against binary search",
        "in-place swap without a temporary",
    ),
    # No CROSS in `registers`, so no themes. A trap needs a stated rule to break,
    # and a dry-run has an answer rather than a rule.
    "cross_themes": (),
    "bank_topics": (),
}

_COGNIZANT_DN_JAVA_FSE: Syllabus = {
    "company": "cognizant",
    "program": "digital-nurture-java-fse",
    "label": "Cognizant Digital Nurture — Java FSE technical interview",
    "kind": InterviewKind.CAMPUS_FUNDAMENTALS.value,
    # None: the campus-fundamentals default mix is right for this program. See
    # the field's comment for when it would not be.
    "shape_mix": None,
    "areas": (_CORE_JAVA, _OOP, _REACT, _SQL, _SPRING, _CODING),
    "code_shapes": (
        "a one-line string transform dry-run aloud",
        "duplicate removal from a small list, aloud",
        "a single pass for a maximum or a count",
        "a hash map tally over characters",
        "a two-pointer or complement pair",
        "a recursion base case stated before the step",
        "a simple sort walked through one iteration",
    ),
    "project_probes": (
        "problem before solution",
        "architecture and where the candidate sat in it",
        "individual contribution separated from team output",
        "a technology choice justified against its alternative",
        "a resume claim taken at its word and tested",
        "the hardest failure and what fixed it",
        "the measurable result",
    ),
    "hr_themes": (
        "relocation willingness",
        "shift and location flexibility",
        "conflict with a teammate",
        "an ethical call under pressure",
        "a lead who was wrong",
        "bond and joining expectations",
    ),
    "sourced": (
        "Structure from the round-by-round interview pattern reference previously "
        "orphaned at knowledge/interview_patterns/cognizant_java_fse.md, plus a "
        "candidate report from a Digital Nurture 5.0 technical interview naming "
        "Java and OOP, React, SQL, Spring Boot and REST, basic coding aloud, the "
        "project and HR, with OOP cross-questions as the characteristic move. "
        "Aptitude is deliberately absent: it is round one, not this round. DSA is "
        "deliberately absent as an area: the report says basic coding, which is a "
        "register over Coding Fundamentals rather than a DSA block."
    ),
    "verified": "2026-08-21",
}

#: Every authored syllabus. Validated at import.
SYLLABI: tuple[Syllabus, ...] = (_COGNIZANT_DN_JAVA_FSE,)

#: Free-text program names, slugified, mapped onto a `SYLLABI` key. Does the job
#: `research_lookup._PROGRAM_ALIASES` does, and carries the entries that table is
#: missing — the absence of any digital-nurture or java-fse alias there is why
#: `find_research` fell through to `rows[0]` and handed this program either GenC's
#: forty-minute viva or GenC Next's three-hour DSA round, at random, over an
#: unordered SELECT.
#:
#: Keyed "company-slug:program-slug" so a program name that means different things
#: at two companies cannot collide. Validated at import: every target must be a
#: real (company, program) pair in `SYLLABI`.
_ALIASES: dict[str, tuple[str, str]] = {
    "cognizant:digital-nurture-java-fse": ("cognizant", "digital-nurture-java-fse"),
    "cognizant:digital-nurture-java-full-stack-engineer": (
        "cognizant",
        "digital-nurture-java-fse",
    ),
    "cognizant:digital-nurture": ("cognizant", "digital-nurture-java-fse"),
    "cognizant:digital-nurture-5-0": ("cognizant", "digital-nurture-java-fse"),
    "cognizant:dn-java-fse": ("cognizant", "digital-nurture-java-fse"),
    "cognizant:java-fse": ("cognizant", "digital-nurture-java-fse"),
    "cognizant:java-full-stack": ("cognizant", "digital-nurture-java-fse"),
    "cognizant:java-full-stack-engineer": ("cognizant", "digital-nurture-java-fse"),
}

#: Focus-term aliases: the words a candidate actually types in the "Anything
#: specific?" box, mapped onto (area name, subtopic or None). Only consulted when
#: the term does not already match an area name or a descriptor, and only honoured
#: when the target area exists in the syllabus being matched — so an alias for
#: React cannot pull a React area into a syllabus that has none.
_FOCUS_ALIASES: dict[str, tuple[str, str | None]] = {
    "oop": ("OOP & Class Design", None),
    "oops": ("OOP & Class Design", None),
    "overriding": ("OOP & Class Design", "overloading against overriding"),
    "overloading": ("OOP & Class Design", "overloading against overriding"),
    "polymorphism": ("OOP & Class Design", "compile-time against runtime polymorphism"),
    "inheritance": ("OOP & Class Design", "inheritance and the extends relation"),
    "abstraction": ("OOP & Class Design", "abstraction as an interface boundary"),
    "encapsulation": ("OOP & Class Design", "encapsulation through accessors"),
    "java": ("Core Java", None),
    "jvm": ("Core Java", "JDK, JRE, JVM boundaries"),
    "collections": ("Core Java", None),
    "multithreading": ("Core Java", "thread creation and lifecycle basics"),
    "threads": ("Core Java", "thread creation and lifecycle basics"),
    "threading": ("Core Java", "thread creation and lifecycle basics"),
    "exceptions": ("Core Java", "checked against unchecked exceptions"),
    "strings": ("Core Java", "String, StringBuilder, StringBuffer"),
    "gc": ("Core Java", "garbage collection and eligibility"),
    "streams": ("Core Java", None),
    "lambdas": ("Core Java", None),
    "react": ("React & Frontend", None),
    "reactjs": ("React & Frontend", None),
    "hooks": ("React & Frontend", "useState and the state it holds"),
    "usestate": ("React & Frontend", "useState and the state it holds"),
    "useeffect": ("React & Frontend", "useEffect dependencies and cleanup"),
    "useref": ("React & Frontend", "useRef as DOM handle and as mutable store"),
    "javascript": ("React & Frontend", "let, var, const scoping"),
    "js": ("React & Frontend", "let, var, const scoping"),
    "frontend": ("React & Frontend", None),
    "sql": ("SQL & Data Modelling", None),
    "joins": ("SQL & Data Modelling", "INNER, LEFT, RIGHT joins"),
    "dbms": ("SQL & Data Modelling", None),
    "normalization": ("SQL & Data Modelling", "1NF, 2NF, 3NF and their anomalies"),
    "normalisation": ("SQL & Data Modelling", "1NF, 2NF, 3NF and their anomalies"),
    "queries": ("SQL & Data Modelling", None),
    "indexing": ("SQL & Data Modelling", None),
    "spring": ("Spring Boot & REST", None),
    "springboot": ("Spring Boot & REST", None),
    "rest": ("Spring Boot & REST", "HTTP verbs and status codes"),
    "api": ("Spring Boot & REST", "HTTP verbs and status codes"),
    "apis": ("Spring Boot & REST", "HTTP verbs and status codes"),
    "jpa": ("Spring Boot & REST", None),
    "hibernate": ("Spring Boot & REST", None),
    "annotations": ("Spring Boot & REST", "the stereotype and mapping annotations"),
    "coding": ("Coding Fundamentals", None),
    "dsa": ("Coding Fundamentals", None),
    "arrays": ("Coding Fundamentals", "single-pass aggregation over an array"),
    "recursion": ("Coding Fundamentals", "recursion base case and step"),
    "algorithms": ("Coding Fundamentals", None),
}


# ─── Validation ───────────────────────────────────────────────────────────────

#: Rounding slack on the area weights, matching `catalogue._WEIGHT_TOLERANCE`. A
#: set summing to 99 is a typo worth failing on; a float a hair off is not.
_WEIGHT_TOTAL = 100.0
_WEIGHT_TOLERANCE = 0.51

#: Word caps. Two of them, one reason each. A descriptor is a noun phrase
#: ("garbage collection and eligibility", four words). A claim needs one
#: subordinate clause ("a static method is hidden, not overridden", seven). Real
#: spoken interview questions in this repo's own bank run twelve to twenty-five
#: words, and the shortest — "What is the difference between the JDK, the JRE and
#: the JVM?" — is twelve, so it dies on the descriptor cap even after its question
#: mark and its interrogative opener are stripped.
_DESCRIPTOR_WORDS = 9
_CLAIM_WORDS = 14

#: The rule that catches the determined sneak. Stripping the question mark and
#: shortening gets past the first two rules; "explain abstract class and
#: interface" is five words with no question mark and dies here.
_QUESTION_OPENERS: frozenset[str] = frozenset(
    {
        "what", "why", "how", "when", "where", "which", "who", "whose",
        "can", "could", "do", "does", "did", "is", "are", "was", "were",
        "will", "would", "should", "shall", "have", "has",
        "name", "list", "explain", "describe", "define", "tell", "give",
        "state", "write", "given", "suppose", "assume", "consider",
        "implement", "find", "print", "return", "compare", "differentiate",
    }
)

#: A question addresses the candidate; a descriptor names a concept. Kills "the
#: difference you must explain".
_SECOND_PERSON: frozenset[str] = frozenset({"you", "your", "yours", "yourself"})

#: Quotes are how a copied question survives de-punctuation — strip the mark from
#: `"can you override a static method?"` and the quotes are what is left of it —
#: and "e.g." is the tell that an example question follows, which is precisely the
#: disease in the old must-cover renderer's `- **{topic}** — e.g. {contents[0]}`.
#: The apostrophe is in the banned set too: no descriptor here needs a possessive,
#: and allowing one would need a rule about where it may appear that is more
#: fragile than rewording.
_BANNED_SUBSTRINGS: tuple[str, ...] = ('"', "'", "“", "”", "‘", "’", "`", "e.g.", "i.e.")

#: Warn, never raise. A date-triggered failure is a time bomb that blocks
#: unrelated work months later and gets deleted rather than fixed.
_STALE_AFTER_DAYS = 548  # ~18 months


def _words(text: str) -> list[str]:
    return [word for word in text.split() if word]


def _check_phrase(text: str, *, where: str, cap: int) -> None:
    """
    Every authored string passes through here at import. See the anti-hardcode
    contract in the module docstring for why each rule exists.
    """
    if not text.strip():
        raise ValueError(f"{where}: empty descriptor")
    if "?" in text:
        raise ValueError(
            f"{where}: contains a question mark — {text!r}. This file holds "
            "descriptors, not questions; a question mark means output was pasted "
            "back into the input."
        )
    for banned in _BANNED_SUBSTRINGS:
        if banned in text.lower():
            raise ValueError(f"{where}: contains {banned!r} — {text!r}")
    if text.rstrip().endswith(":"):
        raise ValueError(f"{where}: ends in a colon, which introduces an example — {text!r}")
    if "```" in text:
        raise ValueError(f"{where}: contains a code fence — {text!r}")

    words = _words(text)
    if len(words) > cap:
        raise ValueError(
            f"{where}: {len(words)} words, cap is {cap} — {text!r}. Past the cap a "
            "descriptor stops describing and starts asking."
        )

    tokens = [re.sub(r"[^a-z0-9-]", "", word.lower()) for word in words]
    if tokens and tokens[0] in _QUESTION_OPENERS:
        raise ValueError(
            f"{where}: opens with the interrogative or imperative {tokens[0]!r} — "
            f"{text!r}. Name the concept instead of asking about it."
        )
    second_person = _SECOND_PERSON.intersection(tokens)
    if second_person:
        raise ValueError(
            f"{where}: addresses the candidate ({sorted(second_person)}) — {text!r}"
        )


def _validate() -> None:
    """
    Fail at import on a malformed syllabus.

    An import-time raise rather than a test, following `domains.py`. A
    mis-weighted or question-carrying syllabus must stop the process starting,
    because the alternative is an interview that renders perfectly and is briefed
    wrongly, and nobody reads the logs of something that appears to work.
    """
    bank_topics = set(_BANK_TOPICS)
    seen_keys: set[tuple[str, str]] = set()

    for syllabus in SYLLABI:
        key = (syllabus["company"], syllabus["program"])
        if key in seen_keys:
            raise ValueError(f"duplicate syllabus for {key}")
        seen_keys.add(key)
        where_root = f"syllabus {key}"

        if not syllabus["areas"]:
            raise ValueError(f"{where_root}: no areas")

        try:
            InterviewKind(syllabus["kind"])
        except ValueError as exc:
            raise ValueError(f"{where_root}: unknown interview kind {syllabus['kind']!r}") from exc

        mix = syllabus["shape_mix"]
        if mix is not None:
            # Through `question_shape.mix_total` rather than `sum(mix.values())`:
            # the six keys are named in exactly one function, so a renamed key is
            # a type error there instead of a silently skipped percentage here.
            total = mix_total(mix)
            if total != 100:
                raise ValueError(f"{where_root}: shape_mix override sums to {total}, expected 100")

        try:
            verified = dt.date.fromisoformat(syllabus["verified"])
        except ValueError as exc:
            raise ValueError(
                f"{where_root}: verified {syllabus['verified']!r} is not an ISO date"
            ) from exc
        age = (dt.date.today() - verified).days
        if age > _STALE_AFTER_DAYS:
            logger.warning(
                "syllabus_stale",
                company=syllabus["company"],
                program=syllabus["program"],
                verified=syllabus["verified"],
                days_old=age,
                note="re-check against candidate reports; not a hard failure by design",
            )

        weight_total = 0.0
        area_names: set[str] = set()
        for area in syllabus["areas"]:
            where = f"{where_root} area {area['name']!r}"
            if area["name"] in area_names:
                raise ValueError(f"{where}: duplicate area name")
            area_names.add(area["name"])
            weight_total += area["weight"]

            if not area["registers"]:
                raise ValueError(f"{where}: no registers — an area nobody can ask is not an area")
            for register in area["registers"]:
                if register not in SUBJECT_REGISTERS:
                    raise ValueError(
                        f"{where}: register {register!r} is not a subject register. PROJECT "
                        "and BEHAVIOURAL are about the candidate, not about an area."
                    )
            if len(set(area["registers"])) != len(area["registers"]):
                raise ValueError(f"{where}: duplicate register")

            if not area["subtopics"]:
                raise ValueError(f"{where}: no subtopics")
            if len(set(area["subtopics"])) != len(area["subtopics"]):
                raise ValueError(f"{where}: duplicate subtopic")
            for subtopic in area["subtopics"]:
                _check_phrase(subtopic, where=f"{where} subtopic", cap=_DESCRIPTOR_WORDS)

            # CROSS in registers and cross_themes must agree in both directions. A
            # CROSS row with no theme has nothing to trap; themes with no CROSS row
            # are dead data that will rot unnoticed.
            has_cross = Register.CROSS in area["registers"]
            if has_cross and not area["cross_themes"]:
                raise ValueError(
                    f"{where}: declares the CROSS register but has no cross_themes to trap with"
                )
            if area["cross_themes"] and not has_cross:
                raise ValueError(
                    f"{where}: has cross_themes but does not declare the CROSS register"
                )
            if len(set(area["cross_themes"])) != len(area["cross_themes"]):
                raise ValueError(f"{where}: duplicate cross theme")
            for theme in area["cross_themes"]:
                _check_phrase(theme, where=f"{where} cross_theme", cap=_CLAIM_WORDS)
                # A theme is a claim about a trap, not a restatement of the topic.
                # An identical string means somebody filled the field to satisfy
                # the schema rather than because they knew a trap.
                if theme in area["subtopics"]:
                    raise ValueError(
                        f"{where}: cross_theme {theme!r} is identical to a subtopic. A theme "
                        "states what goes wrong; a subtopic names the concept."
                    )

            unknown = set(area["bank_topics"]) - bank_topics
            if unknown:
                raise ValueError(
                    f"{where}: bank_topics {sorted(unknown)} are not in "
                    "java_fundamentals.ALL_TOPICS. Renaming a bank topic must break the "
                    "build here rather than silently make this a false claim of offline "
                    "coverage."
                )

        if abs(weight_total - _WEIGHT_TOTAL) > _WEIGHT_TOLERANCE:
            raise ValueError(
                f"{where_root}: area weights sum to {weight_total:g}, expected "
                f"{_WEIGHT_TOTAL:g}. A set summing to 90 does not fail, it silently "
                "under-plans every interview."
            )

        for shape in syllabus["code_shapes"]:
            _check_phrase(shape, where=f"{where_root} code_shape", cap=_CLAIM_WORDS)
            # A concrete input is a problem, not a shape. Two characters of digits
            # is a status code or a normal form; three is an array literal.
            digits = re.search(r"\d{3,}", shape)
            if digits:
                raise ValueError(
                    f"{where_root} code_shape: contains the literal {digits.group()!r} — "
                    f"{shape!r}. A concrete input makes this a problem rather than a shape."
                )
        if not syllabus["code_shapes"] and any(
            Register.CODE_ALOUD in area["registers"] for area in syllabus["areas"]
        ):
            raise ValueError(f"{where_root}: an area declares CODE_ALOUD but there are no shapes")

        for probe in syllabus["project_probes"]:
            _check_phrase(probe, where=f"{where_root} project_probe", cap=_CLAIM_WORDS)
        if not syllabus["project_probes"]:
            raise ValueError(f"{where_root}: no project probes, and every mix allocates project")
        for theme in syllabus["hr_themes"]:
            _check_phrase(theme, where=f"{where_root} hr_theme", cap=_DESCRIPTOR_WORDS)
        if not syllabus["hr_themes"]:
            raise ValueError(f"{where_root}: no HR themes, and every mix allocates HR")

    for alias, target in _ALIASES.items():
        if target not in seen_keys:
            raise ValueError(f"alias {alias!r} points at {target}, which is not in SYLLABI")
        if alias != _alias_key(*target) and not alias.startswith(f"{target[0]}:"):
            raise ValueError(f"alias {alias!r} is not scoped to its company {target[0]!r}")

    # Every focus alias must name a real area, and a real subtopic within it, in
    # at least one syllabus. Otherwise a typo in this table is a focus term that
    # can never match and nobody finds out.
    all_areas = {area["name"]: area for syllabus in SYLLABI for area in syllabus["areas"]}
    # Distinct local names — `aliased_area`, `aliased_subtopic` — rather than
    # reusing `area` and `subtopic` from the loops above. Not cosmetic: those two
    # names are bound to an `Area` and a `str` earlier in this function, and
    # rebinding them to the `| None` results of a lookup is a mypy error. The
    # first argument this module makes for Python over YAML is that mypy covers
    # it, so shipping it mypy-dirty would forfeit the argument.
    for term, (aliased_area_name, aliased_subtopic) in _FOCUS_ALIASES.items():
        if term != _normalise(term):
            raise ValueError(f"focus alias {term!r} is not normalised — it can never match")
        aliased_area = all_areas.get(aliased_area_name)
        if aliased_area is None:
            raise ValueError(f"focus alias {term!r} names unknown area {aliased_area_name!r}")
        if aliased_subtopic is not None and aliased_subtopic not in aliased_area["subtopics"]:
            raise ValueError(
                f"focus alias {term!r} names subtopic {aliased_subtopic!r}, "
                f"absent from {aliased_area_name!r}"
            )


# ─── Slugs and normalisation ──────────────────────────────────────────────────


def _slugify(text: str) -> str:
    """
    Lowercase, non-alphanumerics to single hyphens, trimmed.

    Same shape as `catalogue.subtopic_id`'s, deliberately, so a program name
    slugified here and slugified there produce the same string. Em dashes matter:
    the catalogue's program is literally "Digital Nurture — Java FSE".
    """
    slug = "".join(char if char.isalnum() else "-" for char in text.lower())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def _normalise(text: str) -> str:
    """Free text down to lowercase alphanumerics and single spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _alias_key(company: str, program: str) -> str:
    return f"{_slugify(company)}:{_slugify(program)}"


#: Built once at import. The file is a few kilobytes and never changes at
#: runtime, exactly as the catalogue is parsed once for the same reason.
_INDEX: dict[tuple[str, str], Syllabus] = {}


def _build_index() -> None:
    _INDEX.clear()
    for syllabus in SYLLABI:
        _INDEX[(syllabus["company"], syllabus["program"])] = syllabus


# ─── Resolution ───────────────────────────────────────────────────────────────


def resolve(company: str, program: str) -> Syllabus | None:
    """
    The syllabus for this company and program, or None.

    None is the important return. It means "we have no field research for this
    interview" and the caller must fall back to the existing machinery —
    `domains.topic_block` refined by the company's catalogue weighting — exactly
    as today.

    It must NEVER fall back to another program's syllabus. That is the same class
    of bug as `research_lookup`'s `or rows[0]`, where a Java FSE candidate is
    handed GenC Next's three-hour DSA research and the prompt then calls it the
    primary source of truth. Wrong data wearing a confident label is worse than
    no data.

    Takes no `track_name`. The carrier track cannot reach this decision at all,
    which structurally closes the custom-setup hole for this path rather than
    guarding it with a flag somebody can forget to pass.
    """
    company_slug = _slugify(company)
    if not company_slug:
        return None
    program_slug = _slugify(program)

    # 1. The alias table, which is where the free-text forms land.
    aliased = _ALIASES.get(f"{company_slug}:{program_slug}")
    if aliased is not None:
        found = _INDEX.get(aliased)
        if found is not None:
            return found

    # 2. An exact (company, program) match.
    exact = _INDEX.get((company_slug, program_slug))
    if exact is not None:
        return exact

    # 3. A program-agnostic company row, if one is ever authored. None is today,
    #    and it is the only widening permitted — it says "this is true of every
    #    program at this company", which is a claim somebody had to make on
    #    purpose. A sibling program's syllabus is never such a claim.
    agnostic = _INDEX.get((company_slug, ""))
    if agnostic is not None:
        return agnostic

    return None


def kind_for(syllabus: Syllabus) -> InterviewKind:
    """The syllabus's interview kind as the enum. Validated at import, so no guard."""
    return InterviewKind(syllabus["kind"])


def mix_for(syllabus: Syllabus) -> ShapeMix:
    """
    The shape mix this syllabus actually uses: its override, or its kind's default.

    One accessor rather than `syllabus["shape_mix"] or SHAPE_MIX[...]` at each
    call site, because that expression is easy to write and easy to write
    differently the second time.
    """
    override = syllabus["shape_mix"]
    if override is not None:
        return override
    return SHAPE_MIX[kind_for(syllabus)]


def subtopic_id(syllabus: Syllabus, area: str, subtopic: str) -> str:
    """
    Stable id, e.g.
    "cognizant:digital-nurture-java-fse:oop-class-design:overloading-against-overriding".

    Derived from names, not from list indices, for the reason
    `catalogue.subtopic_id` gives: inserting a subtopic into the middle of a list
    must not silently reassign what every candidate has already been asked. This
    id is persisted against answered questions and compared across sittings, so a
    reassignment would show up as a candidate being asked a "new" subtopic they
    have already had, forever.
    """
    return ":".join(
        (
            _slugify(syllabus["company"]),
            _slugify(syllabus["program"]),
            _slugify(area),
            _slugify(subtopic),
        )
    )


def bank_gaps(syllabus: Syllabus) -> tuple[str, ...]:
    """
    Area names with no offline question coverage (`bank_topics == ()`).

    Read by the fallback planner and the seeder. The syllabus gains React, SQL
    and spoken coding; `java_fundamentals` has none of them; and the fallback is
    what many candidates actually get, because the AI plan times out often enough
    that the orchestrator has a whole path for it.

    Without this function an AI timeout silently downgrades the interview to
    Java-only — the same failure mode as "it said 20 questions and asked me 8",
    which looks like a working feature and is not. With it, the fallback can name
    the areas it could not cover: a reduced interview the candidate knows about
    instead of a complete-looking one that quietly dropped half the syllabus.
    """
    return tuple(area["name"] for area in syllabus["areas"] if not area["bank_topics"])


# ─── Focus matching ───────────────────────────────────────────────────────────

#: Dropped before matching a focus term. Small on purpose: an aggressive list
#: would strip "in", "on" and "of" out of "inversion of control" and start
#: matching things it should not.
_FOCUS_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "the", "of", "on", "in", "to", "for", "with", "about",
        "me", "my", "please", "focus", "more", "some", "also", "topic", "topics",
        "question", "questions", "ask", "asked", "cover", "want", "like",
    }
)


def _content_tokens(text: str) -> list[str]:
    return [token for token in _normalise(text).split() if token not in _FOCUS_STOPWORDS]


def match_focus(syllabus: Syllabus, term: str) -> FocusHit | None:
    """
    Is this focus term on the syllabus, and where?

    Returns ON-SYLLABUS hits ONLY, and deliberately nothing else. Classifying a
    miss as adjacent-but-plausible (Kafka for a Java FSE, which an interviewer
    would happily ask if it were on the CV) or as contradictory (sales in a
    campus technical round) needs the resolved interview kind and
    `domains.is_technical`. Those are the focus allocator's inputs, not this
    file's, and keeping the boundary is what stops this module growing a second
    opinion about what the role is.

    Order of attempts, most specific first, so a term that could match two things
    lands on the narrower one:

      1. the whole term against a subtopic descriptor — a descriptor hit is the
         most precise steer available, because it names one slot's subject;
      2. the term against an area name — broader, and still actionable;
      3. the alias table, whole term then token by token — this is what catches
         "hooks", "oops", "joins" and "multithreading", the words candidates
         actually type, none of which appear verbatim in an area name.
    """
    tokens = _content_tokens(term)
    if not tokens:
        return None
    token_set = set(tokens)

    # 1. Subtopic containment: every content token of the term appears in the
    #    descriptor. "useeffect cleanup" hits "useEffect dependencies and
    #    cleanup"; "sql joins" does not hit "INNER, LEFT, RIGHT joins", because
    #    "sql" is not in it — and that is correct, since "sql joins" is an area
    #    request, which step 2 answers.
    for area in syllabus["areas"]:
        for subtopic in area["subtopics"]:
            if token_set.issubset(set(_content_tokens(subtopic))):
                return FocusHit(term=term, area=area["name"], subtopic=subtopic, how="subtopic")

    # 2. Area name: any distinctive token of the term appears in the area name.
    for area in syllabus["areas"]:
        if token_set & set(_content_tokens(area["name"])):
            return FocusHit(term=term, area=area["name"], subtopic=None, how="area")

    # 3. Aliases. Whole normalised term first — "spring boot" is one alias, not
    #    two — then each token, so "revise my sql joins" still lands.
    area_names = {area["name"] for area in syllabus["areas"]}
    for candidate in [" ".join(tokens), *tokens]:
        alias = _FOCUS_ALIASES.get(candidate.replace(" ", ""))
        if alias is None:
            alias = _FOCUS_ALIASES.get(candidate)
        if alias is None:
            continue
        # Named apart from the `area` and `subtopic` the loops above bind, for
        # the same reason as in `_validate`: rebinding a `str` local to a
        # `str | None` is a type error, and the shadowing also made this branch
        # read as if it were still talking about the subtopic matched in step 1.
        aliased_area_name, aliased_subtopic = alias
        # An alias may only pull an area this syllabus actually has. Otherwise a
        # React alias would conjure a React area into a syllabus without one.
        if aliased_area_name in area_names:
            return FocusHit(
                term=term, area=aliased_area_name, subtopic=aliased_subtopic, how="alias"
            )

    return None


# ─── The grid ─────────────────────────────────────────────────────────────────

#: The order a real interview reaches the registers: warm up on fundamentals,
#: cross-question what was just claimed, ask for code aloud, put a situation, dig
#: into the project, close on HR. Also the render order and the position order,
#: because a plan whose rows are numbered differently from the order they are
#: asked in is a plan two people will read two ways.
_REGISTER_ORDER: tuple[Register, ...] = (
    Register.RECALL,
    Register.CROSS,
    Register.CODE_ALOUD,
    Register.SCENARIO,
    Register.PROJECT,
    Register.BEHAVIOURAL,
)

_DIFFICULTY_ORDER: dict[str, int] = {"easy": 0, "medium": 1}


def _difficulty_for(area: Area, register: Register) -> Difficulty:
    """
    A row's difficulty: easy for a direct recall question, the area's ceiling
    otherwise.

    RECALL is the warm-up and is easy by definition — "the difference between the
    JDK and the JRE" is not a hard question at any depth. Everything else runs at
    the area's declared ceiling, which is why `depth` is on the area: OOP is easy
    even when cross-questioned, and SQL is medium even when merely recalled.
    """
    if register is Register.RECALL:
        return "easy"
    return area["depth"]


def _stems(text: str) -> set[str]:
    """Five-character prefixes of content tokens. A crude stemmer, and enough."""
    return {token[:5] for token in _content_tokens(text)}


def _area_budget(
    syllabus: Syllabus,
    subject_slots: int,
    reserved: Mapping[str, int] | None,
    demand: Mapping[Register, int],
) -> tuple[dict[str, int], dict[str, int]]:
    """
    How many subject slots each area gets, and how many of those the focus bought.

    Three passes, in this order, and the order is the policy:

      1. WEIGHT. Largest remainder over the area weights. This is the interview's
         default shape.
      2. THE CANDIDATE'S FOCUS. `reserved` wins over weight, because the whole
         reported bug is that it did not. Reserved slots are taken from the
         LOWEST-WEIGHTED areas, and — because this function only ever
         redistributes within `subject_slots` — structurally never from the
         introduction, project or HR budget. That is what makes the typed focus
         ADDITIVE to the interview's shape rather than carved out of the parts
         that make it an interview. The must-cover set shrinks at its tail; the
         focus is not "honoured if convenient", which is what it was.
      3. FEASIBILITY. A register is useless if no area holding budget can carry
         it. `demand` is therefore consulted here, not only at placement time.

    Pass 3 exists because of a real defect found in testing. `Register.CODE_ALOUD`
    is carried by only two areas — Coding Fundamentals, which carries nothing
    else, and SQL. At twelve questions both get budget and the code-aloud row
    lands fine. At five questions there are three subject slots, the weight pass
    hands all three to Core Java, OOP and React, and the code-aloud row the mix
    explicitly asked for CANNOT BE PLACED AT ALL: its slot silently became a
    second recall question. That is the same class of bug as the one this whole
    module exists to fix — a mix that says one thing and an interview that does
    another — arriving through the back door at a lower question count. Fixing it
    at placement time is impossible, because by then the budget is spent; it has
    to be fixed in the budget.

    Registers are made feasible scarcest-first (fewest carrying areas), which is
    the order in which starvation actually happens, and topped up from areas
    outside the register's carriers, lowest weight first, never touching a
    reserved area. If no donor is left the register stays unplaceable and
    `_place_registers` fills the slot with the area's most characteristic
    register — a visible degradation, and the honest one, because the alternative
    is a row no model can write.
    """
    weight_by_name = {area["name"]: area["weight"] for area in syllabus["areas"]}
    budget = largest_remainder(dict(weight_by_name), subject_slots)
    if subject_slots <= 0:
        return budget, {}

    focus_counts = _apply_reserved(budget, weight_by_name, subject_slots, reserved)
    _make_registers_feasible(syllabus, budget, weight_by_name, demand, focus_counts)
    return budget, focus_counts


def _steal(
    budget: dict[str, int],
    weight_by_name: Mapping[str, float],
    *,
    into: str,
    protected: frozenset[str],
) -> bool:
    """
    Move one slot into `into` from the lowest-weighted unprotected area that has one.

    Lowest-weighted first because the tail of the distribution is where an
    interview can afford to lose a question, and `protected` is what stops a
    top-up undoing an earlier pass's guarantee.
    """
    donors = sorted(
        (
            donor
            for donor, held in budget.items()
            if donor not in protected and donor != into and held > 0
        ),
        key=lambda donor: (weight_by_name[donor], donor),
    )
    if not donors:
        return False
    budget[donors[0]] -= 1
    budget[into] += 1
    return True


def _apply_reserved(
    budget: dict[str, int],
    weight_by_name: Mapping[str, float],
    subject_slots: int,
    reserved: Mapping[str, int] | None,
) -> dict[str, int]:
    """Pass 2. Returns what the focus actually got, which is not always what it asked."""
    if not reserved:
        return {}

    wanted = {
        name: count
        for name, count in reserved.items()
        if name in weight_by_name and count > 0
    }
    if not wanted:
        return {}

    # Clamp the total ask to the slots that exist. A focus asking for more subject
    # slots than the interview has is not an error to raise on — the candidate
    # typed a sentence, not a configuration — and the allocator upstream already
    # caps it at half the interview.
    granted: dict[str, int] = {}
    taken = 0
    for name in sorted(wanted, key=lambda key: (-wanted[key], key)):
        take = min(wanted[name], subject_slots - taken)
        if take <= 0:
            break
        granted[name] = take
        taken += take

    protected = frozenset(granted)
    for name, count in granted.items():
        while budget[name] < count:
            if not _steal(budget, weight_by_name, into=name, protected=protected):
                break
        # Honesty about what was actually granted: if every donor was exhausted the
        # focus did not get what it asked for, and the review screen must not be
        # told it did.
        granted[name] = min(count, budget[name])

    return {name: count for name, count in granted.items() if count > 0}


def _make_registers_feasible(
    syllabus: Syllabus,
    budget: dict[str, int],
    weight_by_name: Mapping[str, float],
    demand: Mapping[Register, int],
    focus_counts: Mapping[str, int],
) -> None:
    """Pass 3. Mutates `budget` so every demanded register has somewhere to go."""
    carriers = {
        register: tuple(
            area["name"] for area in syllabus["areas"] if register in area["registers"]
        )
        for register in SUBJECT_REGISTERS
    }
    scarcest_first = sorted(
        (register for register in SUBJECT_REGISTERS if demand.get(register, 0) > 0),
        key=lambda register: (len(carriers[register]), -demand[register], register.value),
    )
    for register in scarcest_first:
        homes = carriers[register]
        if not homes:
            continue
        # Only ever guarantee ONE slot per register here, not its full demand. A
        # register with three questions and one carrying area should spread across
        # the syllabus, not commandeer it, and the placement pass distributes the
        # rest if the weights allow. The bug being fixed is a register getting
        # ZERO homes, not a register getting fewer than it wanted.
        if sum(budget[home] for home in homes) > 0:
            continue
        # Into the area that treats this register as most characteristic, so a
        # code-aloud guarantee lands on Coding Fundamentals rather than on SQL.
        by_area = {area["name"]: area for area in syllabus["areas"]}
        target = min(
            homes,
            key=lambda home: (
                by_area[home]["registers"].index(register),
                -by_area[home]["weight"],
                home,
            ),
        )
        protected = frozenset(set(focus_counts) | set(homes))
        _steal(budget, weight_by_name, into=target, protected=protected)


def _place_registers(
    syllabus: Syllabus,
    budget: Mapping[str, int],
    demand: Mapping[Register, int],
) -> list[tuple[Area, Register]]:
    """
    Pair each area slot with a register, respecting `Area.registers`.

    An assignment problem, solved greedily from the CONSTRAINED side: registers
    with the fewest areas willing to carry them are placed first. That ordering
    is what makes a CODE_ALOUD row land on Coding Fundamentals — which carries
    nothing else — rather than on SQL, which can carry one but is not defined by
    it, leaving Coding Fundamentals with a row it cannot legally fill.

    Within a register, areas are preferred that (a) can carry NOTHING ELSE, then
    (b) do not already have a row in this register, so the register spreads across
    the syllabus instead of piling two cross-questions onto one area, then (c)
    treat it as most characteristic (its index in `Area.registers`), then (d)
    weigh more.

    Rule (a) earns its place with a real defect, found by running every question
    count from 4 to 25 and comparing the placed registers against the allocation.
    At sixteen questions Coding Fundamentals holds two budgeted slots and accepts
    only CODE_ALOUD, while the mix asks for two code-aloud rows. Rule (b) alone
    spread them one to Coding Fundamentals and one to SQL — which legally carries
    one — leaving Coding Fundamentals with a slot it could fill only with
    CODE_ALOUD, so the interview came out with three code-aloud rows and one
    cross-question fewer than the mix demanded. A planned cross-question silently
    becoming a third dry-run is the same bug this whole module exists to fix,
    arriving through the back door at a question count nobody tested. Note that
    (a) is deliberately "accepts exactly one register" and not "accepts fewest":
    the general most-constrained-first ordering would send both of OOP's slots to
    RECALL — OOP accepts two registers where Core Java accepts three — and leave
    the area with the most cross-themes in the syllabus without a cross-question,
    which is a worse outcome than the one being fixed.

    If a mix demands more of a register than the syllabus can legally carry, the
    leftover area slots are filled with each area's MOST CHARACTERISTIC register
    rather than emitting an illegal (area, register) pair. That is a visible
    degradation of the mix, and the alternative — a CROSS row on an area with no
    traps — is a question the model cannot write.
    """
    areas = {area["name"]: area for area in syllabus["areas"]}
    free = {name: budget.get(name, 0) for name in areas}
    accepts = {
        register: [area for area in syllabus["areas"] if register in area["registers"]]
        for register in SUBJECT_REGISTERS
    }
    used: dict[tuple[str, Register], int] = {}
    placed: list[tuple[Area, Register]] = []

    register_order = sorted(
        (register for register in SUBJECT_REGISTERS if demand.get(register, 0) > 0),
        key=lambda register: (len(accepts[register]), -demand[register], register.value),
    )
    for register in register_order:
        for _ in range(demand[register]):
            candidates = [area for area in accepts[register] if free[area["name"]] > 0]
            if not candidates:
                break
            candidates.sort(
                key=lambda area: (
                    0 if len(area["registers"]) == 1 else 1,
                    used.get((area["name"], register), 0),
                    area["registers"].index(register),
                    -area["weight"],
                    area["name"],
                )
            )
            chosen = candidates[0]
            free[chosen["name"]] -= 1
            used[(chosen["name"], register)] = used.get((chosen["name"], register), 0) + 1
            placed.append((chosen, register))

    for name, remaining in free.items():
        for _ in range(remaining):
            area = areas[name]
            placed.append((area, area["registers"][0]))

    return placed


def _pick_subtopic(
    syllabus: Syllabus,
    area: Area,
    register: Register,
    covered: frozenset[tuple[str, Register]],
    used: set[str],
    prefer: str | None,
) -> str | None:
    """
    A subtopic for this row: unused in this grid, and not already asked in this
    register in a past sitting.

    `prefer` is a cross theme, on CROSS rows. The subtopic is then chosen by
    crude stem overlap with the theme, so "a static method is hidden, not
    overridden" lands on "static members and initialisation order" rather than on
    whatever happened to be first. Deterministic, and a coherent row beats an
    arbitrary one — but it is only a preference, because nobody has authored a
    theme-to-subtopic mapping and inventing one would be a claim this file cannot
    support.

    If `covered` has exhausted the area, it is RELAXED rather than obeyed: a
    candidate who has worked through every OOP subtopic in this register still
    needs an OOP question, and a repeat in a new session — reworded by the model
    — is far better than a missing row.
    """
    ordered = list(area["subtopics"])
    if prefer is not None:
        theme_stems = _stems(prefer)
        ordered.sort(key=lambda subtopic: -len(theme_stems & _stems(subtopic)))

    def take(honour_covered: bool) -> str | None:
        for subtopic in ordered:
            sid = subtopic_id(syllabus, area["name"], subtopic)
            if sid in used:
                continue
            if honour_covered and (sid, register) in covered:
                continue
            return subtopic
        return None

    return take(True) or take(False)


def plan_grid(
    syllabus: Syllabus,
    question_count: int,
    *,
    mix: ShapeMix | None = None,
    reserved: Mapping[str, int] | None = None,
    covered: frozenset[tuple[str, Register]] = frozenset(),
) -> tuple[Slot, ...]:
    """
    The interview as an integer grid: exactly `question_count - 1` rows, each with
    an area, a register, a difficulty and a subtopic.

    THIS IS THE FIX FOR "MOSTLY SCENARIO QUESTIONS", and it is deliberately a fix
    in Python rather than in prose. `interview_plan.md` used to say "at least two
    thirds scenario-based" and the model obeyed that over every softer
    instruction in the file, because it was the only quantified one. A prompt that
    instead receives eleven numbered rows — three recall, three cross, one
    coding-aloud, one scenario, two project, one HR — cannot drift, because there
    is no proportion left for it to negotiate with. Its remaining freedom is the
    wording, which is exactly the freedom the candidate demanded it keep.

    `question_count - 1` because question 1 is the mandated introduction. Integer
    largest-remainder throughout, never fractions: a model honours "row 4 of 11"
    and argues with "a third of them". Every count derives from the caller's
    `question_count` — in practice `settings.INTERVIEW_QUESTION_COUNT`, default
    12, range 4–25. Writing "3 of 12" as a literal anywhere reintroduces exactly
    the bug `test_the_adaptive_path_uses_the_setting_not_a_hardcoded_number`
    exists to catch: raising the setting moves the dashboard and not the
    interview.

    `reserved` is how the candidate's typed focus lands: {area_name: slots}, from
    the focus allocator. See `_area_budget` for why those slots come from the
    lowest-weighted areas and can never come out of the introduction, project or
    HR budget.

    `covered` is (subtopic_id, register) pairs from the candidate's past sittings.
    A subtopic already asked as RECALL is still available as CROSS — that is "the
    same concept in a genuinely different form", and it is why coverage is keyed
    on the PAIR and not on the subtopic alone. Fifty-seven descriptors times the
    registers their areas permit is 147 distinct forms, against the eight subject
    rows of a twelve-question sitting.

    Deterministic for identical inputs, on purpose. A grid that differed between
    two identical requests would make every test here probabilistic and every bug
    report unreproducible; the variation a candidate should see comes from
    `covered` growing and from the model's wording, not from a shuffle.
    """
    slots_total = max(question_count - 1, 0)
    if slots_total == 0 or not syllabus["areas"]:
        return ()

    effective_mix = mix if mix is not None else mix_for(syllabus)
    counts = allocate(effective_mix, question_count)
    demand = {register: counts.get(register.value, 0) for register in Register}

    subject_slots = sum(demand[register] for register in SUBJECT_REGISTERS)
    budget, focus_counts = _area_budget(syllabus, subject_slots, reserved, demand)
    placed = _place_registers(syllabus, budget, demand)

    # Assign subtopics and themes. Ordered before assignment so that the rows a
    # candidate hears first get first pick of the un-asked subtopics.
    placed.sort(
        key=lambda pair: (
            _REGISTER_ORDER.index(pair[1]),
            _DIFFICULTY_ORDER[_difficulty_for(pair[0], pair[1])],
            -pair[0]["weight"],
            pair[0]["name"],
        )
    )

    used_subtopics: set[str] = set()
    used_themes: set[str] = set()
    focus_remaining = dict(focus_counts)
    rows: list[Slot] = []

    for area, register in placed:
        theme: str | None = None
        if register is Register.CROSS and area["cross_themes"]:
            theme = next(
                (
                    candidate
                    for candidate in area["cross_themes"]
                    if candidate not in used_themes
                ),
                area["cross_themes"][0],
            )
            used_themes.add(theme)

        subtopic = _pick_subtopic(
            syllabus, area, register, covered, used_subtopics, prefer=theme
        )
        sid = None
        if subtopic is not None:
            sid = subtopic_id(syllabus, area["name"], subtopic)
            used_subtopics.add(sid)

        # Attribute the area's first `focus_counts[area]` rows to the focus, so
        # the review screen can tell the candidate which questions their typed
        # request actually bought.
        reason: Literal["weight", "focus", "mandated"] = "weight"
        if focus_remaining.get(area["name"], 0) > 0:
            reason = "focus"
            focus_remaining[area["name"]] -= 1

        rows.append(
            Slot(
                position=0,  # assigned below, once the full order is known
                area=area["name"],
                register=register,
                difficulty=_difficulty_for(area, register),
                subtopic=subtopic,
                subtopic_id=sid,
                theme=theme,
                reason=reason,
            )
        )

    # PROJECT and BEHAVIOURAL last, and with no area: the subject is the
    # candidate, not the syllabus, so steering them onto a topic would be a
    # category error. "mandated" because the mix put them there and no weight or
    # focus can take them away — which is also the guarantee that a focus request
    # cannot eat the project deep-dive.
    for register in (Register.PROJECT, Register.BEHAVIOURAL):
        for _ in range(demand[register]):
            rows.append(
                Slot(
                    position=0,
                    area=None,
                    register=register,
                    difficulty="medium" if register is Register.PROJECT else "easy",
                    subtopic=None,
                    subtopic_id=None,
                    theme=None,
                    reason="mandated",
                )
            )

    return tuple(
        Slot(
            position=index,
            area=row.area,
            register=row.register,
            difficulty=row.difficulty,
            subtopic=row.subtopic,
            subtopic_id=row.subtopic_id,
            theme=row.theme,
            reason=row.reason,
        )
        for index, row in enumerate(rows, start=1)
    )


# ─── Rendering ────────────────────────────────────────────────────────────────

_REGISTER_LABEL: dict[Register, str] = {
    Register.RECALL: "direct question",
    Register.CROSS: "cross-question",
    Register.SCENARIO: "applied situation",
    Register.CODE_ALOUD: "code aloud",
    Register.PROJECT: "project deep-dive",
    Register.BEHAVIOURAL: "HR / behavioural",
}


def render(syllabus: Syllabus, grid: Sequence[Slot]) -> str:
    """
    The `$must_cover` block. THE one renderer, so the plan prompt and the question
    generator stop holding disagreeing opinions about question shape.

    Emits the grid as a numbered table plus, per row, the subtopic descriptor and
    — on a cross-question row — the theme, under a standing instruction that the
    theme is the trap to TEST and must never be restated as the question. This is
    what replaces `interview_plan.md`'s "reuse a handful of the real questions
    where they fit naturally": reuse the topic, the trap and the difficulty, never
    the wording. That old line, paired with a heading reading "questions actually
    asked in past interviews", directly licensed the verbatim reuse the candidate
    forbade.

    Returns a string, not a template. Nothing here is a placeholder, so the
    prompt-caching tests that require the `.md` templates to stay placeholder-free
    are unaffected by what this function produces.
    """
    if not grid:
        return ""

    lines = [
        f"### The interview to run — {syllabus['label']}",
        "",
        "Question 1 is your introduction and is not in this table. The rows below are "
        f"questions 2 to {len(grid) + 1}, in order. Each row fixes the SUBJECT and the "
        "FORM. The wording is yours, and it must be written fresh — do not reuse a "
        "phrasing from anywhere, including from a previous session.",
        "",
        "| # | Subject | Form | Difficulty | Steer |",
        "|---|---|---|---|---|",
    ]
    for slot in grid:
        subject = slot.area or "the candidate"
        steer = slot.theme or slot.subtopic or "—"
        lines.append(
            f"| {slot.position} | {subject} | {_REGISTER_LABEL[slot.register]} "
            f"| {slot.difficulty} | {steer} |"
        )

    present = {slot.register for slot in grid}

    if Register.CROSS in present:
        lines += [
            "",
            "**Cross-question rows.** The steer is a TRAP, written as the claim it "
            "breaks. Ask a question whose honest answer requires knowing it. Never "
            "state the trap, never quote it, never hint at it — the whole value of the "
            "row is that the candidate walks in, and a candidate who was warned learns "
            "nothing. Where the row also names a subtopic, that is the context to ask "
            "it inside.",
        ]
        for slot in grid:
            if slot.register is Register.CROSS and slot.theme:
                context = f" (within: {slot.subtopic})" if slot.subtopic else ""
                lines.append(f"- Row {slot.position} — trap: {slot.theme}{context}")

    if Register.CODE_ALOUD in present and syllabus["code_shapes"]:
        lines += [
            "",
            "**Code-aloud rows.** No editor, sixty seconds, spoken. Ask for the "
            "approach and a dry-run, not a finished program. Invent a small concrete "
            "input yourself; these are the SHAPES to invent one for, not problems to "
            "read out:",
        ]
        lines += [f"- {shape}" for shape in syllabus["code_shapes"]]

    if Register.PROJECT in present and syllabus["project_probes"]:
        lines += [
            "",
            "**Project rows.** The subject is the candidate's own work, so there is no "
            "syllabus topic here. Probe at:",
        ]
        lines += [f"- {probe}" for probe in syllabus["project_probes"]]

    if Register.BEHAVIOURAL in present and syllabus["hr_themes"]:
        lines += [
            "",
            "**HR rows.** Behavioural, about the candidate. Themes:",
        ]
        lines += [f"- {theme}" for theme in syllabus["hr_themes"]]

    focused = [slot for slot in grid if slot.reason == "focus"]
    if focused:
        rows = ", ".join(str(slot.position) for slot in focused)
        lines += [
            "",
            f"**Rows {rows} exist because the candidate asked for them** in their own "
            "words on the setup screen. They are not optional and they are not to be "
            "merged into another row.",
        ]

    gaps = bank_gaps(syllabus)
    if gaps:
        lines += [
            "",
            "Note for the planner: "
            + ", ".join(gaps)
            + " have no offline question bank behind them. Every row on those subjects "
            "has to be written by you, and if you return a short plan those are the "
            "rows that will be missing.",
        ]

    return "\n".join(lines)


_build_index()
_validate()

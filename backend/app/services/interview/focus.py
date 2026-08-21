"""
What the candidate typed into the box — services/interview/focus.py

THE REPORT. A candidate sat a Cognizant Digital Nurture mock, typed their weak areas into
the setup screen's "Anything specific?" box, and said afterwards that the interview was
"not looking at what i have filled in the blocks for additional topics". They were right,
and the box had been decorative for its whole life.

WHY IT WAS IGNORED, WHICH IS THREE SEPARATE THINGS AND NOT ONE.

  1. THE PROMPT GAVE IT ONE CLAUSE. `interview_plan.md` said "Honour the candidate's focus
     request if given.", appended to a paragraph about something else, against two
     concrete instructions in the same file — "Draw the majority of your questions from
     this list" and "Stay inside it." A model resolving that conflict picks the quantified
     side, every time. That half is fixed in the prompt; this module supplies the number
     that makes the focus quantified too.
  2. IT REACHED EXACTLY ONE OF THE FOUR PATHS that produce questions. The AI plan saw it.
     `_fallback_plan` — whose own docstring admits it is "not the rare exception it reads
     as" — never did, nor did `_top_up_plan`, nor the generated-remainder loop. A grid
     built here travels with the plan instead, so the reservation is made once and the
     paths that fill slots inherit it.
  3. `focus_concepts` IS A FALSE FRIEND. That parameter, threaded through
     `question_generator.md` and `_generate_question`, carries concepts the SCORER found
     the candidate missed in earlier answers. It has never carried the typed box. Anyone
     reading the orchestrator for "where does the focus go" finds that name first and
     stops. Hence a module with an unambiguous one.

WHAT THIS FILE DECIDES, AND WHAT IT REFUSES TO.

It decides HOW MANY questions the typed focus is worth and WHICH syllabus areas it lands
on. It does not decide what those questions say — `app/data/syllabus.py` holds the areas
and `app/data/question_shape.py` holds the forms, and neither stores a question sentence.
Nothing here contains interview text either; the reservation is arithmetic and the block
it renders is an instruction, not a question.

THE CEILING IS THREE, AND IT IS A CEILING RATHER THAN A FRACTION. On a twelve-question
interview the introduction, the two project rows and the HR row already claim four slots.
A fourth focus slot would leave the must-cover core with four subject rows — which hollows
out the thing the candidate actually came for in the name of the thing they mentioned. Two
is the floor for the opposite reason: one question is indistinguishable from a passing
mention, which is the complaint.

A MISS IS A MISS. `syllabus.match_focus` returns None rather than the nearest area, so
"go easy on me" reserves nothing and this module says so plainly in the block. Turning
somebody's nerves into a topic list is a worse failure than ignoring the box was.
"""

from __future__ import annotations

import math
import re

from app.data import syllabus as syllabus_data
from app.data.syllabus import FocusHit, Syllabus

#: How the box gets split into candidate subjects.
#:
#: Commas, semicolons, slashes, newlines and the words people join lists with. Deliberately
#: crude: `syllabus.match_focus` is the thing that decides whether a fragment names a real
#: subject, so over-splitting costs a failed match and under-splitting costs a missed one —
#: and only the second is invisible to the candidate.
_SPLIT = re.compile(r"[,;/\n]|\band\b|\balso\b|\bplus\b|&", re.IGNORECASE)

#: Lead-ins people put in front of a topic list. Stripped so "focus on React hooks" and
#: "React hooks" match the same area, rather than the first one failing on a word that
#: carries no subject.
_LEAD_IN = re.compile(
    r"^(?:please\s+)?(?:can\s+you\s+)?(?:i\s+)?"
    r"(?:want|need|would\s+like|prefer|struggle\s+with|am\s+weak\s+(?:in|at)|"
    r"focus(?:\s+on)?|concentrate\s+on|cover|include|ask(?:\s+about)?|test|"
    r"more\s+of|mostly|mainly|especially)\s+",
    re.IGNORECASE,
)

#: The most areas a focus may claim. Beyond this the candidate has not focused on
#: anything — they have listed the syllabus — and spreading two or three slots across six
#: areas buys them one question each in nothing.
_MAX_AREAS = 3


def slots(question_count: int) -> int:
    """
    How many questions the typed focus is guaranteed.

    Derived from `question_count` rather than written as a literal, because
    `INTERVIEW_QUESTION_COUNT` is configurable (4–25) and a hardcoded "3 of 12" is the
    exact shape of a bug this repo already has a test for: raising the setting moved the
    dashboard's promise and not the interview.
    """
    return min(max(2, math.ceil(question_count / 4)), 3)


def terms(text: str) -> list[str]:
    """
    The free-text box as a list of candidate subjects, in the order typed.

    Order is kept because it is the candidate's own ranking: the thing somebody names
    first is the thing they are most worried about, and when the reservation cannot cover
    everything it should cover that.
    """
    out: list[str] = []
    for raw in _SPLIT.split(text or ""):
        fragment = _LEAD_IN.sub("", raw.strip().strip(".!?-–—").strip()).strip()
        if len(fragment) < 2:
            continue
        if fragment.lower() not in {t.lower() for t in out}:
            out.append(fragment)
    return out


def hits(syllabus: Syllabus, text: str) -> list[FocusHit]:
    """
    The typed focus, located on this role's syllabus. Empty when it names no subject.

    De-duplicated BY AREA, not by term: "React hooks, useEffect, virtual DOM" is one
    request for React questions said three ways, and treating it as three would spend the
    whole reservation on one area while looking like it honoured a list.
    """
    found: list[FocusHit] = []
    seen: set[str] = set()
    for term in terms(text):
        hit = syllabus_data.match_focus(syllabus, term)
        if hit is None or hit.area in seen:
            continue
        seen.add(hit.area)
        found.append(hit)
        if len(found) == _MAX_AREAS:
            break
    return found


def reserve(syllabus: Syllabus, text: str, question_count: int) -> dict[str, int]:
    """
    `{area_name: slots}` for `syllabus.plan_grid(reserved=...)`.

    The budget is spread across the matched areas by largest remainder, so two matched
    areas out of three slots gives 2/1 rather than 1/1-and-a-lost-slot. Reuses
    `question_shape.largest_remainder` rather than rounding here: two apportionment rules
    in one codebase is how a grid stops summing to the interview length.
    """
    matched = hits(syllabus, text)
    if not matched:
        return {}
    budget = slots(question_count)
    even = {hit.area: 1.0 for hit in matched}
    from app.data.question_shape import largest_remainder  # noqa: PLC0415

    return {area: n for area, n in largest_remainder(even, budget).items() if n > 0}


def focus_block(
    text: str,
    question_count: int,
    *,
    syllabus: Syllabus | None = None,
) -> str:
    """
    The `$focus_directive` block for `interview_plan.md`. THE one renderer for the box.

    Four cases, and they are genuinely different instructions rather than one instruction
    with adjectives:

      NOTHING TYPED    — say so, in one line. An empty block that the model has to
                         interpret is how "(no specific focus)" became a topic.
      NAMES SUBJECTS   — a guaranteed count, per area, stated as a count. This is the
                         case the whole change exists for.
      NAMES NO SUBJECT — "go easy on me", "I'm nervous". Passed through as pitch, with an
                         explicit instruction NOT to mine it for topics.
      NO SYLLABUS      — a role with no authored syllabus (the domains.py path). The count
                         is still guaranteed, but this module cannot promise the area
                         exists in the brief, so it says that and lets the model check it
                         against the must-cover block rather than asserting something it
                         has not verified.
    """
    typed = (text or "").strip()
    if not typed:
        return (
            "The candidate did not fill in the box. Plan the interview from the must-cover "
            "block alone — do not invent a focus for them."
        )

    quoted = f'They typed, exactly: "{typed}"'
    budget = slots(question_count)

    if syllabus is None:
        return (
            f"{quoted}\n\n"
            f"This role has no authored syllabus, so the areas above came from the role's "
            f"domain rather than from a reported question list. If what they typed names a "
            f"subject this role genuinely covers, **{budget} of the questions below must be "
            f"on it**, additive to the must-cover core. If it names no subject at all, it "
            f"tells you how to pitch the interview and must not be turned into a topic list."
        )

    matched = hits(syllabus, typed)
    if not matched:
        return (
            f"{quoted}\n\n"
            f"That names no subject on this role's syllabus. It is therefore NOT a topic "
            f"list and must not be treated as one: do not reserve questions for it, and do "
            f"not reach outside the must-cover block to satisfy it. Read it as context for "
            f"how to pitch the interview — the difficulty you open at, how much you help — "
            f"and plan the subjects from the must-cover block as normal."
        )

    reserved = reserve(syllabus, typed, question_count)
    lines = []
    for hit in matched:
        count = reserved.get(hit.area, 0)
        if count <= 0:
            continue
        where = f" (they named {hit.subtopic!r})" if hit.subtopic else ""
        lines.append(
            f"- **{count} {'question' if count == 1 else 'questions'} on {hit.area}**"
            f"{where} — because they asked for it, matched on the term "
            f"{hit.term!r} via {hit.how}."
        )
    return (
        f"{quoted}\n\n"
        f"That resolves to real areas on this role's syllabus, so it is a guarantee and "
        f"not a preference. The grid above already carries these rows, marked as the "
        f"candidate's request:\n" + "\n".join(lines) + "\n\n"
        "Those counts are additive to the must-cover core and are already accounted for "
        "in the grid — do not add more on top, and do not drop a must-cover subject to "
        "make room for them."
    )

"""
What is this interview actually for? — services/interview/context.py

ONE ANSWER, FOR EVERYTHING. Reported from a real session, and it is the worst bug this app
has had: a candidate started an interview for a **sales role at Morani Plastics** and the
panel greeted them about an **"Advanced ASE role at Accenture"**, with a code editor open
beside it.

Nothing was broken in the sense of throwing. Two parts of the system simply disagreed about
what the interview was, because there were TWO SOURCES OF TRUTH:

  1. WHAT THE CANDIDATE TYPED. The setup form takes a company and a program as free text —
     "Morani Plastics", "Sales" — and `create_plan` persists both into
     `InterviewSession.session_metadata`. The interview PLAN is built from these, so the
     questions were right.

  2. THE CATALOGUE TRACK the session row points at. `InterviewSession.track_id` is required
     and the setup form preselects `tracks[0]` when the candidate does not pick one, so for
     anybody typing their own company this is an arbitrary IT-services track that has nothing
     to do with what they asked for.

The panel resolved everything from (2): the greeting, the panelists' designations, the
self-rating subject, the pivot topics, and — worst — whether the role is technical, which is
what decides if a code editor appears. So the plan knew it was a sales interview and the room
did not.

THE FIX IS NOT A PATCH AT EACH CALL SITE. Six places asking the same question in six ways is
how the disagreement happened; a seventh would be added the next time somebody needed it.
This module is the single answer, and every consumer reads it.

PRECEDENCE, AND WHY IT IS THIS WAY ROUND. What the candidate typed wins, always. They chose
it deliberately and it is the thing they are preparing for; the track is a dropdown default
they may never have looked at. The track is the fallback for the case that is genuinely
common too — somebody picking "Cognizant GenC" off the catalogue and typing nothing.

`is_technical` IS RESOLVED ONCE AND PERSISTED, not recomputed per request. A candidate must
not see a code editor appear midway through a sales interview because a later keyword match
went differently, and a value on the row is inspectable when somebody asks why their
interview looked the way it did.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data import domains

logger = structlog.get_logger(__name__)

#: Where the resolved technical flag lives on the session.
_TECHNICAL_KEY = "is_technical"


@dataclass(frozen=True)
class InterviewContext:
    """What this interview is for, resolved once and agreed on by everything."""

    #: The employer, as the candidate named it. "Morani Plastics", not the track's company.
    company: str
    #: The role, as the candidate named it. "Sales", not "Advanced ASE".
    role: str
    #: The domain family from data/domains.py — "sales", "software", "hr", …
    domain: str
    #: Whether this role is asked engineering content at all. Decides the code editor, the
    #: coding questions, the code review stage, and the self-rating subject.
    is_technical: bool
    #: True when the role title actually matched a domain rather than falling through to the
    #: default. Callers phrase the brief more strongly on a confident match.
    domain_matched: bool

    @property
    def role_line(self) -> str:
        """One line for a prompt: "Sales at Morani Plastics"."""
        if self.company:
            return f"{self.role} at {self.company}"
        return self.role


#: What to say when there is nothing at all to go on. Deliberately names no technology.
_UNKNOWN_ROLE = "a general fresher role"


async def resolve(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> InterviewContext:
    """
    The one function that answers "what is this interview about".

    Scoped by `user_id` when given, as every read in this app is. Callers that already own the
    session may omit it.

    Never raises. A session that cannot be resolved returns a neutral, non-technical-agnostic
    context rather than an error, because every caller is somewhere in the middle of a live
    interview and none of them can usefully handle an exception.
    """
    from app.models.company import Company, InterviewTrack  # noqa: PLC0415
    from app.models.session import InterviewSession  # noqa: PLC0415

    where = [InterviewSession.id == session_id]
    if user_id is not None:
        where.append(InterviewSession.user_id == user_id)

    row = (
        await db.execute(
            select(
                InterviewSession.session_metadata,
                InterviewTrack.name,
                Company.name,
            )
            .select_from(InterviewSession)
            # OUTER joins: a session whose track was deleted, or a track with no company row,
            # must still resolve from what the candidate typed rather than vanishing.
            .outerjoin(InterviewTrack, InterviewTrack.id == InterviewSession.track_id)
            .outerjoin(Company, Company.id == InterviewTrack.company_id)
            .where(*where)
        )
    ).first()

    if row is None:
        return InterviewContext(
            company="",
            role=_UNKNOWN_ROLE,
            domain=domains.resolve("", ""),
            is_technical=True,
            domain_matched=False,
        )

    meta, track_name, company_name = row
    meta = meta or {}

    # THE PRECEDENCE. What they typed, then the track, then nothing.
    role = (meta.get("program") or "").strip() or (track_name or "").strip() or _UNKNOWN_ROLE
    company = (meta.get("company") or "").strip() or (company_name or "").strip()

    # The focus text is part of how somebody describes their role — "sales, FMCG distribution"
    # typed into the focus box is a strong signal and costs nothing to consider.
    focus = (meta.get("focus") or "").strip()

    domain = domains.resolve(role, focus)
    matched = domains.matched(role, focus)

    # Pinned when the plan was made, if it was. A candidate must not watch a code editor
    # appear halfway through a sales interview because a keyword matched differently on a
    # later request. Falling back to the same rule create_plan uses means an older session
    # with no stored value behaves identically.
    stored = meta.get(_TECHNICAL_KEY)
    is_technical = stored if isinstance(stored, bool) else decide_technical(role, focus)

    return InterviewContext(
        company=company,
        role=role,
        domain=domain,
        is_technical=is_technical,
        domain_matched=matched,
    )


def decide_technical(role: str, focus: str = "") -> bool:
    """
    Is this role asked engineering content?

    UNMATCHED MEANS TECHNICAL, and that asymmetry is deliberate. A missing code editor in a
    technical interview costs the candidate the question they were about to answer; a
    spurious one in a sales interview costs them a glance. When the title is ambiguous —
    "Analyst", "Associate", "Trainee" — the forgiving failure is the one to take.

    A CONFIDENT NON-TECHNICAL MATCH IS RESPECTED ABSOLUTELY. "Sales Executive" resolves to
    the sales domain and gets no editor, no coding questions and no code review, because
    being asked to write Java in a sales interview is not a small annoyance — it tells the
    candidate the simulation does not know what job they applied for.
    """
    if not domains.matched(role, focus):
        return True
    return domains.is_technical(role, focus)

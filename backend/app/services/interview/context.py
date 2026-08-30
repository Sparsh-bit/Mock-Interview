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
from app.services.interview.open_domain import OpenDomain

logger = structlog.get_logger(__name__)

#: Where the resolved technical flag lives on the session.
_TECHNICAL_KEY = "is_technical"

#: Where the generated open-domain profile lives on the session, for a stream the catalogue
#: does not name. See services/interview/open_domain.py.
_OPEN_DOMAIN_KEY = "open_domain"


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
    #: The generated profile for a field the catalogue does not name, pinned at plan time.
    #: None for every curated stream, which is the common case.
    #:
    #: WHY IT LIVES ON THE CONTEXT. Everything that reads it — the panel's designations, the
    #: self-rating subject, the pivot topics — already reads this object for the role and the
    #: technical flag. Giving it a second place to look would be a seventh source of truth in
    #: a module written because there were two.
    open_domain: OpenDomain | None = None

    @property
    def field_label(self) -> str:
        """
        What this interview's field is CALLED, for a log line or a chip.

        The generated label when there is one, the curated domain's label otherwise. One
        property rather than `ctx.open_domain.label if ... else ...` at each call site, which
        is how the two would come to disagree.
        """
        if self.open_domain is not None:
            return self.open_domain.label
        return domains.PROFILES[self.domain]["label"]

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
            open_domain=None,
        )

    meta, track_name, company_name = row
    meta = meta or {}

    typed_role = (meta.get("program") or "").strip()
    typed_company = (meta.get("company") or "").strip()

    # ON A CUSTOM SETUP THE TRACK IS NOT CONSULTED AT ALL.
    #
    # The form must send a track_id whatever happens — InterviewSession.track_id is a non-null
    # foreign key — so "they chose Cognizant Java FSE" and "they typed Morani Plastics while a
    # chip was left selected from a previous visit" arrive looking identical. `custom_setup`
    # is the only thing that tells them apart, and they mean opposite things: in the second
    # case the track is a carrier and reading it is how a sales interview became an Accenture
    # one.
    #
    # Falling back to _UNKNOWN_ROLE rather than the track is deliberate even though it is
    # vaguer. A vague role produces a general interview; the wrong role produces a confident,
    # specific interview for a job the candidate did not apply for, and only one of those is
    # recoverable by the candidate noticing.
    custom = bool(meta.get("custom_setup"))
    if custom:
        role = typed_role or _UNKNOWN_ROLE
        company = typed_company
    else:
        role = typed_role or (track_name or "").strip() or _UNKNOWN_ROLE
        company = typed_company or (company_name or "").strip()

    # The focus text is part of how somebody describes their role — "sales, FMCG distribution"
    # typed into the focus box is a strong signal and costs nothing to consider.
    focus = (meta.get("focus") or "").strip()

    domain = domains.resolve(role, focus)
    matched = domains.matched(role, focus)

    # Pinned when the plan was made, if it was. A candidate must not watch a code editor
    # appear halfway through a sales interview because a keyword matched differently on a
    # later request. Falling back to the same rule create_plan uses means an older session
    # with no stored value behaves identically.
    # Pinned by `create_plan` for a stream the catalogue does not name. Read back rather than
    # regenerated: it cost a model call to resolve, the panel needs it on every turn, and a
    # field that could change mid-interview is the same defect `is_technical` is pinned to
    # avoid. None — including on every session written before this existed — means the
    # curated path, and every caller below behaves exactly as it always has.
    open_profile = OpenDomain.from_metadata(meta.get(_OPEN_DOMAIN_KEY))

    stored = meta.get(_TECHNICAL_KEY)
    if isinstance(stored, bool):
        is_technical = stored
    elif open_profile is not None:
        is_technical = open_profile.is_technical
    else:
        is_technical = decide_technical(role, focus)

    return InterviewContext(
        company=company,
        role=role,
        domain=domain,
        is_technical=is_technical,
        domain_matched=matched,
        open_domain=open_profile,
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

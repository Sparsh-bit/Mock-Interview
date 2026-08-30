"""
Interviews for fields nobody authored — services/interview/open_domain.py

WHAT THIS IS FOR. `data/domains.py` answers "what is this role about" from a hand-written
keyword list, and it is right for every family it names. But the list is finite and the setup
form is free text, so the honest description of what happens outside it is:

    domains.resolve("Sommelier and wine list curation", "")  -> "software"
    domains.matched("Sommelier and wine list curation", "")  -> False

`_DEFAULT = "software"` is a defensible default for a product whose catalogue is campus IT
recruitment, and `matched()` exists precisely so callers can tell the default from a finding.
The trouble is what each caller then does with the finding:

  · `_must_cover_block` writes a paragraph of prose asking the model to infer the role, with
    no topic weighting at all — so the planner allocates twelve questions across nothing.
  · `context.decide_technical` returns **True** for anything unmatched, so a code editor
    opens in front of a sommelier.
  · `panel_for` reads `profile_for`, which falls through to the software profile, so the
    panel is a "Senior Engineering Manager" and a "Technical Lead".
  · `_rating_subject` gives up and asks them to rate "the core skills for this role".
  · `_pivot_order_for` offers a candidate who has just admitted a gap "Programming
    fundamentals, DBMS & SQL, Data structures".

Every one of those is individually reasonable and together they are a software interview
wearing the candidate's job title. That is the same defect `context.py` was written to fix,
reached from the other end: there, six callers disagreed about what the interview was; here,
five callers agree — on the wrong answer.

THE FIX IS TO GO AND FIND OUT, ONCE. The model knows what an air traffic control interview
covers. It has never been asked, because nothing in this codebase had a place to put the
answer. This module asks it, validates the answer into exactly the shape `domains.py` already
publishes, and pins it on the session so the five callers above read one resolved profile
instead of five separate fall-throughs.

FOUR RULES, AND THEY ARE WHAT KEEP THE CURATED PATH SAFE.

  1. THE CATALOGUE WINS, ALWAYS. `resolve` returns None the moment `syllabus.resolve` or
     `domains.matched` has an answer, and it is a hard guard inside this module rather than a
     condition at the call site — a curated stream must be structurally unable to reach a
     generated profile, not merely unlikely to. `tests/test_open_domain.py` asserts the
     generator is never invoked for a curated stream.
  2. NO BLENDING. There is no merge step anywhere here. A session is served by the syllabus
     grid, or by a curated domain profile, or by a generated one — never by two of them
     averaged, because an average of two coherent briefs is one incoherent brief.
  3. FAILING MEANS FAILING TO None. Every failure — provider down, malformed JSON, a
     weighting that is not a distribution — returns None and the caller keeps exactly today's
     behaviour. An open-domain profile is an improvement on a bad default; it is never worth
     costing somebody the interview they paid for.
  4. THE PROFILE IS PINNED, NOT RE-DERIVED. Written into `session_metadata["open_domain"]` at
     plan time, for the same reason `is_technical` is pinned there: a value re-generated per
     request is a value that can change at question seven, and an interview that changed
     shape mid-way is indistinguishable from a bug.

WHY A SEPARATE AI CALL, AND WHY IT IS AFFORDABLE. The obvious alternative is to fold the
characterisation into the plan call that immediately follows it. It cannot be: `is_technical`
has to be resolved BEFORE the plan prompt is built (it is an input to the brief and to whether
a code editor exists), a plan can be served from the semantic cache with no model call at all,
and `_fallback_plan` runs with no model available. The profile is also needed by the panel on
every turn, long after the plan is gone.

What makes it cheap is that a profile is a fact about a FIELD and not about a candidate, so
unlike a plan it is shareable: the Redis entry is keyed on the stream text alone and is read
by every candidate who types anything close to it. It is deliberately NOT keyed on the focus
box — that box invites first-person text ("I struggle with...") and this cache is global, which
is the same leak `orchestrator._is_personal_focus` exists to stop.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

#: How long a generated profile lives in Redis. A week, because the answer to "what does an
#: air traffic control interview cover" does not change on a shorter horizon than that, and a
#: miss costs a candidate a second or two on the path between pressing Start and the plan.
_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

#: Hard ceiling on the call. The output is one small object; anything longer is a model
#: writing prose around it, which fails JSON validation anyway.
_MAX_TOKENS = 700

#: Seconds. This sits on the path between pressing Start and the interview beginning, ahead of
#: the plan call which has its own budget, so it gets a short one. Timing out is not a failure
#: mode that needs handling — it returns None like every other failure and the caller keeps
#: today's behaviour.
_AI_BUDGET_SECONDS = 12.0


@dataclass(frozen=True, slots=True)
class OpenDomain:
    """
    A generated domain, in the shape `domains.DomainProfile` publishes plus the two facts a
    `DomainProfile` does not carry because the curated path derives them elsewhere.

    Frozen, because this is pinned onto the session and read by the panel on every turn. A
    mutable copy handed to five callers is five chances for one of them to edit it.
    """

    label: str
    lead_role: str
    specialist_role: str
    is_technical: bool
    rating_subject: str
    #: (area, weight), weights summing to 100. Same shape as `DomainProfile["topics"]`.
    topics: tuple[tuple[str, int], ...]
    #: Which of those areas is the round about the CANDIDATE rather than the field. Declared
    #: by the model rather than matched on the name — see `schemas.OpenDomainTopic.behavioural`
    #: for why a substring test cannot do this job on free-form names.
    behavioural_area: str = ""

    def topic_block(self) -> str:
        """
        The weighting as markdown bullets.

        Byte-for-byte the same shape `domains.topic_block` and `_company_topic_block` emit, so
        `_must_cover_block` concatenates all three without a second format to reason about.
        """
        lines = "\n".join(
            f"- **{name}** — {weight:g}% of the interview" for name, weight in self.topics
        )
        return f"This is a **{self.label}** role. Cover these areas:\n{lines}"

    def pivot_topics(self) -> list[str]:
        """
        What to offer a candidate who has just said they do not know something, best first.

        Heaviest area first for the same reason the curated path orders by weight: the thing
        the field cares most about is also the thing the candidate is most likely to have
        prepared. The behavioural area is dropped — a pivot is meant to find ground in the
        subject, and "shall we talk about teamwork instead?" reads as giving up on the round.

        DROPPED BY THE MODEL'S OWN FLAG, not by a substring test. The curated filter looks for
        "hr" / "behavioural" / "behavioral" in the name, which works because every profile in
        `domains.py` calls that area "Behavioural & Ownership". A generated profile names it in
        the field's register — "Ownership & Collaboration", "Teamwork & Handover Discipline" —
        and the substring test misses every one of them.
        """
        excluded = self.behavioural_area.strip().lower()
        return [
            name
            for name, _weight in sorted(self.topics, key=lambda t: -t[1])
            if name.strip().lower() != excluded
            # Belt as well as braces, and cheap: a profile pinned before `behavioural_area`
            # existed has an empty one, and the old substring rule is still right whenever it
            # fires. It can only ever remove an area the flag would have removed too.
            and not any(k in name.lower() for k in ("hr", "behavioural", "behavioral"))
        ]

    def to_metadata(self) -> dict[str, Any]:
        """JSONB-safe, for `session_metadata["open_domain"]`."""
        return {
            "label": self.label,
            "lead_role": self.lead_role,
            "specialist_role": self.specialist_role,
            "is_technical": self.is_technical,
            "rating_subject": self.rating_subject,
            "topics": [[name, weight] for name, weight in self.topics],
            "behavioural_area": self.behavioural_area,
        }

    @classmethod
    def from_metadata(cls, raw: Any) -> OpenDomain | None:
        """
        Read a pinned profile back off a session. None for anything malformed.

        Never raises, and that is the point: every caller is somewhere in a live interview and
        none of them can usefully handle an exception. A session written before this feature
        existed, or by a future version with a different shape, simply has no open domain and
        falls back to exactly the behaviour it had.
        """
        if not isinstance(raw, dict):
            return None
        try:
            topics = tuple(
                (str(name), int(weight)) for name, weight in (raw.get("topics") or [])
            )
            if not topics:
                return None
            return cls(
                label=str(raw["label"]),
                lead_role=str(raw["lead_role"]),
                specialist_role=str(raw["specialist_role"]),
                is_technical=bool(raw["is_technical"]),
                rating_subject=str(raw["rating_subject"]),
                topics=topics,
                # Absent on a session pinned before this field existed. Empty is handled by
                # `pivot_topics`, which then falls back to the substring rule.
                behavioural_area=str(raw.get("behavioural_area") or ""),
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("open_domain_metadata_unreadable")
            return None


def _normalise(stream: str) -> str:
    """
    The cache identity of a stream.

    Lower-cased, punctuation-stripped, whitespace-collapsed, so "Sommelier & Wine-List
    Curation" and "sommelier and wine list curation" share one entry. Deliberately crude:
    this is a cache key, and the cost of two near-identical streams missing each other is one
    extra call, while the cost of two genuinely different streams colliding is one candidate
    interviewed for the wrong field.
    """
    text = (stream or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def is_open(stream: str, focus: str = "", program: str = "") -> bool:
    """
    Is this stream outside everything the catalogue authored?

    THE ONE PLACE THAT DECIDES, so a curated stream cannot reach the generated path by a
    caller forgetting a guard. `syllabus.resolve` is not consulted here because it needs a
    company as well and the caller that has one checks it first — see `resolve`.
    """
    from app.data import domains  # noqa: PLC0415

    if not _normalise(stream) and not _normalise(program):
        return False
    return not domains.matched(stream, focus) and not domains.matched(program, focus)


async def resolve(
    stream: str,
    *,
    program: str = "",
    company: str = "",
    focus: str = "",
) -> OpenDomain | None:
    """
    Characterise a stream the catalogue does not name. None when it does name it, or on any
    failure whatsoever.

    `focus` is used ONLY to decide whether the stream matched the catalogue (a candidate who
    typed "Analyst" and focused on "channel sales" has told us it is a sales role, and
    `domains.matched` already reads both). It never reaches the model and never reaches the
    cache key: the box invites personal text and this cache is global.
    """
    from app.data import syllabus as syllabus_data  # noqa: PLC0415

    # THE CATALOGUE WINS. Both halves, in the order the planner applies them.
    if syllabus_data.resolve(company, program) is not None:
        return None
    if not is_open(stream, focus, program):
        return None

    subject = (stream or "").strip() or (program or "").strip()
    key = _cache_key(subject)

    cached = await _read_cache(key)
    if cached is not None:
        return cached

    generated = await _generate(subject)
    if generated is None:
        return None
    await _write_cache(key, generated)
    return generated


def _cache_key(subject: str) -> str:
    from app.db.redis import CacheKeys  # noqa: PLC0415

    digest = hashlib.sha256(_normalise(subject).encode()).hexdigest()[:32]
    return CacheKeys.open_domain_profile(digest)


async def _read_cache(key: str) -> OpenDomain | None:
    """Best effort. A Redis that is down means one extra model call, never a failed start."""
    from app.db.redis import cache_get, get_redis  # noqa: PLC0415

    try:
        raw = await cache_get(get_redis(), key)
    except Exception:  # noqa: BLE001 — Redis unavailable must not reach the candidate
        return None
    if not raw:
        return None
    try:
        return OpenDomain.from_metadata(json.loads(raw))
    except (ValueError, TypeError):
        logger.warning("open_domain_cache_unreadable", key=key)
        return None


async def _write_cache(key: str, profile: OpenDomain) -> None:
    from app.db.redis import cache_set, get_redis  # noqa: PLC0415

    try:
        await cache_set(get_redis(), key, json.dumps(profile.to_metadata()), _CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning("open_domain_cache_write_failed", key=key)


async def _generate(subject: str) -> OpenDomain | None:
    """
    Ask the model what this field's interview covers. None on any failure.

    Schema-validated exactly as strictly as every other structured call in this product —
    `OpenDomainProfile` rejects a weighting that is not a distribution and a topic name that
    is really a question. Being an open-domain path is a reason for MORE validation, not
    less: the curated data was reviewed by a person and this was not.
    """
    import asyncio  # noqa: PLC0415

    from app.core.exceptions import AIProviderUnavailableError  # noqa: PLC0415
    from app.prompts.prompt_loader import get_prompt_loader  # noqa: PLC0415
    from app.services.ai.base_provider import CostTier  # noqa: PLC0415
    from app.services.ai.generate import generate_structured  # noqa: PLC0415
    from app.services.ai.prompt_builder import PromptBuilder  # noqa: PLC0415
    from app.services.ai.schemas import OpenDomainProfile  # noqa: PLC0415

    brief = (
        "## The field to characterise\n\n"
        f"{subject}\n\n"
        "That is what the candidate typed as the stream or role they are preparing for. It is "
        "not on this product's catalogue, which is why you are being asked.\n\n"
        "If what they typed is vague, a course name, or a job advert rather than a field, "
        "characterise the closest real field it plainly refers to rather than inventing a "
        "narrower one.\n\n"
        "Return the profile as JSON now."
    )
    messages = PromptBuilder(get_prompt_loader()).chat_static(
        system_template="open_domain_profile", user_content=brief
    )

    try:
        profile, _ = await asyncio.wait_for(
            generate_structured(
                OpenDomainProfile,
                messages,
                max_tokens=_MAX_TOKENS,
                # Low, deliberately. The question has a right answer — what an interview in
                # this field covers — and creativity here shows up as invented areas.
                temperature=0.2,
                # BALANCED, not CHEAP. This decides whether a code editor appears and what the
                # panel is called; it is the one judgement in the session that every later
                # call inherits, and it is made once per field for everybody.
                cost_tier=CostTier.BALANCED,
                attempts_per_provider=2,
                # A STRING LITERAL, not a constant, and that is a convention rather than an
                # oversight: `tests/test_ai_usage.py` greps every `context="..."` in app/ and
                # fails on a feature the ledger has no label for. A named constant here would
                # hide this call site from that scan and the spend would land unlabelled.
                # Registered in `api/v1/ai_usage.FEATURE_LABELS`.
                context="open_domain_profile",
                # The rules are byte-identical on every call — the field arrives in the user
                # message. See the header of open_domain_profile.md.
                cache_system=True,
            ),
            timeout=_AI_BUDGET_SECONDS,
        )
    except (AIProviderUnavailableError, TimeoutError) as exc:
        logger.warning(
            "open_domain_profile_unavailable",
            subject=subject[:80],
            error_type=type(exc).__name__,
            consequence="planner keeps the unmatched-role fallback brief",
        )
        return None

    resolved = OpenDomain(
        label=profile.label.strip(),
        lead_role=profile.lead_role.strip(),
        specialist_role=profile.specialist_role.strip(),
        is_technical=profile.is_technical,
        rating_subject=profile.rating_subject.strip(),
        topics=tuple((t.name.strip(), t.weight) for t in profile.topics),
        # Exactly one, guaranteed by `OpenDomainProfile._exactly_one_behavioural_area`.
        behavioural_area=next(t.name.strip() for t in profile.topics if t.behavioural),
    )
    logger.info(
        "open_domain_profile_resolved",
        subject=subject[:80],
        label=resolved.label,
        is_technical=resolved.is_technical,
        areas=len(resolved.topics),
    )
    return resolved

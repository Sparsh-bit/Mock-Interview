"""
Who processes this data, and where — services/legal/disclosure.py

The single source of truth for the §5 notice and the §16 cross-border disclosure.

DERIVED FROM THE RUNNING CONFIGURATION, NOT WRITTEN OUT BY HAND, and that is the
whole design. A hand-written list of processors is correct on the day it is written
and wrong the first time somebody flips `AI_PROVIDER` — and a disclosure that names
the wrong country is worse than no disclosure, because it is a statement the
candidate relied on. Here, `active_processors()` reads the same settings the request
path reads, so switching provider changes what the candidate is told. There is a
test that fails if a configured provider has no entry.

WHAT IS A PROCESSOR AND WHAT IS NOT. Only services that receive personal data are
listed. Judge0 receives submitted code, which is the candidate's work product and is
listed. Cloudflare Turnstile receives a challenge token and no personal data, so it
is not.

THE TEXT IN `blurb` IS DRAFT AND IS MARKED AS SUCH EVERYWHERE IT IS SHOWN. It states
facts an engineer can verify from the code — which service, which country, what is
sent. It is NOT the privacy notice, and it does not attempt the parts that are a
lawyer's: the lawful basis, the retention commitment as a promise rather than as a
description, and the §16 position on transfers to China. See docs/COMPLIANCE.md.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

#: Bumped whenever the disclosure or the notice changes in a way a person would want
#: to be asked about again. Stored on every consent row, so a later rewrite cannot
#: silently re-characterise what somebody agreed to.
NOTICE_VERSION = "2026-08-30.1"


@dataclass(frozen=True)
class Processor:
    """One third party that receives personal data, and what it receives."""

    key: str
    name: str
    #: Where the processing happens, in plain words. This is the §16 disclosure.
    country: str
    #: What is actually sent. Specific, because "your data" is not a disclosure.
    receives: str
    #: Why. §5 requires the purpose, not just the recipient.
    purpose: str


#: Every processor this codebase can send personal data to, keyed by the setting
#: value that turns it on. Adding a provider to the factory without adding it here
#: fails `test_data_protection.py`.
_CATALOGUE: dict[str, Processor] = {
    "anthropic": Processor(
        key="anthropic",
        name="Anthropic",
        country="United States",
        receives="Your resume text, your interview answers, and your name",
        purpose="Generating questions, grading answers and writing your report",
    ),
    "glm": Processor(
        key="glm",
        name="ZhipuAI (GLM)",
        # NAMED EXPLICITLY. docs/COMPLIANCE.md flags this as the sharpest §16
        # exposure: DPDP permits transfer except to countries the Government
        # restricts, that list is not yet notified, and it may include China.
        country="China",
        receives="Your resume text, your interview answers, and your name",
        purpose="Generating questions, grading answers and writing your report",
    ),
    "nvidia": Processor(
        key="nvidia",
        name="NVIDIA NIM",
        country="United States",
        receives="Your resume text and your interview answers",
        purpose="Standby model provider when the primary one is unavailable",
    ),
    "elevenlabs": Processor(
        key="elevenlabs",
        name="ElevenLabs",
        country="United States",
        receives="The interviewer's spoken lines. Not your answers, and not your voice",
        purpose="Giving the panel a voice",
    ),
    "fish": Processor(
        key="fish",
        name="Fish Audio",
        country="Singapore",
        receives="The interviewer's spoken lines. Not your answers, and not your voice",
        purpose="Giving the panel a voice",
    ),
    "judge0": Processor(
        key="judge0",
        name="Judge0",
        country="United States / European Union",
        receives="The code you submit in a coding round",
        purpose="Compiling and running your code against the test cases",
    ),
    "piston": Processor(
        key="piston",
        name="Piston (self-hosted)",
        country="Wherever this deployment runs it",
        receives="The code you submit in a coding round",
        purpose="Compiling and running your code against the test cases",
    ),
    "supabase": Processor(
        key="supabase",
        name="Supabase",
        # Replaced from `settings.DATA_REGION` in `active_processors` when it is set. The
        # literal here is the honest fallback, not a placeholder to be filled in by editing
        # this file — see the note on DATA_REGION in core/config.py.
        country="Region not confirmed — see DATA_REGION in the deployment settings",
        receives="Everything: your account, resume file, answers, transcripts and reports",
        purpose="It is the database and the file store",
    ),
    "razorpay": Processor(
        key="razorpay",
        name="Razorpay",
        country="India",
        receives="Your payment details. Card data never reaches this service",
        purpose="Taking payment",
    ),
}


def active_processors() -> list[Processor]:
    """
    The processors this deployment actually sends data to, right now.

    Ordered most-sensitive first, because the model providers are the ones receiving
    the resume and a list a person has to read to the end is a list they will not.
    """
    from app.core.config import settings  # noqa: PLC0415

    keys: list[str] = []

    for value in (settings.AI_PROVIDER, settings.AI_FALLBACK_PROVIDER):
        key = (value or "").strip().lower()
        if key and key not in keys:
            keys.append(key)

    tts = (settings.TTS_PROVIDER or "").strip().lower()
    if tts and tts not in keys:
        keys.append(tts)

    runner = (settings.CODE_EXEC_PROVIDER or "").strip().lower()
    if runner and runner not in keys:
        keys.append(runner)

    # Always true of this deployment, whatever the toggles say.
    keys.extend(["supabase", "razorpay"])

    out: list[Processor] = []
    for key in keys:
        processor = _CATALOGUE.get(key)
        # An unknown key is silently skipped RATHER THAN GUESSED. Inventing an entry
        # would put a made-up country in front of a candidate; the test is what
        # catches the omission, not a runtime placeholder.
        if processor and processor not in out:
            # SUPABASE IS THE ONE ENTRY WHOSE COUNTRY IS A DEPLOYMENT FACT rather than a
            # vendor fact. Anthropic is in the United States for everybody; Supabase is
            # wherever this project's region is, and the repository cannot know it. So it
            # comes from configuration, and says so plainly when unset — see
            # docs/DATA-RESIDENCY.md for why "not confirmed" is the right thing to publish
            # rather than a guess.
            region = (settings.DATA_REGION or "").strip()
            if processor.key == "supabase" and region:
                processor = replace(processor, country=region)
            out.append(processor)
    return out


def leaves_india() -> bool:
    """True when any active processor is outside India. The §16 trigger."""
    return any(p.country != "India" for p in active_processors())


def disclosure() -> dict:
    """
    The whole disclosure, as the API returns it and the upload screen renders it.

    `draft` is part of the payload rather than a comment, so the UI cannot show this
    text without also showing that it has not been through a lawyer.
    """
    from app.core.config import settings  # noqa: PLC0415

    return {
        "notice_version": NOTICE_VERSION,
        "draft": True,
        "processors": [
            {
                "name": p.name,
                "country": p.country,
                "receives": p.receives,
                "purpose": p.purpose,
            }
            for p in active_processors()
        ],
        "leaves_india": leaves_india(),
        "grievance": {
            "role": "Grievance Officer / Data Protection contact",
            "name": settings.DPO_NAME,
            "email": settings.DPO_EMAIL,
            "response_days": settings.GRIEVANCE_RESPONSE_DAYS,
            "configured": bool(settings.DPO_NAME and settings.DPO_EMAIL),
        },
        "retention": RETENTION_SUMMARY,
        "rights": [
            "See everything held about you — Settings, or GET /api/v1/users/me/export",
            "Correct it — Settings",
            "Delete your account and its contents — Settings",
            "Withdraw consent — Settings",
            "Complain to the contact above",
        ],
    }


#: Plain-language retention, mirroring services/legal/retention.py. Kept next to the
#: disclosure because this is the half a candidate reads; that module is the half the
#: code enforces, and a test asserts the two agree.
RETENTION_SUMMARY: list[dict[str, str]] = [
    {
        "what": "Your resume, answers, transcripts and reports",
        "how_long": "Until you delete your account, or until you delete them individually",
    },
    {
        "what": "Payment and credit records",
        "how_long": (
            "Kept for 8 years after the transaction even if you delete your account, "
            "because company law requires it. They are de-identified when you leave: "
            "the amounts remain, your name and account do not"
        ),
    },
    {
        "what": "Security and access logs",
        "how_long": (
            "180 days, as required for reporting cyber incidents. They stop naming "
            "you as soon as your account is deleted"
        ),
    },
]

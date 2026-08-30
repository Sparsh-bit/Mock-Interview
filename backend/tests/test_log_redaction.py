"""
What the log stream is allowed to contain.

TWO AUDITS PRODUCED THIS FILE. The first walked every `logger.*` call in `app/` with an AST
pass and found four real leaks: 120 characters of a CV on a resume parse failure, 100 and 400
characters of raw model output on JSON failures, and the whole parsed response on a schema
failure. All four are fixed at their call sites — a redacted field is safe but useless, and
the useful version is nearly always a length or a reason.

The second is this file, and it exists because fixing four call sites does nothing for the
fifth. `core/logging._redact_pii` enforces the rule on the way out, once, for code that does
not exist yet — and the failure it prevents is silent, because a log line with somebody's CV
in it looks exactly like a log line without one.

THE OTHER HALF OF THE TEST IS THAT REDACTION MUST NOT MAKE THE LOGS USELESS. A processor that
blanks everything passes every "PII absent" assertion and destroys the only tool anybody has
during an incident. `request_id` in particular must survive verbatim: it is echoed in the
`X-Request-ID` response header, so it is the one value a person can quote from a failed
request, and a hashed version would find nothing.
"""

from __future__ import annotations

import pytest

from app.core.logging import _NEVER_REDACT, _redact_pii
from app.core.observability import (
    REDACTED,
    register_sensitive_text,
    reset_sensitive_text,
)

RESUME = (
    "SPARSH GUPTA | sparsh@example.com | +91 98765 43210 | B.Tech CSE 2026 | "
    "Built a payments service handling 4M requests a day."
)
ANSWER = "A HashMap is not thread safe; ConcurrentHashMap is the one to reach for."
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.QWJjRGVmR2hpSktMbW5PcA"
SESSION_ID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_sensitive_text()
    yield
    reset_sensitive_text()


def _log(**fields) -> dict:
    """Run one event dict through the processor, as structlog would."""
    return _redact_pii(None, "info", dict(fields))


# ── The four leaks the audit found ───────────────────────────────────────────


def test_a_resume_preview_does_not_survive():
    # services/resume/extractor.py logged `preview=text[:120]` on a parse failure. The first
    # 120 characters of a CV are the name, the e-mail and the phone number.
    out = _log(event="resume_content_not_a_resume", preview=RESUME[:120], chars=120)
    assert out["preview"] == REDACTED
    assert "SPARSH" not in repr(out)
    # And the field that made the decision is still there.
    assert out["chars"] == 120


def test_raw_model_output_does_not_survive():
    # services/ai/response_parser.py logged `content_preview=content[:400]`. The model's
    # output IS the candidate's report or the panel's assessment of what they said.
    out = _log(event="ai_json_extraction_failed", content_preview=f'{{"summary": "{ANSWER}"}}')
    assert out["content_preview"] == REDACTED
    assert "ConcurrentHashMap" not in repr(out)


def test_a_validation_failures_raw_data_does_not_survive():
    # services/ai/json_validator.py logged `raw_data_preview=str(data)[:300]`.
    out = _log(event="ai_response_validation_failed", raw_data_preview=str({"answer": ANSWER}))
    assert out["raw_data_preview"] == REDACTED


def test_email_addresses_do_not_survive():
    """
    api/v1/auth.py, core/security.py and api/v1/admin.py each logged an address. An e-mail
    identifies a person directly, and a `user_id` on the same line already answers "who".
    """
    out = _log(event="user_signed_in", email="sparsh@example.com", user_id=SESSION_ID)
    assert out["email"] == REDACTED
    out2 = _log(event="note", detail="reached out to sparsh@example.com about it")
    assert "sparsh@example.com" not in out2["detail"]


# ── The general rule, for the call sites that do not exist yet ───────────────


def test_credentials_are_removed_from_any_field():
    # No key name to match on — a token interpolated into a message.
    out = _log(event="auth_failed", detail=f"rejected Bearer {JWT}")
    assert JWT not in out["detail"]


def test_nesting_is_followed():
    # `detail={"answer": ...}` must be caught as surely as `answer=...`.
    out = _log(event="x", detail={"answer": ANSWER, "attempt": 2})
    assert out["detail"]["answer"] == REDACTED
    assert out["detail"]["attempt"] == 2


def test_registered_text_is_removed_wherever_it_lands():
    """
    The vector no key name and no pattern can reach: an answer has no shape. The same
    registry the Sentry scrubber uses — populated where resume text is extracted and where an
    answer is submitted — applies here, so the two cannot drift apart.
    """
    register_sensitive_text(ANSWER)
    out = _log(event="grading_failed", reason=f"could not grade: {ANSWER}")
    assert ANSWER not in out["reason"]
    assert "could not grade" in out["reason"]


def test_bulk_text_is_truncated():
    out = _log(event="x", note="y" * 4000)
    assert len(out["note"]) < 600


def test_the_denylist_is_shared_with_the_sentry_scrubber():
    """
    Two lists of "what counts as personal data here" would drift, and the drift would be
    invisible on both sides.
    """
    from pathlib import Path

    from app.core import logging as log_module
    from app.core.observability import PII_KEY_PARTS

    source = Path(log_module.__file__ or "").read_text()
    assert "redact_log_value" in source
    assert "resume" in PII_KEY_PARTS and "answer" in PII_KEY_PARTS


# ── And the half that keeps the logs worth having ────────────────────────────


def test_the_request_id_survives_verbatim():
    """
    THE ONE THAT KEEPS AN INCIDENT DEBUGGABLE. `request_id` is echoed in the X-Request-ID
    response header, so it is the only value a person can quote from a failed request. A
    hashed version would find nothing in the logs.
    """
    out = _log(event="request_failed", request_id=SESSION_ID)
    assert out["request_id"] == SESSION_ID


def test_identifiers_stay_readable():
    """
    A DELIBERATE JUDGEMENT, not an oversight. user_id and session_id are pseudonymous, they
    are the entire mechanism for triaging an incident, and hashing them buys little against
    an operator who can also read the database — while making the logs unusable for the
    person they exist for. If logs are ever drained to a third party, that party becomes a
    processor and this balance is re-decided; see docs/OBSERVABILITY.md.
    """
    out = _log(event="interview_started", user_id=SESSION_ID, session_id=SESSION_ID)
    assert out["user_id"] == SESSION_ID
    assert out["session_id"] == SESSION_ID


def test_the_event_name_and_level_are_untouched():
    # Redacting the event name would make every log line unsearchable.
    for field in ("event", "level", "logger", "timestamp"):
        assert field in _NEVER_REDACT
    out = _log(event="user_deleted_their_own_account", level="warning")
    assert out["event"] == "user_deleted_their_own_account"


def test_ordinary_operational_fields_are_left_alone():
    out = _log(
        event="ai_call_complete",
        provider="anthropic",
        model="claude-sonnet-5",
        duration_ms=1240,
        input_tokens=3100,
        output_tokens=880,
        cost_usd=0.0184,
        status_code=200,
        cached=True,
    )
    assert out["provider"] == "anthropic"
    assert out["duration_ms"] == 1240
    assert out["input_tokens"] == 3100
    assert out["cost_usd"] == 0.0184
    assert out["cached"] is True


def test_the_processor_is_actually_installed():
    """
    The processor being correct is worth nothing if configure_logging does not use it. It is
    also positioned deliberately — last of the shared processors, before the renderer — so it
    sees everything the others added and applies to console output as well as JSON. A leak
    that only exists on a developer's machine is still a leak, and it is the one that gets
    pasted into a ticket.
    """
    from pathlib import Path

    from app.core import logging as log_module

    source = Path(log_module.__file__ or "").read_text()
    body = source.split("shared_processors: list[Processor] = [")[1].split("]")[0]
    assert "_redact_pii" in body
    assert body.strip().rstrip(",").endswith("_redact_pii")


def test_no_call_site_reintroduces_a_preview_of_candidate_text():
    """
    A GREP GUARD, because the four fixed call sites are the kind that come back. The
    processor makes a reintroduced preview safe; this makes it visible, so the next person
    logs a length instead of shipping a field that is always `[redacted]`.
    """
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    banned = re.compile(
        r"(preview|snippet|excerpt)\s*=\s*(?!len\(|str\(len)", re.I
    )
    for path in app_dir.rglob("*.py"):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if banned.search(line) and "#" not in line.split("=")[0]:
                offenders.append(f"{path.relative_to(app_dir)}:{number}: {line.strip()}")
    assert not offenders, (
        "a `preview=`/`snippet=` field is back in a log call. It will be redacted to "
        "`[redacted]`, which is safe and useless — log a length or a reason instead:\n"
        + "\n".join(offenders)
    )

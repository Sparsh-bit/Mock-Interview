"""
Error tracking, and the proof that it does not export the candidate.

TWO THINGS ARE UNDER TEST HERE and they fail in opposite directions:

  1. That a deliberately-thrown exception in a FastAPI route actually reaches the
     transport. A scrubber that redacts everything, including the event, would pass
     every assertion in the second group while making the tracker useless.
  2. That nothing personal rides along with it. The interesting values are the
     resume text, the answer a candidate gave, the transcript of what they said,
     the bearer token that authenticated them, and the session id.

The Sentry client is built directly and attached to an isolation scope rather than
via `sentry_sdk.init()`, because `init()` installs a process-global client that
would then be live for every test module that runs afterwards.
"""

from __future__ import annotations

from typing import Any

import pytest
import sentry_sdk
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.transport import Transport

from app.core.observability import (
    MAX_STRING_LENGTH,
    MIN_SENSITIVE_LENGTH,
    REDACTED,
    init_sentry,
    register_sensitive_text,
    reset_sensitive_text,
    scrub_breadcrumb,
    scrub_event,
)

RESUME = (
    "SPARSH GUPTA — sparsh@example.com — +91 98765 43210\n"
    "B.Tech CSE, 2026. Built a payments service handling 4M requests/day."
)
ANSWER = "A HashMap is not thread safe, you should use ConcurrentHashMap instead."
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.QWJjRGVmR2hpSktMbW5PcA"
SESSION_ID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


class _Capturing(Transport):
    """Collects envelopes in memory instead of sending them anywhere."""

    def __init__(self) -> None:
        super().__init__({"dsn": "https://public@example.invalid/1"})
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope) -> None:  # noqa: ANN001
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)

    def capture_event(self, event) -> None:  # noqa: ANN001
        self.events.append(event)


@pytest.fixture(autouse=True)
def _clean_registry():
    """The registry is a ContextVar; a leak between tests would fake a pass."""
    reset_sensitive_text()
    yield
    reset_sensitive_text()


def _blob(event: dict[str, Any]) -> str:
    """The whole event flattened to one string, for 'appears nowhere' assertions."""
    return repr(event)


# ── The scrubber, as a pure function ─────────────────────────────────────────


def test_redacts_pii_keys_at_any_depth():
    event = scrub_event(
        {
            "extra": {
                "resume_text": RESUME,
                "candidate_answer": ANSWER,
                "nested": [{"transcript": "I think the answer is B"}],
            },
            "contexts": {"interview": {"session_id": SESSION_ID}},
        }
    )
    blob = _blob(event)
    assert "SPARSH" not in blob
    assert "ConcurrentHashMap" not in blob
    assert "I think the answer is B" not in blob
    assert event["extra"]["resume_text"] == REDACTED
    assert event["extra"]["nested"][0]["transcript"] == REDACTED
    assert event["contexts"]["interview"]["session_id"] == REDACTED


def test_redacts_secrets_that_appear_inside_a_kept_string():
    """
    The case key-based filtering cannot reach: an exception message built by
    interpolation. `ValueError(f"bad token {jwt}")` has no key to match on.
    """
    event = scrub_event(
        {
            "exception": {
                "values": [
                    {
                        "type": "ValueError",
                        "value": (
                            f"rejected Bearer {JWT} for sparsh@example.com "
                            f"on session {SESSION_ID}"
                        ),
                    }
                ]
            }
        }
    )
    value = event["exception"]["values"][0]["value"]
    assert JWT not in value
    assert "sparsh@example.com" not in value
    assert SESSION_ID not in value
    # The exception TYPE survives — the point is to keep the event useful.
    assert event["exception"]["values"][0]["type"] == "ValueError"


def test_uuids_become_a_stable_one_way_handle():
    """
    Session ids leave, but two events about the same session still correlate —
    otherwise 'one user failed 400 times' is indistinguishable from '400 users
    failed once', which is most of what an error tracker is for.
    """
    first = scrub_event({"extra": {"note": f"session {SESSION_ID} failed"}})
    second = scrub_event({"extra": {"note": f"retrying {SESSION_ID}"}})
    other = scrub_event({"extra": {"note": "session 00000000-0000-4000-8000-000000000000 x"}})

    handle = first["extra"]["note"].split("session ")[1].split(" ")[0]
    assert handle.startswith("[uuid:")
    assert handle in second["extra"]["note"]
    assert handle not in other["extra"]["note"]
    assert SESSION_ID not in handle


def test_request_body_headers_and_query_string_are_dropped():
    event = scrub_event(
        {
            "request": {
                "method": "POST",
                "url": f"https://api.example.com/api/v1/interview/{SESSION_ID}/answer",
                "query_string": f"share_token={JWT}",
                "data": {"answer": ANSWER},
                "cookies": {"sb-access-token": JWT},
                "headers": {
                    "Authorization": f"Bearer {JWT}",
                    "X-Session-Token": JWT,
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
            }
        }
    )
    request = event["request"]
    blob = _blob(request)
    assert JWT not in blob
    assert ANSWER not in blob
    assert request["data"] == REDACTED
    assert request["query_string"] == REDACTED
    assert request["cookies"] == REDACTED
    # Headers are an ALLOWLIST — the vendor header nobody thought of is the point.
    assert set(request["headers"]) == {"Content-Type", "User-Agent"}
    # The path survives, with the session id reduced to a handle, so the failing
    # endpoint is still identifiable.
    assert "/api/v1/interview/" in request["url"]
    assert SESSION_ID not in request["url"]


def test_sentry_user_block_is_emptied():
    """
    `id` and `username` are too generic to put on a global key denylist, and Sentry
    fills this block itself, so it is cleared wholesale.
    """
    event = scrub_event({"user": {"id": SESSION_ID, "ip_address": "203.0.113.7"}})
    assert event["user"] == {}


def test_long_strings_are_truncated():
    """Backstop against bulk text riding along in a value whose key matched nothing."""
    event = scrub_event({"extra": {"note": "x" * (MAX_STRING_LENGTH * 3)}})
    assert len(event["extra"]["note"]) < MAX_STRING_LENGTH + 32


def test_http_breadcrumbs_keep_the_shape_and_lose_the_payload():
    """
    The quieter leak. Every call to the model provider becomes a breadcrumb, and
    the prompt we send it contains the resume.
    """
    crumb = scrub_breadcrumb(
        {
            "type": "http",
            "category": "httplib",
            "data": {
                "method": "POST",
                "url": f"https://api.anthropic.com/v1/messages?session={SESSION_ID}",
                "status_code": 500,
                "body": RESUME,
                "reason": "Internal Server Error",
            },
        }
    )
    assert crumb is not None
    blob = _blob(crumb)
    assert "SPARSH" not in blob
    assert SESSION_ID not in blob
    assert crumb["data"]["url"] == "https://api.anthropic.com/v1/messages"
    assert crumb["data"]["status_code"] == 500  # int, not stringified


def test_log_breadcrumbs_are_scrubbed_too():
    crumb = scrub_breadcrumb(
        {
            "type": "default",
            "category": "app.services.resume",
            "message": f"parsed resume for sparsh@example.com session {SESSION_ID}",
            "data": {"resume_text": RESUME},
        }
    )
    assert crumb is not None
    blob = _blob(crumb)
    assert "sparsh@example.com" not in blob
    assert "SPARSH" not in blob
    assert crumb["data"]["resume_text"] == REDACTED


def test_scrubbing_never_drops_the_event():
    """
    A scrubber that returns None would silence the tracker while passing every
    'PII absent' assertion above.
    """
    assert scrub_event({"exception": {"values": [{"type": "RuntimeError"}]}}) is not None
    assert scrub_breadcrumb({"category": "x"}) is not None


# ── End to end: a real exception, through a real client, to a transport ──────


@pytest.fixture()
def captured() -> _Capturing:
    return _Capturing()


def test_a_thrown_exception_is_captured_and_arrives_scrubbed(captured: _Capturing):
    """
    THE ONE THAT PROVES THE WIRING. A route raises with a resume, an answer and a
    token in the exception message and in the scope; the event reaches the
    transport, and none of the three is in it.
    """
    app = FastAPI()
    router = APIRouter()

    @router.get("/boom")
    async def boom():
        raise RuntimeError(f"deliberate test exception: {ANSWER} [{JWT}]")

    app.include_router(router)

    client = sentry_sdk.Client(
        dsn="https://public@example.invalid/1",
        transport=captured,
        include_local_variables=False,
        max_request_body_size="never",
        send_default_pii=False,
        before_send=scrub_event,
        before_breadcrumb=scrub_breadcrumb,
        traces_sample_rate=0.0,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        default_integrations=False,
    )

    # Exactly what POST /interview/{id}/answer does with the submitted content.
    register_sensitive_text(ANSWER)

    with sentry_sdk.isolation_scope() as scope:
        scope.set_client(client)
        scope.set_extra("resume_text", RESUME)
        scope.set_user({"id": SESSION_ID, "email": "sparsh@example.com"})
        with TestClient(app, raise_server_exceptions=False) as http:
            http.get("/boom", headers={"Authorization": f"Bearer {JWT}"})
        client.flush()

    assert captured.events, "the exception never reached the transport"
    event = captured.events[-1]

    # It is the right exception, and it is still identifiable.
    assert event["exception"]["values"][-1]["type"] == "RuntimeError"
    assert "deliberate test exception" in event["exception"]["values"][-1]["value"]

    blob = _blob(event)
    assert JWT not in blob
    assert ANSWER not in blob
    assert "SPARSH" not in blob
    assert "sparsh@example.com" not in blob
    assert SESSION_ID not in blob


def test_local_variables_are_never_attached(captured: _Capturing):
    """
    THE MOST IMPORTANT ONE. Sentry defaults `include_local_variables` to True, and
    in this codebase the local in the frame that raises IS the resume — no
    key-based filter helps when the variable is called `text`.
    """
    client = sentry_sdk.Client(
        dsn="https://public@example.invalid/1",
        transport=captured,
        include_local_variables=False,
        before_send=scrub_event,
        default_integrations=False,
    )

    def parse() -> None:
        text = RESUME  # noqa: F841 — the whole point is that this must not be sent
        raise ValueError("unparseable")

    with sentry_sdk.isolation_scope() as scope:
        scope.set_client(client)
        try:
            parse()
        except ValueError:
            sentry_sdk.capture_exception()
        client.flush()

    assert captured.events
    frames = captured.events[-1]["exception"]["values"][-1]["stacktrace"]["frames"]
    assert frames, "no stacktrace captured"
    assert all("vars" not in frame for frame in frames)
    assert "SPARSH" not in _blob(captured.events[-1])


# ── The registry, for text no pattern can recognise ──────────────────────────


def test_registered_text_is_removed_from_free_text():
    """
    An answer has no shape. Once it has been interpolated into an exception
    message there is nothing in the string that says whose words those are, so it
    is registered at the door instead.
    """
    register_sensitive_text(ANSWER)
    event = scrub_event(
        {"exception": {"values": [{"type": "ValueError", "value": f"could not grade: {ANSWER}"}]}}
    )
    value = event["exception"]["values"][0]["value"]
    assert ANSWER not in value
    assert "could not grade" in value


def test_registered_text_is_removed_before_truncation():
    """
    Order matters: truncating first would leave the first 1024 characters of a
    resume in place, and 1024 characters of a resume is a resume.
    """
    register_sensitive_text(RESUME)
    event = scrub_event({"extra": {"note": RESUME * 40}})
    assert "SPARSH" not in event["extra"]["note"]


def test_registry_ignores_values_too_short_to_be_worth_it():
    """
    Redacting every occurrence of a short string would blank out unrelated words
    in the stack trace and make the event less useful, not more private.
    """
    short = "x" * (MIN_SENSITIVE_LENGTH - 1)
    register_sensitive_text(short, None, 123)  # type: ignore[arg-type]
    event = scrub_event({"extra": {"note": f"saw {short} here"}})
    assert short in event["extra"]["note"]


def test_registry_is_scoped_to_the_current_context():
    """One candidate's answer must never be in scope for another's request."""
    register_sensitive_text(ANSWER)
    assert ANSWER not in scrub_event({"extra": {"n": ANSWER}})["extra"]["n"]
    reset_sensitive_text()
    assert ANSWER in scrub_event({"extra": {"n": ANSWER}})["extra"]["n"]


def test_the_answer_endpoint_registers_the_submitted_content():
    """
    Pinned against the source, because the registration is one line in a handler
    and deleting it would break nothing else. The resume side is pinned the same
    way — that call is the only thing standing between a parse failure and a CV
    in an incident report.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    answers = (root / "api" / "v1" / "interview.py").read_text()
    assert "register_sensitive_text(request.content)" in answers

    extractor = (root / "services" / "resume" / "extractor.py").read_text()
    assert "register_sensitive_text(text)" in extractor


# ── Configuration ────────────────────────────────────────────────────────────


def test_init_is_a_silent_noop_without_a_dsn(monkeypatch, caplog):
    """
    A local machine and CI both legitimately have no DSN. Warning on every boot
    teaches people to ignore warnings.
    """
    from app.core import config

    monkeypatch.setattr(config.settings, "SENTRY_DSN", "", raising=False)
    assert init_sentry() is False
    assert not caplog.records


def test_no_dsn_is_hardcoded():
    """A DSN identifies the project and is configuration, not source."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "app" / "core" / "observability.py"
    assert "ingest.sentry.io" not in source.read_text()

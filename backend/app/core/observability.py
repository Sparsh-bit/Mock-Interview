"""
Error tracking — core/observability.py

Initialises Sentry, and scrubs personal data out of every event before it leaves
the process.

WHY THIS FILE IS MOSTLY SCRUBBING. This application's ordinary working data is
personal data of a kind that must never reach a third-party error tracker: a
candidate's resume, the answers they gave in an interview, the transcript of what
they said out loud, and the bearer token that authenticated them. All four are in
scope for an incident report by default — resume text sits in a local variable in
the frame that raised, the answer is in the request body, and the token is in the
`Authorization` header, all three of which Sentry collects unless told not to.

So the defence is five layers, in order of how much they actually protect:

  1. `include_local_variables=False`. THE MOST IMPORTANT LINE IN THIS FILE. Sentry
     defaults it to True and attaches every local of every stack frame. When
     `services/resume/…` raises, the resume text is a local. No key-based filter
     helps if the local is called `text`, so the collection is turned off rather
     than filtered.
  2. `max_request_body_size="never"`. The request body of `POST /interview/answer`
     IS the candidate's answer.
  3. Key-based redaction, recursively, over the whole event and every breadcrumb
     (`_scrub`). Deliberately over-broad: matching `answer` also matches
     `answers_correct`, and losing a counter is a better failure than keeping a
     transcript.
  4. Pattern-based redaction inside the strings that survive (`_redact_text`), for
     the case the first three cannot reach — an exception *message* built by
     interpolation, e.g. `ValueError(f"unparseable resume: {text}")`. This catches
     tokens, e-mail addresses and UUIDs, which have a recognisable shape.
  5. `register_sensitive_text()`, for the case layer 4 cannot reach: a candidate's
     answer has no recognisable shape. The exact strings are registered where they
     enter the process and removed from anything on its way out. See its docstring.

`scrub_event` and `scrub_breadcrumb` are pure functions taking and returning plain
dicts, so `tests/test_sentry_scrubbing.py` can assert on them directly rather than
asserting on a mock of the SDK.

Nothing here runs unless `SENTRY_DSN` is set. `init_sentry()` on an unconfigured
environment is a silent no-op — not a warning, because a local dev machine and CI
both legitimately have no DSN and a warning on every boot trains people to ignore
warnings.
"""

from __future__ import annotations

import hashlib
import re
from contextvars import ContextVar
from typing import Any, cast

import structlog

logger = structlog.get_logger(__name__)

REDACTED = "[redacted]"

#: Maximum length of any string kept in an event. A backstop against bulk text
#: (a whole resume, a whole transcript) riding along inside a value whose key
#: matched nothing. NOT the primary control — layers 1-3 above are.
MAX_STRING_LENGTH = 1024

#: A key is redacted if any of these appears anywhere in its lower-cased name.
#: Substring rather than exact match, because the same datum is spelled a dozen
#: ways across the codebase (`resume_text`, `resumeText`, `raw_resume`) and an
#: exact list is a list somebody has to remember to extend.
PII_KEY_PARTS: frozenset[str] = frozenset(
    {
        # Credentials and identity
        "authorization",
        "cookie",
        "password",
        "passwd",
        "secret",
        "token",
        "jwt",
        "api_key",
        "apikey",
        "api-key",
        "credential",
        "x-api-key",
        "dsn",
        "signature",
        # The candidate's own words
        "resume",
        "cv_text",
        "answer",
        "response_text",
        "transcript",
        "utterance",
        "speech",
        "audio",
        "message_text",
        "candidate",
        # Free-text CARRIERS. These names say nothing about their contents, which
        # is why they are here: `content` is the field the candidate's answer
        # arrives in (`SubmitAnswerRequest.content`), and `preview` is a 120-char
        # slice of a resume that services/resume/extractor.py logs on a parse
        # failure. Broad on purpose — a redacted `content` counter is cheap.
        "content",
        "preview",
        "snippet",
        "excerpt",
        "prompt",
        "input",
        "feedback",
        "verdict",
        "report_body",
        # Direct identifiers
        "email",
        "phone",
        "full_name",
        "first_name",
        "last_name",
        "address",
        # Correlation handles the brief names explicitly
        "session_id",
        "sessionid",
        "user_id",
        "userid",
    }
)

#: Header names kept verbatim. An allowlist, because the interesting failure mode
#: is a header nobody thought of (`X-Forwarded-Authorization`, a vendor's
#: `X-Session-Token`) rather than one of the handful worth keeping.
SAFE_HEADERS: frozenset[str] = frozenset(
    {"content-type", "content-length", "user-agent", "referer", "accept", "host", "origin"}
)

_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PROVIDER_KEY = re.compile(r"\b(?:sk|rzp|pk)[-_][A-Za-z0-9_-]{12,}")
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _uuid_handle(match: re.Match[str]) -> str:
    """
    Replace a UUID with a stable, one-way handle.

    Session ids and user ids are UUIDs, and they are exactly what the brief says to
    remove. Removing them outright would also remove the ability to tell "one user
    hit this 400 times" from "400 users hit this once", which is most of what an
    error tracker is for. A truncated SHA-256 keeps that: the same session produces
    the same handle in every event, and the handle cannot be turned back into the
    id — 122 bits of UUID entropy is not enumerable.

    It is a correlation token, NOT a lookup key. Nothing may join it back to a row.
    """
    digest = hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()[:8]
    return f"[uuid:{digest}]"


def _redact_text(value: str) -> str:
    """Redact secrets and identifiers that appear inside an otherwise-kept string."""
    # Registered values first: truncation later in this function would otherwise
    # leave a prefix of a resume in place, which is still a resume.
    for secret in _SENSITIVE.get():
        if secret in value:
            value = value.replace(secret, REDACTED)
    value = _JWT.sub(REDACTED, value)
    value = _BEARER.sub(REDACTED, value)
    value = _PROVIDER_KEY.sub(REDACTED, value)
    value = _EMAIL.sub("[email]", value)
    value = _UUID.sub(_uuid_handle, value)
    if len(value) > MAX_STRING_LENGTH:
        value = value[:MAX_STRING_LENGTH] + "…[truncated]"
    return value


def _is_pii_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in PII_KEY_PARTS)


def _scrub(value: Any, depth: int = 0) -> Any:
    """
    Recursively redact PII from an arbitrary JSON-ish structure.

    Depth-limited because Sentry events are nested but finite, and a cycle in a
    hint-attached object would otherwise hang the reporting path — which would turn
    an error into an outage.
    """
    if depth > 12:
        return REDACTED

    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_pii_key(key):
                out[key] = REDACTED
            else:
                out[key] = _scrub(item, depth + 1)
        return out

    if isinstance(value, (list, tuple)):
        scrubbed = [_scrub(item, depth + 1) for item in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed

    if isinstance(value, str):
        return _redact_text(value)

    return value


def _scrub_request(request: dict[str, Any]) -> dict[str, Any]:
    """
    Reduce the request context to what cannot identify anybody.

    The body and the query string go entirely: the body of an answer submission is
    the answer, and query strings on this API carry session ids and share tokens.
    Headers are allowlisted rather than denylisted — see SAFE_HEADERS.
    """
    kept: dict[str, Any] = {}
    if "method" in request:
        kept["method"] = request["method"]
    if "url" in request:
        kept["url"] = _redact_text(str(request["url"]))

    headers = request.get("headers")
    if isinstance(headers, dict):
        kept["headers"] = {
            name: value for name, value in headers.items() if name.lower() in SAFE_HEADERS
        }

    # Recorded so a reader can tell "we dropped this" from "there was none".
    if request.get("data") is not None:
        kept["data"] = REDACTED
    if request.get("query_string"):
        kept["query_string"] = REDACTED
    if request.get("cookies"):
        kept["cookies"] = REDACTED
    return kept


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    `before_send`. Pure: takes an event dict, returns a scrubbed event dict.

    Returning a dict rather than None on every path is deliberate — an exception is
    still worth reporting with its payload removed, and silently dropping events
    would make the tracker lie about how often something fails.
    """
    del hint  # The hint holds the live exception object; nothing is read off it.

    event = _scrub(event)

    if isinstance(event.get("request"), dict):
        event["request"] = _scrub_request(event["request"])

    # `user` is Sentry's own identity block. `id`/`username` do not match the key
    # denylist (they are too generic to denylist globally), and ip_address is set
    # by the server even with send_default_pii off if a header supplies it.
    if isinstance(event.get("user"), dict):
        event["user"] = {}

    return event


def scrub_breadcrumb(
    crumb: dict[str, Any], hint: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """
    `before_breadcrumb`.

    Breadcrumbs are the quieter leak: every outbound HTTP call and every log line
    below ERROR becomes one, so the prompt sent to the model — which contains the
    resume — arrives here rather than in the event itself.
    """
    del hint

    if crumb.get("type") == "http" or crumb.get("category") == "httplib":
        data = crumb.get("data")
        if isinstance(data, dict):
            # Keep only the shape of the call. A URL is enough to know which
            # provider was involved; the payload is not needed and is the resume.
            crumb["data"] = {
                key: _redact_text(value) if isinstance(value, str) else value
                for key, value in data.items()
                if key in {"method", "status_code", "reason"}
            }
            url = data.get("url")
            if url:
                crumb["data"]["url"] = _redact_text(str(url).split("?", 1)[0])

    return _scrub(crumb)


# ── Values that no pattern and no key name can catch ─────────────────────────


_SENSITIVE: ContextVar[tuple[str, ...]] = ContextVar("sentry_sensitive_text", default=())

#: Below this, a registered value is more likely to collide with ordinary prose
#: than to be worth redacting — redacting every occurrence of a 6-character answer
#: would blank out unrelated words in the stack trace.
MIN_SENSITIVE_LENGTH = 24


def register_sensitive_text(*values: str | None) -> None:
    """
    Mark specific strings as never-send, for the current request only.

    THE VECTOR THIS CLOSES. Everything above is structural: a key name, a header
    allowlist, a pattern. None of them can catch a candidate's answer interpolated
    into free text — `ValueError(f"could not grade: {content}")`, or Pydantic
    echoing the offending `input` back inside a validation message. There is no
    signal in the string itself that says "this is somebody's resume".

    So the values are registered at the two places they enter the process — where
    resume text is extracted, and where an answer is submitted — and `_redact_text`
    removes them from anything on its way out, wherever they ended up.

    Scoped to a ContextVar, so it is per-request and per-task: one candidate's
    answer is never in scope while another's request is being handled, and nothing
    accumulates across requests.
    """
    keep = list(_SENSITIVE.get())
    for value in values:
        if isinstance(value, str) and len(value.strip()) >= MIN_SENSITIVE_LENGTH:
            keep.append(value.strip())
    # Longest first, so redacting a whole resume happens before redacting a
    # paragraph of it and leaving the rest behind.
    _SENSITIVE.set(tuple(sorted(set(keep), key=len, reverse=True)))


def reset_sensitive_text() -> None:
    """Drop everything registered in this context. For tests and for the middleware."""
    _SENSITIVE.set(())


# ── The same rules, applied to the log stream ────────────────────────────────


#: Patterns applied to log values. A SUBSET of `_redact_text`'s: log lines keep their UUIDs.
#:
#: `user_id` and `session_id` are the entire mechanism for triaging an incident, they are
#: pseudonymous already, and hashing them buys little against an operator who can also read
#: the database — while making the logs useless to the person they exist for. An e-mail
#: address is different: it identifies a person directly, and a `user_id` on the same line
#: already answers "who". See the docstring on `core/logging._redact_pii`.
def _redact_log_text(value: str) -> str:
    for secret in _SENSITIVE.get():
        if secret in value:
            value = value.replace(secret, REDACTED)
    value = _JWT.sub(REDACTED, value)
    value = _BEARER.sub(REDACTED, value)
    value = _PROVIDER_KEY.sub(REDACTED, value)
    value = _EMAIL.sub("[email]", value)
    if len(value) > MAX_LOG_STRING_LENGTH:
        value = value[:MAX_LOG_STRING_LENGTH] + "…[truncated]"
    return value


#: Shorter than MAX_STRING_LENGTH. A log line is read in a terminal or a search UI, and a
#: 1 KB field pushes everything else off the screen; it is also the backstop against a whole
#: document arriving under a key nobody thought to deny.
MAX_LOG_STRING_LENGTH = 512


def _is_identifier_key(key: str) -> bool:
    """
    True for `user_id`, `session_id`, `resume_id`, `id` — a reference to a row, not content.

    NEEDED BECAUSE THE DENYLIST IS INTENTIONALLY BROAD. `resume_id` contains "resume" and
    `answer_id` contains "answer", so both match `_is_pii_key`, and redacting them would take
    away the only handle anybody has on the thing the log line is about. An id is a
    pseudonymous reference; the content it points at is what the denylist is for.
    """
    lowered = key.lower()
    return lowered == "id" or lowered.endswith(("_id", "_ids", "_uid", "_uuid"))


def redact_log_value(key: str, value: Any, depth: int = 0) -> Any:
    """
    Redact one key/value pair from a log record.

    Takes the KEY as well as the value, because the strongest signal is the field name —
    `preview` and `content` say nothing about their contents, which is exactly why they are
    on the denylist. Structure-aware for the nested case: `detail={"answer": ...}` must be
    caught as surely as `answer=...`.

    TWO EXEMPTIONS FROM THE KEY DENYLIST, both found by the test that asserts redaction does
    not make the logs useless:

      A NON-STRING VALUE IS NEVER REDACTED BY KEY. `input_tokens=3100` matches the denylist
      on "token" and is a count. So does `output_tokens`, `cache_write_tokens`,
      `prompt_tokens` and every other field the AI cost ledger is built from — blanking them
      would leave the spend numbers in docs/AI-COST-MODEL.md underivable. An integer cannot
      be a resume, an answer or a credential, so the key does not need to be consulted.

      AN ID KEY IS NEVER REDACTED BY KEY. See `_is_identifier_key`.
    """
    if depth > 8:
        return REDACTED

    # `isinstance(value, ...)` is part of the condition, not a nested check: only a string
    # or a container can carry content, so a numeric value skips the key rules entirely.
    if (
        isinstance(key, str)
        and _is_pii_key(key)
        and not _is_identifier_key(key)
        and isinstance(value, (str, dict, list, tuple))
    ):
        return REDACTED

    if isinstance(value, dict):
        return {k: redact_log_value(k, v, depth + 1) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        # The key applies to the whole collection, and it has already been cleared above.
        scrubbed = [redact_log_value("", item, depth + 1) for item in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed

    if isinstance(value, str):
        return _redact_log_text(value)

    return value


def init_sentry() -> bool:
    """
    Initialise Sentry if a DSN is configured.

    Returns True when Sentry was initialised, False when it was skipped. Never
    raises: error tracking failing to start must not stop the service from serving.
    """
    from app.core.config import settings  # noqa: PLC0415

    dsn = settings.SENTRY_DSN.strip()
    if not dsn:
        return False

    try:
        import sentry_sdk  # noqa: PLC0415
        from sentry_sdk.integrations.fastapi import FastApiIntegration  # noqa: PLC0415
        from sentry_sdk.integrations.starlette import StarletteIntegration  # noqa: PLC0415

        sentry_sdk.init(
            dsn=dsn,
            environment=settings.ENVIRONMENT,
            release=f"{settings.APP_NAME}@{settings.APP_VERSION}",
            # Layer 1 — see the module docstring. Non-negotiable.
            include_local_variables=False,
            # Layer 2.
            max_request_body_size="never",
            send_default_pii=False,
            # Layers 3 and 4.
            # `cast` because the SDK types these as taking its `Event` /
            # `Breadcrumb` TypedDicts, and a TypedDict is not assignable to
            # `dict[str, Any]` in either direction. The scrubbers are deliberately
            # plain-dict functions so the tests can call them with literals rather
            # than having to construct a TypedDict.
            before_send=cast(Any, scrub_event),
            before_breadcrumb=cast(Any, scrub_breadcrumb),
            # Performance tracing off. It is a separate cost centre, it samples
            # spans whose descriptions carry query text, and nothing is asking for
            # it yet. Turn it on deliberately, with its own scrubbing review.
            traces_sample_rate=0.0,
            profiles_sample_rate=0.0,
            integrations=[
                StarletteIntegration(transaction_style="endpoint"),
                FastApiIntegration(transaction_style="endpoint"),
            ],
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("sentry_init_failed", error=str(exc))
        return False

    logger.info("sentry_initialised", environment=settings.ENVIRONMENT)
    return True

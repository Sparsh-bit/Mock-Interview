"""
A pasted CORS_ORIGINS cannot kill the container — tests/test_cors_origins_parsing.py

THE OUTAGE THIS COMES FROM, reproduced in a container before being fixed.

`CORS_ORIGINS: list[str]` is a COMPLEX field, so pydantic-settings JSON-decodes it inside
`EnvSettingsSource.prepare_field_value` — before any validator of ours runs, and before
`main.py` has configured structlog. A value that is not clean JSON therefore does not produce
a validation message, it produces this, at import:

    json.decoder.JSONDecodeError: Expecting value: line 1 column 2 (char 1)
    pydantic_settings.exceptions.SettingsError: error parsing value for field
      "CORS_ORIGINS" from source "EnvSettingsSource"

The container exits instantly with a raw traceback and NO structured logging. Downstream:
the platform reports the deployment unhealthy, the edge answers 502 with
`x-railway-fallback: true`, and the browser reports every request as
"blocked by CORS policy: No Access-Control-Allow-Origin" — because a 502 page carries no CORS
headers. Four symptoms, none of them adjacent to a malformed environment variable, and the one
log line that would have said so is above everything anyone thinks to scroll to.

MEASURED IN A CONTAINER: of the four shapes a person plausibly pastes, ONE booted.

    ["https://a"]              PASS
    [\\"https://a\\"]            CRASH   <- how a dashboard/CLI commonly DISPLAYS it
    "["https://a"]"            CRASH   <- copied with its surrounding quotes
    https://a,https://b        CRASH   <- the obvious guess

WHY TOLERANCE IS THE RIGHT ANSWER AND NOT LAXNESS. Every one of those four is unambiguous
about intent — they are all "these origins". Refusing three of them buys no safety; it only
moves the failure to the worst possible place, which is a production boot with no diagnosis.
Nothing here widens what is ALLOWED: the parsed result is still an explicit allowlist, and a
value that genuinely cannot be read still fails — but now by name, with the accepted forms
printed, at the layer that can say so.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings

BASE = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@h:6543/db",
    "SUPABASE_URL": "https://x.supabase.co",
    "SUPABASE_ANON_KEY": "k",
    "SUPABASE_SERVICE_KEY": "k",
    "SUPABASE_JWT_SECRET": "not-the-placeholder",
}


def _origins(raw):
    return Settings(**{**BASE, "CORS_ORIGINS": raw}).CORS_ORIGINS


ONE = ["https://interviewos.net.in"]
TWO = ["https://interviewos.net.in", "https://www.interviewos.net.in"]


class TestTheShapesPeopleActuallyPaste:
    def test_plain_json(self):
        assert _origins('["https://interviewos.net.in"]') == ONE

    def test_backslash_escaped_json(self):
        """How a dashboard or `railway variables` output commonly renders it."""
        assert _origins('[\\"https://interviewos.net.in\\"]') == ONE

    def test_json_copied_with_its_surrounding_quotes(self):
        assert _origins('"["https://interviewos.net.in"]"') == ONE

    def test_single_quoted_json(self):
        # Shell quoting that survived a copy-paste out of a runbook.
        assert _origins('\'["https://interviewos.net.in"]\'') == ONE

    def test_comma_separated(self):
        assert _origins("https://interviewos.net.in,https://www.interviewos.net.in") == TWO

    def test_comma_separated_with_spaces(self):
        assert _origins(" https://interviewos.net.in , https://www.interviewos.net.in ") == TWO

    def test_a_single_bare_origin(self):
        assert _origins("https://interviewos.net.in") == ONE

    def test_an_actual_list_is_untouched(self):
        assert _origins(TWO) == TWO

    def test_multiple_origins_json_all_survive(self):
        assert _origins('[\\"https://a.dev\\",\\"https://b.dev\\",\\"https://c.dev\\"]') == [
            "https://a.dev",
            "https://b.dev",
            "https://c.dev",
        ]


class TestItDoesNotBecomeLax:
    def test_it_never_produces_a_wildcard(self):
        """
        THE VACUITY GUARD, and the one that matters. Tolerance about SHAPE must never become
        tolerance about SCOPE: a parser that fell back to allowing everything would turn a
        crash into a silent security hole, which is strictly worse.
        """
        for raw in ('["https://a.dev"]', "https://a.dev", '[\\"https://a.dev\\"]'):
            assert "*" not in _origins(raw)

    def test_empty_means_empty_not_everything(self):
        assert _origins("") == []
        assert _origins("[]") == []

    def test_junk_still_fails_but_by_name(self):
        """
        A value nobody can read must still fail. The requirement is that it fails LEGIBLY —
        naming the variable and the accepted forms — rather than as a JSONDecodeError from
        inside the settings source.
        """
        with pytest.raises(ValueError) as exc:
            _origins("{not: valid, at: all")
        message = str(exc.value)
        assert "CORS_ORIGINS" in message
        assert "JSON" in message or "comma" in message

    def test_blank_entries_are_dropped_not_kept_as_empty_origins(self):
        # An empty string in an allowlist matches nothing but looks like an entry.
        assert _origins("https://a.dev,,https://b.dev") == ["https://a.dev", "https://b.dev"]

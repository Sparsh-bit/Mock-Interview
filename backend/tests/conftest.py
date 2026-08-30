"""
Pytest configuration — tests/conftest.py

CRITICAL: this runs before any test module (and therefore before
`app.db.session` builds its engine), so it repoints the database at a
DEDICATED test database. The integration tests TRUNCATE/DROP schema between
runs; without this they would wipe the shared dev database out from under a
running dev server, causing exactly the transient CORS/500 failures that
looks like broken app but is really the tables vanishing mid-request.

Override the target with TEST_DATABASE_URL; otherwise it derives an
`interviewos_test` database next to whatever DATABASE_URL points at.
"""

import os

import pytest as _pytest

_test_url = os.environ.get("TEST_DATABASE_URL")
if not _test_url:
    base = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://interviewos:password@localhost:5433/interviewos_dev"
    )
    # Swap the database name for the test one, keeping host/creds/driver.
    if "/" in base:
        base = base.rsplit("/", 1)[0]
    _test_url = f"{base}/interviewos_test"

os.environ["DATABASE_URL"] = _test_url
# Mark the environment so any test-only behavior (e.g. prompt cache bypass)
# can key off it.
os.environ.setdefault("TESTING", "true")


# ─── Tests that need a service we do not have in CI ──────────────────────────
#
# A handful of tests genuinely talk to Supabase over the network — listing storage buckets,
# deleting a login through the auth admin API. They pass on a developer's machine because
# `.env` holds real credentials, and they cannot pass in CI, which has placeholders.
#
# TWO OF THEM ALREADY GUARDED THIS, with `skipif(settings.SUPABASE_SERVICE_KEY ==
# "your-service-role-key")` — matching the one exact literal `.env.example` ships. That works
# only if every other environment uses that same literal, and the first CI config I wrote used
# `placeholder-service-key` instead, so the guards did not fire and the tests failed rather
# than skipping. Four more had no guard at all.
#
# So the question "is this a real credential?" is answered here, once, rather than by an
# equality check against a string that each caller has to remember. CI sets the `.env.example`
# values and every one of these skips for the same stated reason.
#
# THESE SKIPS ARE NOT A WAY TO GET CI GREEN. They mark tests that require a live external
# service, which is a different category from a test that is failing. Anything that can be
# checked without the network belongs outside this marker.



def _is_placeholder(value: str | None) -> bool:
    """True when a setting holds an obvious stand-in rather than a real credential."""
    if not value:
        return True
    v = value.strip().lower()
    return v.startswith(("your-", "placeholder")) or "your-project" in v


def _live_supabase() -> bool:
    from app.core.config import settings  # noqa: PLC0415 — after conftest sets the env

    return not (
        _is_placeholder(settings.SUPABASE_SERVICE_KEY) or _is_placeholder(settings.SUPABASE_URL)
    )


def _live_ai() -> bool:
    from app.core.config import settings  # noqa: PLC0415

    return not (
        _is_placeholder(settings.ANTHROPIC_API_KEY) and _is_placeholder(settings.GLM_API_KEY)
    )


#: Decorate a test that makes a real network call to Supabase.
requires_live_supabase = _pytest.mark.skipif(
    not _live_supabase(),
    reason="needs real Supabase credentials — this test makes a live network call",
)

#: Decorate a test that spends real money on a real model call.
requires_live_ai = _pytest.mark.skipif(
    not _live_ai(),
    reason="needs a real AI provider key — this test makes a live model call",
)

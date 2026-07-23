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

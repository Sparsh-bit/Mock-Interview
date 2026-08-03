"""
Every public table must have Row Level Security enabled.

WHY THIS TEST EXISTS. Supabase auto-exposes every table in the `public` schema
through its PostgREST API, authenticated with the anon key — and the anon key is
not a secret, it ships inside the browser bundle to every visitor. With RLS off
there is nothing at all between that key and the table.

Migration 002 enabled RLS on the seventeen tables that existed then. Migrations
003 and 004 remembered to extend it. Migrations 009 and 011 did not, and the gap
was only caught weeks later by Supabase's advisor — by which point `ai_usage` was
provably insertable and deletable by any visitor.

That is a process failure, not a coding mistake: nothing in the codebase connected
"I added a table" to "I must enable RLS on it". This test is that connection. It
reads the models for the list of tables and the migrations for the list of
protected ones, so a new table fails the suite until it is covered.

It is intentionally source-based rather than a live database query. A test that
needs a Supabase connection does not run in CI or on a laptop, which is precisely
where this needs to fail — the whole point is to catch the omission before it
reaches production, not to confirm afterwards that production is wrong.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app import models as _register  # noqa: F401 — registers every mapper
from app.models.base import Base

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "database" / "migrations" / "versions"


def _tables_in_models() -> set[str]:
    """Every table the application defines, from SQLAlchemy's metadata."""
    return set(Base.metadata.tables)


def _tables_with_rls() -> set[str]:
    """
    Every table any migration enables RLS on.

    Matches both the direct form and the loop-over-a-list form used by 002 and
    012, by pulling table names out of `_TABLES = [...]` blocks in files that also
    contain an ENABLE ROW LEVEL SECURITY statement.
    """
    enabled: set[str] = set()
    for path in MIGRATIONS.glob("*.py"):
        src = path.read_text()
        if "ENABLE ROW LEVEL SECURITY" not in src:
            continue

        # Direct: ALTER TABLE public.foo ENABLE ROW LEVEL SECURITY
        enabled |= set(
            re.findall(
                r"ALTER TABLE (?:public\.)?(\w+) ENABLE ROW LEVEL SECURITY",
                src,
            )
        )

        # Interpolated over a list: for table in _TABLES: ... {table} ...
        #
        # The optional `: list[str]` matters — 002 writes `_TABLES = [` and 012
        # writes the same, but an annotated form would have two `=` signs. An
        # earlier version of this regex required two and therefore matched
        # neither, which made every table look uncovered.
        if "{table}" in src:
            for block in re.findall(r"_TABLES(?:\s*:[^=]*?)?\s*=\s*\[(.*?)\]", src, re.S):
                enabled |= set(re.findall(r'"(\w+)"', block))

    return enabled


class TestRLSCoverage:
    def test_the_scanner_actually_finds_something(self):
        """
        Guards the test below from passing vacuously. If the migration format
        changes and the regexes stop matching, this fails loudly instead of the
        coverage test silently reporting that everything is fine.
        """
        found = _tables_with_rls()
        assert len(found) >= 15, (
            f"only found RLS statements for {len(found)} tables — the migration "
            "scanner has probably stopped matching. Fix the scanner before "
            "trusting the coverage test."
        )

    def test_every_model_table_has_rls_enabled_somewhere(self):
        missing = sorted(_tables_in_models() - _tables_with_rls() - {"alembic_version"})
        assert not missing, (
            "These tables have no migration enabling Row Level Security:\n  "
            + "\n  ".join(missing)
            + "\n\nSupabase exposes every public table through PostgREST using the "
            "anon key, which ships in the browser bundle. Without RLS these are "
            "readable and writable by any visitor. Add them to a migration that "
            "runs `ALTER TABLE public.<name> ENABLE ROW LEVEL SECURITY` — see "
            "database/migrations/versions/012_rls_on_late_tables.py."
        )

    def test_no_migration_enables_rls_for_a_table_that_does_not_exist(self):
        """
        The mirror image: a typo in a migration's table list would silently protect
        nothing, and the table it was meant to cover would stay exposed.
        """
        # audit_logs and friends are real; anything not in metadata is a typo or a
        # table dropped without cleaning up its RLS statement.
        stale = sorted(_tables_with_rls() - _tables_in_models())
        assert not stale, (
            f"migrations enable RLS on tables that no longer exist in the models: {stale}"
        )


@pytest.mark.parametrize("table", sorted(_tables_in_models()))
def test_table_is_covered(table: str):
    """
    One case per table, so a failure names the specific table in the test id
    rather than burying it in a list.
    """
    assert table in _tables_with_rls(), f"{table} has no RLS migration"

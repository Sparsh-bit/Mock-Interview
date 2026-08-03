"""
The migration chain has exactly one head — tests/test_migration_chain.py

WHY THIS EXISTS. Migration 013 shipped with `down_revision = "012_rls_on_late_tables"`
— the FILENAME of migration 012, not its revision id, which is "012". Alembic does
not validate that at import time, so the result was two heads and a dangling
down_revision, and `alembic upgrade head` would have failed on the deploy rather than
here. Nothing in lint, mypy or the test suite noticed.

The failure mode is the worst kind: invisible locally (there is no database in CI),
and it surfaces during a production migration.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "database" / "migrations" / "versions"


def _revisions() -> dict[str, str | None]:
    """revision -> down_revision, loaded from the migration files themselves."""
    out: dict[str, str | None] = {}
    for f in sorted(VERSIONS.glob("[0-9]*.py")):
        spec = importlib.util.spec_from_file_location(f.stem, f)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f.stem] = mod
        spec.loader.exec_module(mod)
        out[mod.revision] = mod.down_revision
    return out


class TestMigrationChain:
    def test_the_loader_actually_found_migrations(self):
        # Guards every assertion below from passing vacuously if the glob or the
        # directory layout changes.
        revs = _revisions()
        assert len(revs) >= 13, f"only loaded {len(revs)} migrations — check the path"

    def test_there_is_exactly_one_head(self):
        revs = _revisions()
        parents = {v for v in revs.values() if v}
        heads = sorted(set(revs) - parents)
        assert len(heads) == 1, (
            f"the migration chain has {len(heads)} heads: {heads}\n\n"
            "`alembic upgrade head` fails with multiple heads. The usual cause is a "
            "down_revision naming a migration's FILENAME instead of its revision id "
            "— 012's file is 012_rls_on_late_tables.py but its revision is \"012\"."
        )

    def test_no_down_revision_points_at_a_migration_that_does_not_exist(self):
        revs = _revisions()
        dangling = sorted(
            f"{rev} -> {down}" for rev, down in revs.items() if down and down not in revs
        )
        assert not dangling, f"down_revision names an unknown revision: {dangling}"

    def test_every_migration_reaches_the_root(self):
        revs = _revisions()
        parents = {v for v in revs.values() if v}
        head = next(iter(set(revs) - parents))
        walked, cur = 0, head
        seen: set[str] = set()
        while cur:
            assert cur not in seen, f"cycle in the migration chain at {cur}"
            seen.add(cur)
            walked += 1
            cur = revs.get(cur)
        assert walked == len(revs), (
            f"walking back from the head visits {walked} of {len(revs)} migrations — "
            "some are orphaned and would never run."
        )

    def test_every_migration_has_a_downgrade(self):
        # Not merely tidiness: a migration that cannot be reversed makes a bad deploy
        # unrecoverable without hand-written SQL against production.
        for f in sorted(VERSIONS.glob("[0-9]*.py")):
            src = f.read_text()
            assert "def downgrade()" in src, f"{f.name} has no downgrade()"
            body = src.split("def downgrade()", 1)[1]
            assert "pass" not in body.split("\n")[1:3] or "op." in body, (
                f"{f.name} has an empty downgrade()"
            )

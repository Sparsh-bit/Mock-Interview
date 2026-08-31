"""
The retention clocks, now that something enforces them.

`FINANCIAL_RETENTION_YEARS = 8` and `SECURITY_LOG_RETENTION_DAYS = 180` were declared
in services/legal/retention.py, quoted in COMPLIANCE.md, DATA-RESIDENCY.md and
SECURITY-REVIEW.md, and enforced by nothing. All three documents said so.

TWO FAILURE DIRECTIONS, and only one of them is loud. Purging too little is a
compliance drift nobody notices. Purging too much is an unattended, irreversible
delete of financial records the Companies Act requires be kept — so most of what is
below is about the second.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select

from app.models.system import AuditLog
from app.services.legal.purge import (
    _MINIMUM_WINDOW,
    BUCKETS,
    Bucket,
    purge_expired,
)
from app.services.legal.retention import (
    FINANCIAL_RETENTION_YEARS,
    SECURITY_LOG_RETENTION_DAYS,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


class TestItUsesTheConstantsThatAlreadyExist:
    """The point of the constants is that the number appears once. A second opinion
    living in purge.py is how the disclosure and the enforcement come to disagree."""

    def test_the_security_window_is_the_cert_in_one(self):
        bucket = next(b for b in BUCKETS if b.clock == "SECURITY_LOG_RETENTION_DAYS")
        assert bucket.window == timedelta(days=SECURITY_LOG_RETENTION_DAYS)
        assert bucket.window.days == 180

    def test_the_financial_window_is_eight_financial_years(self):
        bucket = next(b for b in BUCKETS if b.clock == "FINANCIAL_RETENTION_YEARS")
        # 365.25 so eight years does not land two days short of the statute.
        assert bucket.window >= timedelta(days=FINANCIAL_RETENTION_YEARS * 365)
        assert bucket.window.days == int(FINANCIAL_RETENTION_YEARS * 365.25)

    def test_no_bucket_invents_its_own_number(self):
        allowed = {
            timedelta(days=SECURITY_LOG_RETENTION_DAYS),
            timedelta(days=FINANCIAL_RETENTION_YEARS * 365.25),
        }
        for bucket in BUCKETS:
            assert bucket.window in allowed, (
                f"{bucket.table} purges on a window that is neither constant"
            )

    def test_every_bucket_carries_a_reason(self):
        # What a reviewer needs to judge whether the deletion is justified.
        for bucket in BUCKETS:
            assert len(bucket.reason) > 30

    @pytest.mark.parametrize("table", ["activity_logs", "consent_events", "referrals", "users"])
    def test_the_deliberately_excluded_tables_are_absent(self, table):
        """Each is excluded for a reason written into purge.py's docstring. If one is
        added, that reasoning has to be revisited rather than silently overtaken."""
        assert table not in {b.table for b in BUCKETS}


class TestTheFloorThatStopsItDeletingLiveData:
    """The failure being guarded is a constant edited to 0, or `days=` where the code
    meant years — either turns "older than eight years" into "everything"."""

    @pytest.mark.asyncio
    async def test_a_zero_window_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.legal.purge.BUCKETS",
            (Bucket("audit_logs", timedelta(0), "TEST", "a window of nothing"),),
        )
        with pytest.raises(ValueError, match="below the"):
            await purge_expired(None, now=NOW)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_a_years_as_days_slip_is_refused(self, monkeypatch):
        """FINANCIAL_RETENTION_YEARS read as days: 8 days instead of 8 years."""
        monkeypatch.setattr(
            "app.services.legal.purge.BUCKETS",
            (
                Bucket(
                    "credit_events",
                    timedelta(days=FINANCIAL_RETENTION_YEARS),
                    "FINANCIAL_RETENTION_YEARS",
                    "eight DAYS — the unit slip this exists to catch",
                ),
            ),
        )
        with pytest.raises(ValueError, match="deletes live data"):
            await purge_expired(None, now=NOW)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_a_negative_window_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.legal.purge.BUCKETS",
            (Bucket("audit_logs", timedelta(days=-400), "TEST", "a window into the future"),),
        )
        with pytest.raises(ValueError):
            await purge_expired(None, now=NOW)  # type: ignore[arg-type]

    def test_the_floor_sits_below_both_real_windows(self):
        # Otherwise it would refuse a legitimate purge.
        for bucket in BUCKETS:
            assert bucket.window >= _MINIMUM_WINDOW

    @pytest.mark.asyncio
    async def test_a_naive_now_is_refused(self):
        # A naive cutoff compared against timezone-aware created_at is a silent bug.
        with pytest.raises(ValueError, match="timezone-aware"):
            await purge_expired(None, now=datetime(2026, 8, 31))  # type: ignore[arg-type]


@pytest.fixture(scope="module", autouse=True)
async def _audit_logs_table():
    """Make sure `audit_logs` exists in the test database.

    The full schema is built by a session-scoped fixture inside test_integration.py, so
    it is not reliably in place when this module runs on its own. `checkfirst=True`
    makes this a no-op when it is, so the two cannot fight.
    """
    import app.models  # noqa: F401 — registers every mapper before create_all
    from app.db.session import engine
    from app.models.base import Base

    # The whole schema, not just audit_logs: it carries a foreign key to `users`, and
    # that table has its own dependencies. `checkfirst=True` makes this a no-op when
    # test_integration.py's session-scoped fixture has already built it, so the two
    # cannot fight over the same database.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    yield


@pytest.mark.asyncio
class TestAgainstRealRows:
    """The counting and the deleting, against a real table. Anything less does not
    establish that the predicate selects what the report claims it selects."""

    @staticmethod
    async def _session():
        from app.db.session import AsyncSessionFactory

        return AsyncSessionFactory()

    async def _seed(self, db, ages_in_days: list[int], tag: str) -> None:
        for age in ages_in_days:
            db.add(
                AuditLog(
                    id=uuid.uuid4(),
                    action=f"{tag}.{age}",
                    created_at=NOW - timedelta(days=age),
                )
            )
        await db.flush()

    async def _cleanup(self, db, tag: str) -> None:
        await db.execute(delete(AuditLog).where(AuditLog.action.like(f"{tag}.%")))
        await db.commit()

    async def test_a_dry_run_counts_the_old_and_deletes_nothing(self):
        tag = f"purge-dry-{uuid.uuid4().hex[:8]}"
        async with await self._session() as db:
            try:
                # Two well past 180 days, two comfortably inside it.
                await self._seed(db, [400, 181, 179, 1], tag)
                before = await db.scalar(
                    select(func.count()).select_from(AuditLog).where(
                        AuditLog.action.like(f"{tag}.%")
                    )
                )
                assert before == 4

                report = await purge_expired(db, now=NOW, apply=False)

                assert report.applied is False
                assert report.rows["audit_logs"] >= 2
                after = await db.scalar(
                    select(func.count()).select_from(AuditLog).where(
                        AuditLog.action.like(f"{tag}.%")
                    )
                )
                assert after == 4, "a dry run deleted rows"
                assert "DRY RUN" in report.render()
            finally:
                await self._cleanup(db, tag)

    async def test_apply_deletes_only_what_is_past_the_window(self):
        tag = f"purge-apply-{uuid.uuid4().hex[:8]}"
        async with await self._session() as db:
            try:
                await self._seed(db, [400, 181, 179, 1], tag)

                report = await purge_expired(db, now=NOW, apply=True)
                assert report.applied is True

                remaining = (
                    await db.execute(
                        select(AuditLog.action).where(AuditLog.action.like(f"{tag}.%"))
                    )
                ).scalars().all()

                # THE ASSERTION THAT MATTERS. Not "some rows went" — exactly the two
                # outside the window went, and both inside it are untouched.
                assert sorted(remaining) == sorted([f"{tag}.179", f"{tag}.1"]), (
                    f"the purge crossed the retention boundary: kept {sorted(remaining)}"
                )
            finally:
                await self._cleanup(db, tag)

    async def test_the_boundary_row_is_kept(self):
        """`created_at < cutoff`, not `<=`. A row exactly on the boundary is still
        inside the retention period."""
        tag = f"purge-edge-{uuid.uuid4().hex[:8]}"
        async with await self._session() as db:
            try:
                exact = NOW - timedelta(days=SECURITY_LOG_RETENTION_DAYS)
                db.add(AuditLog(id=uuid.uuid4(), action=f"{tag}.exact", created_at=exact))
                await db.flush()

                await purge_expired(db, now=NOW, apply=True)

                still = await db.scalar(
                    select(func.count()).select_from(AuditLog).where(
                        AuditLog.action == f"{tag}.exact"
                    )
                )
                assert still == 1, "a row exactly on the retention boundary was deleted"
            finally:
                await self._cleanup(db, tag)

    async def test_it_does_not_commit_by_itself(self):
        """purge_expired leaves the transaction to the caller, like credits.consume.
        A rollback must undo the whole batch rather than leave it half-purged."""
        tag = f"purge-rb-{uuid.uuid4().hex[:8]}"
        async with await self._session() as db:
            try:
                await self._seed(db, [400, 401], tag)
                await db.commit()

                await purge_expired(db, now=NOW, apply=True)
                await db.rollback()

                survived = await db.scalar(
                    select(func.count()).select_from(AuditLog).where(
                        AuditLog.action.like(f"{tag}.%")
                    )
                )
                assert survived == 2, "the purge committed on its own; a rollback lost rows"
            finally:
                await self._cleanup(db, tag)

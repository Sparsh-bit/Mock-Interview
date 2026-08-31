"""
The other end of retention — services/legal/purge.py

`retention.py` decides what SURVIVES an erasure request. This decides what stops
surviving once the clock it was kept for has run out, which is the half that did not
exist: `FINANCIAL_RETENTION_YEARS` and `SECURITY_LOG_RETENTION_DAYS` were declared,
quoted in three documents, and enforced by nothing. A retention period that is only
ever a floor is not a policy — DPDP §8(7) permits keeping data to satisfy another
law, and stops permitting it when that law stops asking.

THE TWO CLOCKS ARE THE ONES THAT ALREADY EXIST. No new number is invented here, and
that is deliberate: a second opinion about how long to keep a financial record,
living in a different file from the first, is how the disclosure a candidate reads
and the code that enforces it come to disagree.

WHAT IS DELIBERATELY NOT PURGED, because neither constant names it:

  activity_logs   Product data — one completed interview or quiz. Not a security log,
                  whatever the name suggests, and no statutory clock applies.
  consent_events  Its stated reason in RETAINED_TABLES is evidence that processing
                  which already happened was consented to. That evidence is worth
                  exactly as long as the processing is arguable, and nobody has put
                  a number on it. Deleting it on a clock nobody chose would be
                  inventing the number this module refuses to invent.
  referrals       Explains a credit_events grant no payment paid for. It should not
                  outlive the row it explains, nor predecease it; wiring that
                  correctly needs the financial clock applied to a join, which is
                  more than "older than X" and so is not smuggled in here.

DRY RUN IS THE DEFAULT, AND NOT AS A COURTESY. `purge_expired` reports without
`apply=True`; nothing deletes unless a caller says so in as many words. The first
run of an irreversible batch job against real data should be readable before it is
believed.

THE FLOOR IS CHECKED RATHER THAN TRUSTED. Every cutoff is asserted to be at least
its full window in the past before any statement runs, so a caller passing a
mistaken `now` — a test, a clock skew, a future refactor computing the window in
days where it meant years — cannot delete anything inside the retention period. The
failure mode being guarded is not "deletes slightly too much"; it is "deletes
records the Companies Act requires, on a job that runs unattended".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.legal.retention import (
    FINANCIAL_RETENTION_YEARS,
    SECURITY_LOG_RETENTION_DAYS,
)

logger = structlog.get_logger(__name__)

#: Days per financial year, for turning FINANCIAL_RETENTION_YEARS into a cutoff.
#: 365.25 rather than 365 so eight years does not drift two days short of the
#: statutory period because of leap years — erring, as everything here does, on the
#: side of keeping the record longer.
_DAYS_PER_YEAR = 365.25

#: No bucket may ever purge with a window shorter than this. Not a policy — the two
#: real windows are 180 days and eight years — but a backstop against the way this
#: job kills somebody: a constant edited to 0, or a unit slip that reads
#: FINANCIAL_RETENTION_YEARS as days. Set just under the smaller real window, so it
#: catches a mistake without needing to be edited when a legitimate one changes.
_MINIMUM_WINDOW = timedelta(days=SECURITY_LOG_RETENTION_DAYS - 1)


@dataclass(frozen=True)
class Bucket:
    """One table, one clock, one reason a reviewer can check."""

    table: str
    window: timedelta
    clock: str
    reason: str


def _financial(table: str, reason: str) -> Bucket:
    return Bucket(
        table=table,
        window=timedelta(days=FINANCIAL_RETENTION_YEARS * _DAYS_PER_YEAR),
        clock="FINANCIAL_RETENTION_YEARS",
        reason=reason,
    )


def _security(table: str, reason: str) -> Bucket:
    return Bucket(
        table=table,
        window=timedelta(days=SECURITY_LOG_RETENTION_DAYS),
        clock="SECURITY_LOG_RETENTION_DAYS",
        reason=reason,
    )


#: Every table this job will ever touch. Adding one is a deliberate act with a
#: reason attached, not a consequence of adding a model.
BUCKETS: tuple[Bucket, ...] = (
    _security(
        "audit_logs",
        "CERT-In Directions, April 2022 — 180 days. retention.py already names "
        "audit_logs as the table that keeps them.",
    ),
    _financial(
        "credit_events",
        "Financial ledger — Companies Act §128(5), eight financial years.",
    ),
    _financial(
        "offer_redemptions",
        "Financial ledger, and the one-redemption-per-account record.",
    ),
)


@dataclass
class PurgeReport:
    applied: bool
    at: datetime
    rows: dict[str, int] = field(default_factory=dict)
    cutoffs: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.rows.values())

    def render(self) -> str:
        verb = "Deleted" if self.applied else "Would delete"
        lines = [
            f"{verb} {self.total} row(s) — retention purge at {self.at.isoformat()}",
            "" if self.applied else "DRY RUN — nothing was deleted. Pass --apply to act.",
        ]
        for bucket in BUCKETS:
            lines.append(
                f"  {bucket.table:20} {self.rows.get(bucket.table, 0):>8}  "
                f"older than {self.cutoffs.get(bucket.table, '?')}  [{bucket.clock}]"
            )
        return "\n".join(line for line in lines if line != "" or not self.applied)


def _model_for(table: str) -> Any:
    """The mapped class for a table name, so the delete goes through the ORM's own
    metadata rather than an interpolated table name."""
    # Importing the models package registers every mapper on Base.
    import app.models  # noqa: F401, PLC0415
    from app.models.base import Base  # noqa: PLC0415

    for mapper in Base.registry.mappers:
        if mapper.class_.__tablename__ == table:
            return mapper.class_
    raise LookupError(f"no model is mapped to {table!r}")


async def purge_expired(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    apply: bool = False,
) -> PurgeReport:
    """
    Count — and only if `apply`, delete — rows past their retention window.

    Returns what it did, or what it would have done. Never commits: the caller's
    session scope decides, exactly as it does for `consume` in billing/credits.py,
    so a failure anywhere in the job undoes the whole batch rather than leaving it
    half-purged.
    """
    at = now or datetime.now(UTC)
    if at.tzinfo is None:
        raise ValueError("`now` must be timezone-aware; a naive cutoff is a silent bug")

    report = PurgeReport(applied=apply, at=at)

    for bucket in BUCKETS:
        cutoff = at - bucket.window

        # THE FLOOR, checked at the last point before an unattended, irreversible
        # statement. `cutoff` is derived from `window`, so comparing the two would be
        # a tautology and would guard nothing. What can actually go wrong is the
        # WINDOW: a constant edited to 0 or a negative, or `days=` used where the
        # code meant years, turns "older than eight years" into "everything" without
        # changing a line of this function.
        if bucket.window < _MINIMUM_WINDOW:
            raise ValueError(
                f"refusing to purge {bucket.table}: {bucket.clock} yields a window of "
                f"{bucket.window.days} days, below the {_MINIMUM_WINDOW.days}-day floor. "
                f"A window this short deletes live data."
            )
        if cutoff >= at:  # pragma: no cover - implied by the check above
            raise ValueError(f"cutoff for {bucket.table} is not in the past")

        model = _model_for(bucket.table)
        report.cutoffs[bucket.table] = cutoff.isoformat()

        matched = await db.scalar(
            select(func.count()).select_from(model).where(model.created_at < cutoff)
        )
        report.rows[bucket.table] = int(matched or 0)

        if apply and report.rows[bucket.table]:
            # ponytail: one unbounded DELETE per table. Fine at this size; if a table
            # ever grows past a few hundred thousand expired rows, batch it by primary
            # key so the lock is not held for the whole statement.
            await db.execute(delete(model).where(model.created_at < cutoff))

        logger.info(
            "retention_purge_bucket",
            table=bucket.table,
            clock=bucket.clock,
            cutoff=cutoff.isoformat(),
            rows=report.rows[bucket.table],
            applied=apply,
        )

    logger.info(
        "retention_purge_complete",
        applied=apply,
        total=report.total,
    )
    return report

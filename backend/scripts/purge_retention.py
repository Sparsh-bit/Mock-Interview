#!/usr/bin/env python
"""
Delete what the retention clocks have run out on.

    uv run python scripts/purge_retention.py            # dry run — prints, deletes nothing
    uv run python scripts/purge_retention.py --apply    # actually deletes

DRY RUN IS THE DEFAULT AND --apply IS A WORD SOMEBODY HAS TO TYPE. This is an
unattended, irreversible batch delete against financial and security records; the
version of it that is easy to run by accident is the wrong version.

The windows come from services/legal/retention.py — FINANCIAL_RETENTION_YEARS and
SECURITY_LOG_RETENTION_DAYS. There is no flag to override them, deliberately: a
retention period that a command-line argument can shorten is not a retention period.

Exit codes: 0 on success (including a dry run that found nothing), 1 on failure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually delete. Without it, nothing is written.",
    )
    args = parser.parse_args()

    from app.db.session import get_db_session
    from app.services.legal.purge import purge_expired

    async with get_db_session() as db:
        report = await purge_expired(db, apply=args.apply)
        if args.apply:
            # purge_expired never commits — see its docstring. The whole batch lands
            # together or not at all.
            await db.commit()

    print(report.render())
    if not args.apply and report.total:
        print("\nRe-run with --apply to delete these.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

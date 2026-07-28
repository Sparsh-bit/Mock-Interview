"""
Seed company interview research — scripts/seed_research.py

Loads every YAML file in knowledge/research/ into the company_research table.
Idempotent: re-running updates existing (company_slug, program_slug) rows in
place rather than duplicating them, so refreshing the research is just an edit
plus a re-run.

Usage:
    cd backend && uv run python scripts/seed_research.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import yaml

# Make `app` importable when run as a plain script.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db.session import AsyncSessionFactory  # noqa: E402
from app.models.research import CompanyResearch  # noqa: E402

RESEARCH_DIR = pathlib.Path(__file__).resolve().parent.parent / "knowledge" / "research"

REQUIRED = ("company_slug", "company_name")


def _load_entries() -> list[dict]:
    """Read and validate every research YAML file."""
    if not RESEARCH_DIR.is_dir():
        raise SystemExit(f"No research directory at {RESEARCH_DIR}")

    entries: list[dict] = []
    for path in sorted(RESEARCH_DIR.glob("*.yaml")):
        loaded = yaml.safe_load(path.read_text()) or []
        if not isinstance(loaded, list):
            raise SystemExit(f"{path.name}: expected a list of entries")
        for i, entry in enumerate(loaded):
            missing = [k for k in REQUIRED if not entry.get(k)]
            if missing:
                raise SystemExit(f"{path.name}[{i}]: missing {missing}")
            entries.append(entry)
    return entries


async def seed() -> None:
    entries = _load_entries()
    created = updated = 0

    async with AsyncSessionFactory() as db:
        for entry in entries:
            company = entry["company_slug"].strip().lower()
            program = (entry.get("program_slug") or "").strip().lower()

            row = await db.scalar(
                select(CompanyResearch).where(
                    CompanyResearch.company_slug == company,
                    CompanyResearch.program_slug == program,
                )
            )
            if row is None:
                row = CompanyResearch(company_slug=company, program_slug=program)
                db.add(row)
                created += 1
            else:
                updated += 1

            row.company_name = entry["company_name"]
            row.program_name = entry.get("program_name") or ""
            row.rounds = entry.get("rounds") or []
            row.previous_questions = entry.get("previous_questions") or []
            row.focus_topics = entry.get("focus_topics") or []
            row.tips = entry.get("tips") or []
            row.sources = entry.get("sources") or []

            print(
                f"  {company}/{program or '(any)':<10} "
                f"{len(row.previous_questions):>3} questions, {len(row.rounds)} rounds"
            )

        await db.commit()

    print(f"\nSeeded {created} new and {updated} updated research rows.")


if __name__ == "__main__":
    asyncio.run(seed())

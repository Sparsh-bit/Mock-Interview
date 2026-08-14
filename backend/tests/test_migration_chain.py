"""
The migration chain is linear and has one head — tests/test_migration_chain.py

WHY THIS EXISTS. Two migrations were written with revision "016" and two with "017", by
someone (me) adding files without checking what the branch already had. Alembic does not
care until you run it, and then it refuses everything:

    UserWarning: Revision 017 is present more than once
    FAILED: Multiple head revisions are present for given argument 'head'

That surfaced on Render, mid-deploy, as `Exited with status 255` — the backend would not
start at all. It is a class of mistake that costs nothing to catch in a second and takes a
production outage to notice otherwise, because nothing in lint, mypy or the test suite reads
these files.

The tests are deliberately about the SHAPE of the chain rather than about what any migration
does. A duplicate id, a dangling parent, or a fork are all "the deploy dies"; the contents of
a migration are a different question with different tests.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

_VERSIONS = Path(__file__).resolve().parents[2] / "database" / "migrations" / "versions"


def _revisions() -> dict[str, tuple[str | None, str]]:
    """{revision: (down_revision, filename)} read straight from the files."""
    out: dict[str, tuple[str | None, str]] = {}
    for path in sorted(_VERSIONS.glob("*.py")):
        src = path.read_text()
        # Both spellings appear in this repo — the early ones are annotated
        # (`revision: str = "001"`), the later ones bare. Matching both rather than
        # normalising the files, because rewriting history to suit a test is backwards.
        rev = re.search(r'^revision(?:\s*:\s*[^=]+)?\s*=\s*"([^"]+)"', src, re.M)
        down = re.search(
            r'^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(?:"([^"]+)"|None)', src, re.M
        )
        if not rev:
            continue
        out[rev.group(1)] = (down.group(1) if down and down.group(1) else None, path.name)
    return out


def _duplicates() -> list[str]:
    """Revision ids claimed by more than one file. Read per-file, not via the dict."""
    ids: list[str] = []
    for path in sorted(_VERSIONS.glob("*.py")):
        rev = re.search(
            r'^revision(?:\s*:\s*[^=]+)?\s*=\s*"([^"]+)"', path.read_text(), re.M
        )
        if rev:
            ids.append(rev.group(1))
    return [rev for rev, n in Counter(ids).items() if n > 1]


def test_the_scanner_actually_finds_the_migrations():
    """
    Guards the guard. Every assertion below passes trivially against an empty directory, so
    a moved folder or a changed filename pattern would silently disable all of them.
    """
    revisions = _revisions()
    assert len(revisions) >= 15, f"only found {len(revisions)} migrations — has the path moved?"


def test_no_revision_id_is_used_twice():
    """
    THE ONE THAT WOULD HAVE CAUGHT IT. Two files claiming "017" is not a merge conflict or a
    subtle ordering problem — it is a backend that refuses to boot.
    """
    dupes = _duplicates()
    assert not dupes, (
        f"these revision ids are claimed by more than one file: {sorted(dupes)}. "
        "Alembic refuses to run at all in this state — renumber the newer one to sit after "
        "the existing chain."
    )


def test_there_is_exactly_one_head():
    """
    A head is a revision nothing else points back to. Two heads means `alembic upgrade head`
    cannot pick one and fails, which is the second half of what the deploy printed.
    """
    revisions = _revisions()
    parents = {down for down, _ in revisions.values() if down}
    heads = sorted(set(revisions) - parents)
    assert len(heads) == 1, (
        f"expected one head, found {heads}. Two heads means the chain forked — one migration "
        "needs its down_revision pointed at the other."
    )


def test_every_parent_exists():
    """
    A down_revision naming something that is not there leaves an unreachable migration: it
    never runs, and the table it creates is missing at runtime rather than at deploy time —
    which is far worse, because the deploy looks fine.
    """
    revisions = _revisions()
    for _rev, (down, filename) in sorted(revisions.items()):
        if down is not None:
            assert down in revisions, f"{filename} points at {down!r}, which does not exist"


def test_exactly_one_migration_is_the_base():
    revisions = _revisions()
    bases = sorted(rev for rev, (down, _) in revisions.items() if down is None)
    assert bases == ["001"], f"expected 001 to be the only base, found {bases}"


def test_the_chain_is_linear_with_no_two_children_sharing_a_parent():
    """
    A fork. Alembic can express branches deliberately, and this project does not use them —
    so two migrations claiming the same parent is always the accident above rather than an
    intention, and it produces the same two-heads failure.
    """
    revisions = _revisions()
    by_parent: dict[str, list[str]] = {}
    for rev, (down, filename) in revisions.items():
        if down:
            by_parent.setdefault(down, []).append(f"{rev} ({filename})")
    forks = {parent: kids for parent, kids in by_parent.items() if len(kids) > 1}
    assert not forks, f"these revisions have more than one child: {forks}"


@pytest.mark.parametrize("path", sorted(_VERSIONS.glob("*.py")), ids=lambda p: p.name)
def test_the_filename_prefix_matches_the_revision_id(path: Path):
    """
    `018_offers.py` declaring revision "016" is legal and unreadable — the directory listing
    stops being the running order, which is how the duplicate above got written in the first
    place. One case per file, so a failure names the file.
    """
    prefix = path.name.split("_", 1)[0]
    rev = re.search(r'^revision(?:\s*:\s*[^=]+)?\s*=\s*"([^"]+)"', path.read_text(), re.M)
    assert rev, f"{path.name} declares no revision"
    assert rev.group(1) == prefix, (
        f"{path.name} declares revision {rev.group(1)!r}; rename the file or the revision so "
        "the directory listing is the running order"
    )

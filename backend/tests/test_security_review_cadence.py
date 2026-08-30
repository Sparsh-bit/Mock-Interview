"""
The security review is a clock, not a document — tests/test_security_review_cadence.py

WHY THIS FILE EXISTS. `docs/MISTAKES.md` is largely one lesson written many ways: a guard
that cannot fail reports success. A quarterly review that lives only in a Markdown file is
exactly that guard. It does not go red when it is skipped. It just quietly stops describing
the codebase, and the longer it goes unread the more authoritative it sounds — which is the
precise failure mode of the trial-allowance note that `CLAUDE.md` now spends a paragraph
warning about.

So the schedule is enforced here, and this file fails the suite when:

  · the review is overdue,
  · the newest review entry does not cover every category on all three OWASP lists,
  · a category is claimed without a status, or
  · the "next review due" date is missing or unparseable.

IT FAILS LOUDLY AND ON PURPOSE. A warning nobody sees is the thing being replaced. The
grace period below is what stops a review falling on a public holiday from breaking a
deploy, and the due date is a plain string in the document, so extending it is a one-line
commit that somebody reviews rather than a console setting that somebody clicks.

WHAT THIS DOES NOT DO. It cannot check that a review was any GOOD — that a "covered" row is
true, or that the evidence next to it is real. Nothing can. What it can do is make skipping
the review cost the same as breaking a test, which is the only part that was ever going to
be forgotten.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

_DOC = Path(__file__).resolve().parents[2] / "docs" / "SECURITY-REVIEW.md"

#: How long after the due date the suite stays green. A review that lands on a holiday must
#: not break a deploy; a review that is a month late should.
_GRACE_DAYS = 14

#: The categories a review has to have an opinion about. Written out rather than scraped
#: from the web, because a test that makes a network call is a test that fails on a train —
#: and because the point is to catch a review that SKIPPED something, which needs a fixed
#: list to compare against. When OWASP publishes a new edition, this list changes in the
#: same commit as the review that used it.
_WEB_2025 = tuple(f"A{n:02d}:2025" for n in range(1, 11))
_API_2023 = tuple(f"API{n}:2023" for n in range(1, 11))
_LLM_2025 = tuple(f"LLM{n:02d}:2025" for n in range(1, 11))
_ALL_CATEGORIES = _WEB_2025 + _API_2023 + _LLM_2025

#: A row is only an answer if it carries one of these. A category listed with an empty
#: status column is a category nobody looked at.
_STATUS_MARKERS = ("✅", "⚠️", "🟡", "🔴")


@pytest.fixture(scope="module")
def doc() -> str:
    assert _DOC.exists(), (
        f"{_DOC} is missing. The security review cadence is defined by that document; "
        "deleting it does not end the obligation, it just hides it."
    )
    return _DOC.read_text(encoding="utf-8")


def _due_date(text: str) -> dt.date:
    match = re.search(r"\*\*Next review due:\*\*\s*(\d{4}-\d{2}-\d{2})", text)
    assert match, (
        "SECURITY-REVIEW.md has no parseable '**Next review due:** YYYY-MM-DD' line. "
        "That line is the schedule; without it there is no cadence, only a document."
    )
    return dt.date.fromisoformat(match.group(1))


def _newest_review(text: str) -> str:
    """
    The body of the most recent `### YYYY-MM-DD — …` section under the review log.

    Newest by DATE rather than by position, so a review appended in the wrong place is
    still read correctly and an old entry edited to look new does not become the one
    checked.
    """
    sections = re.split(r"^### (\d{4}-\d{2}-\d{2})", text, flags=re.MULTILINE)
    assert len(sections) > 1, (
        "the review log has no dated entries. Writing the process down is not running it — "
        "the first review has to be logged before this file can check anything."
    )
    pairs = list(zip(sections[1::2], sections[2::2], strict=True))
    return max(pairs, key=lambda pair: pair[0])[1]


class TestTheScheduleIsReal:
    def test_the_document_declares_a_quarterly_cadence(self, doc: str):
        assert "quarterly" in doc.lower()

    def test_the_next_review_is_not_overdue(self, doc: str):
        due = _due_date(doc)
        today = dt.date.today()
        overdue_by = (today - due).days

        assert overdue_by <= _GRACE_DAYS, (
            f"The quarterly security review was due on {due.isoformat()} and is "
            f"{overdue_by} days late.\n\n"
            "This is not a broken test — it is the schedule doing its job. Run the review: "
            "docs/SECURITY-REVIEW.md has the procedure under 'How to run one'. Append a "
            "dated section to the review log and move the 'Next review due' line.\n\n"
            "If the review genuinely cannot happen now, moving the date is a one-line "
            "commit — but make it deliberately, in a change somebody reads, rather than by "
            "deleting this assertion."
        )

    def test_the_due_date_is_in_the_future_of_the_last_review(self, doc: str):
        """
        Guards the guard. A due date accidentally set to a past quarter would fail the test
        above forever and the fix would look like 'delete the test'.
        """
        due = _due_date(doc)
        last = max(
            dt.date.fromisoformat(d)
            for d in re.findall(r"^### (\d{4}-\d{2}-\d{2})", doc, flags=re.MULTILINE)
        )
        assert due > last, (
            f"the next review is due {due} but the last one was logged {last} — the due "
            "date was not moved forward after the review was run"
        )


class TestTheReviewActuallyCoveredTheLists:
    def test_all_three_lists_are_named_with_their_editions(self, doc: str):
        for marker in ("OWASP Top 10:2025", "API Security Top 10", "LLM Applications"):
            assert marker in doc, f"{marker!r} is not named in the review document"

    def test_each_list_cites_its_source_url(self, doc: str):
        """
        A review against a remembered list is a review against a stale list. The URLs are
        what make it re-runnable by somebody who was not here.
        """
        for url in (
            "https://owasp.org/Top10/2025/",
            "https://owasp.org/API-Security/",
            "https://genai.owasp.org/",
        ):
            assert url in doc, f"no source cited for {url}"

    @pytest.mark.parametrize("category", _ALL_CATEGORIES)
    def test_the_newest_review_has_a_row_for_every_category(self, doc: str, category: str):
        newest = _newest_review(doc)
        assert category in newest, (
            f"the most recent review has no row for {category}. Every category gets an "
            "answer, including 'not applicable' — a missing row is indistinguishable from "
            "a category nobody looked at."
        )

    @pytest.mark.parametrize("category", _ALL_CATEGORIES)
    def test_every_category_row_carries_a_status(self, doc: str, category: str):
        newest = _newest_review(doc)
        row = next(
            (line for line in newest.splitlines() if line.strip().startswith("|") and category in line),
            None,
        )
        assert row is not None, f"{category} is mentioned but not as a table row"
        assert any(marker in row for marker in _STATUS_MARKERS), (
            f"the {category} row has no status marker (one of {_STATUS_MARKERS}). "
            "A category listed without a verdict is a category nobody decided about."
        )


class TestFindingsAreTraceable:
    def test_every_finding_id_referenced_in_a_table_has_a_section(self, doc: str):
        """
        A table row pointing at 'SR-2026Q3-04' with no such section is a finding that reads
        as recorded and is not. The tables and the write-ups have to agree.
        """
        referenced = set(re.findall(r"SR-\d{4}Q\d-\d{2}", doc))
        written_up = set(re.findall(r"^### (SR-\d{4}Q\d-\d{2})", doc, flags=re.MULTILINE))

        assert referenced, "no findings are recorded at all — see the note below"
        missing = referenced - written_up
        assert not missing, (
            f"these findings are referenced but never written up: {sorted(missing)}"
        )

    def test_every_written_up_finding_has_a_severity_and_a_state(self, doc: str):
        headings = re.findall(r"^### SR-\d{4}Q\d-\d{2}[^\n]*", doc, flags=re.MULTILINE)
        assert headings, "no findings written up"
        for heading in headings:
            assert any(s in heading for s in ("**high**", "**medium**", "**low**")), (
                f"{heading!r} has no severity"
            )
            #: "blocked" is a first-class state, not a synonym for open: it means the
            #: remaining work is not in this repository. SR-2026Q3-04 is the case — brute
            #: force protection for login is a Supabase console setting — and a review that
            #: cannot say so has to either lie or leave it looking un-triaged.
            assert any(
                s in heading for s in ("open", "closed", "accepted", "mitigated", "blocked")
            ), (
                f"{heading!r} does not say whether it is open"
            )

    def test_the_first_review_recorded_real_findings(self, doc: str):
        """
        THE POINT OF THE WHOLE EXERCISE. A first review that found nothing did not happen.
        This is not a claim that a future review must find something — it is a claim about
        the one already logged, so the process cannot have been established by writing a
        document and ticking every box.
        """
        assert len(re.findall(r"^### SR-\d{4}Q\d-\d{2}", doc, flags=re.MULTILINE)) >= 5

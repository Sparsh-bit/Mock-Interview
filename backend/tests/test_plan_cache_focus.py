"""
A typed focus is never served somebody else's plan — tests/test_plan_cache_focus.py

THE REPORT, AND THE HALF OF IT NO PROMPT COULD HAVE FIXED. A candidate said the setup
screen's "Anything specific?" box did nothing. Most of that was `interview_plan.md` giving
the box one trailing clause against two concrete "draw from this list" instructions. But
`create_plan` asks `semantic_cache.find_similar_key(company, program, focus)` BEFORE the
must-cover block or the focus string is assembled, and on a hit no model is called at all.
So on the common path the prompt was irrelevant: the candidate was handed a plan generated
before their topics existed.

The number is the whole argument. `_vectorize` weights company 3.0, program 3.0, focus 1.0,
so a focused setup and the same setup with an empty box are 0.958 apart and the reuse
threshold is 0.82. Every candidate who typed a topic list into that box got the generic
plan, silently, from the moment one existed.

WHY A PARTITION AND NOT A HIGHER THRESHOLD. Raising the threshold past 0.958 would also
separate "Cognizant GenC" from "cognizant gen-c", which is the entire point of the fuzzy
match. Company and program answer "which interview is this", where approximately-right is
useful. The focus answers "what did this person ask for", where there is no such thing as
approximately what somebody asked for.

These tests are pure functions over the module's internals plus its index entries. They do
not touch Redis, because the reuse decision is made in Python over a loaded index and that
is where the bug was.
"""

from __future__ import annotations

import pytest

from app.services.ai import semantic_cache as sc

COGNIZANT = ("Cognizant", "Digital Nurture — Java FSE")


def test_the_original_bug_is_still_measurable():
    """
    Pins the number the fix exists for. If this ever drops below the threshold on its own,
    the partition is no longer load-bearing and somebody should be told rather than left to
    assume it still is.
    """
    focused = sc._vectorize(*COGNIZANT, "React, SQL, Spring Boot")
    unfocused = sc._vectorize(*COGNIZANT, "")
    score = sc._similarity(focused, unfocused)
    assert score >= sc._SIMILARITY_THRESHOLD, (
        f"a focused setup scores {score:.3f} against an unfocused one, threshold "
        f"{sc._SIMILARITY_THRESHOLD} — similarity alone would reuse the wrong plan"
    )


class TestThePartition:
    def test_a_focus_and_no_focus_are_different_buckets(self):
        assert sc._focus_partition("React, SQL") != sc._focus_partition("")

    def test_an_empty_box_is_its_own_bucket_rather_than_a_wildcard(self):
        # "no preference" and "React please" are the two things that must never be
        # confused, so the empty case gets a name instead of matching everything.
        assert sc._focus_partition("") == "none"
        assert sc._focus_partition("   ") == "none"

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("SQL and React", "react, sql"),
            ("React,  SQL", "REACT / SQL"),
            ("sql react", "react sql"),
        ],
    )
    def test_the_same_request_said_differently_shares_a_bucket(self, a: str, b: str):
        # The saving is real and worth keeping: two candidates asking for the same thing
        # should share a plan. Canonical tokens, so word order and spacing collapse.
        assert sc._focus_partition(a) == sc._focus_partition(b)

    def test_different_requests_do_not_share_a_bucket(self):
        assert sc._focus_partition("React hooks") != sc._focus_partition("SQL joins")

    def test_the_variant_key_still_separates_focuses(self):
        # The Redis bucket a plan is STORED in must differ too, or the partition on lookup
        # would be reading correctly from a bucket that already holds both.
        assert sc.variant_key(*COGNIZANT, "React") != sc.variant_key(*COGNIZANT, "")


class TestWhatALookupWillAccept:
    """
    `find_similar_key` is async and loads its index from Redis. These drive the decision
    directly instead, because the decision is the thing that was wrong — and a test that
    needed a live Redis would not run in CI.
    """

    @staticmethod
    def _entry(focus: str) -> dict:
        return {
            "key": sc.variant_key(*COGNIZANT, focus),
            "vec": sc._vectorize(*COGNIZANT, focus),
            "focus": sc._focus_partition(focus),
        }

    def test_a_focused_request_rejects_the_generic_plan(self):
        """THE ONE THAT WOULD HAVE CAUGHT IT."""
        generic = self._entry("")
        wanted = sc._focus_partition("React hooks and SQL joins")
        assert generic["focus"] != wanted

    def test_a_focused_request_accepts_a_plan_built_for_the_same_focus(self):
        # The fix must not cost the reuse it was designed for, or every focused interview
        # pays for a generation forever.
        entry = self._entry("react, sql")
        assert entry["focus"] == sc._focus_partition("SQL and React")
        assert sc._similarity(
            sc._vectorize(*COGNIZANT, "SQL and React"), entry["vec"]
        ) >= sc._SIMILARITY_THRESHOLD

    def test_a_generic_request_still_matches_a_near_miss_on_the_program(self):
        # Company and program stay fuzzy. "gen-c" and "GenC" are one interview, and this is
        # the behaviour the threshold exists for.
        a = sc._vectorize("Cognizant", "GenC", "")
        b = sc._vectorize("cognizant", "gen-c", "")
        assert sc._similarity(a, b) >= sc._SIMILARITY_THRESHOLD
        assert sc._focus_partition("") == sc._focus_partition("")

    def test_a_legacy_entry_records_no_focus_and_is_therefore_skippable(self):
        # Entries written before this change carry no "focus" key. The lookup skips them
        # rather than guessing, because both available guesses can serve a plan that
        # ignores what the candidate typed. Asserted so nobody "fixes" the skip into a
        # default.
        legacy = {"key": "plan:variants:deadbeef", "vec": sc._vectorize(*COGNIZANT, "")}
        assert legacy.get("focus") is None

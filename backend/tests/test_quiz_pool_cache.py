"""
A generated quiz is reused without becoming the same quiz — tests/test_quiz_pool_cache.py

THE GAP. vector_cache.py's own header names the quiz as an archetype — "the quiz for
'Exception Handling / medium' is the same for everybody" — but `quiz_generation` was not in
CACHEABLE_FEATURES, so every quiz was generated from scratch. Meanwhile the allowlist argued
AGAINST caching it: "unlike a quiz there is no reason to want a DIFFERENT framing of the same
motion next time." Both are right, and they only conflict if the cache stores a QUIZ.

SO IT STORES A POOL, exactly as `question_bank` already does. Generate once, keep the
questions, and serve a random subset per request. Cost falls because the model is not asked
again; freshness survives because two candidates — or one candidate twice — draw different
subsets. Neither half of the tension has to give.

WHY THIS IS SAFE TO SHARE ACROSS CANDIDATES, which is the only question that matters for a
global cache. The generation prompt takes `track_name`, `topics`, `count` and `company` and
nothing else — verified at the call site in api/v1/quiz.py. No resume, no answers, no name, no
typed focus. That is the same tenancy property `question_bank` relies on, and CLAUDE.md's rule
is that nothing derived from one candidate reaches another.

WHAT DOES NOT CHANGE. The curated banks in app/data are still consulted, still top up a
shortfall, and are still the fallback when generation fails. The pool sits between them and
the model: bank first for what it covers, pool instead of a fresh call, model only when the
pool cannot cover the request.
"""

from __future__ import annotations

import random

import pytest

from app.services.ai import vector_cache


class TestTheFeatureIsAllowedToBeCached:
    def test_quiz_pool_is_on_the_allowlist(self):
        assert "quiz_pool" in vector_cache.CACHEABLE_FEATURES

    def test_the_raw_generation_feature_is_still_not(self):
        """
        THE DISTINCTION THAT RESOLVES THE TENSION. `quiz_generation` names one call for one
        request; caching THAT would serve the same quiz back. `quiz_pool` names the reusable
        artefact. Adding the former would reintroduce exactly the problem the allowlist warned
        about.
        """
        assert "quiz_generation" not in vector_cache.CACHEABLE_FEATURES


class TestThePoolKeyCarriesNoCandidateData:
    def test_the_key_is_built_from_syllabus_and_config_only(self):
        from app.api.v1.quiz import _pool_key

        key = _pool_key(track_name="Java FSE", company="Cognizant", topics="Collections, OOP")
        for token in ("Java FSE", "Cognizant", "Collections"):
            assert token.lower() in key.lower()

    def test_the_same_inputs_produce_the_same_key(self):
        from app.api.v1.quiz import _pool_key

        a = _pool_key(track_name="Java FSE", company="Cognizant", topics="Collections")
        b = _pool_key(track_name="Java FSE", company="Cognizant", topics="Collections")
        assert a == b

    def test_a_different_track_is_a_different_key(self):
        # THE VACUITY GUARD: a key that ignored its inputs would make every track share a pool.
        from app.api.v1.quiz import _pool_key

        a = _pool_key(track_name="Java FSE", company="Cognizant", topics="Collections")
        b = _pool_key(track_name="Data Analyst", company="Cognizant", topics="Collections")
        assert a != b


def _q(text: str) -> dict:
    return {
        "question": text,
        "options": ["a", "b", "c", "d"],
        "correct_index": 0,
        "explanation": "because",
        "difficulty": "medium",
        "topic": "Collections",
    }


class TestServingFromThePool:
    def test_a_pool_with_enough_questions_serves_without_generating(self):
        from app.api.v1.quiz import _draw_from_pool

        pool = [_q(f"question {i}") for i in range(20)]
        drawn = _draw_from_pool(pool, want=5, rng=random.Random(1))
        assert len(drawn) == 5

    def test_two_draws_differ_so_a_retake_is_not_identical(self):
        """
        The whole reason this is a pool and not a cached quiz. If two draws matched, the
        allowlist's original objection would stand.
        """
        from app.api.v1.quiz import _draw_from_pool

        pool = [_q(f"question {i}") for i in range(30)]
        a = [x["question"] for x in _draw_from_pool(pool, want=8, rng=random.Random(1))]
        b = [x["question"] for x in _draw_from_pool(pool, want=8, rng=random.Random(2))]
        assert a != b

    def test_a_short_pool_yields_what_it_has_rather_than_repeating(self):
        from app.api.v1.quiz import _draw_from_pool

        pool = [_q(f"question {i}") for i in range(3)]
        drawn = _draw_from_pool(pool, want=10, rng=random.Random(1))
        assert len(drawn) == 3
        assert len({d["question"] for d in drawn}) == 3, "a draw must never duplicate"

    def test_an_empty_pool_draws_nothing(self):
        from app.api.v1.quiz import _draw_from_pool

        assert _draw_from_pool([], want=5, rng=random.Random(1)) == []


class TestThePoolAccumulates:
    def test_new_questions_merge_into_the_existing_pool(self):
        from app.api.v1.quiz import _merge_pool

        existing = [_q("a"), _q("b")]
        merged = _merge_pool(existing, [_q("c")])
        assert [m["question"] for m in merged] == ["a", "b", "c"]

    def test_duplicates_are_not_stored_twice(self):
        from app.api.v1.quiz import _merge_pool

        merged = _merge_pool([_q("a")], [_q("a"), _q("b")])
        assert [m["question"] for m in merged] == ["a", "b"]

    def test_matching_ignores_case_and_surrounding_space(self):
        from app.api.v1.quiz import _merge_pool

        merged = _merge_pool([_q("What is a HashMap?")], [_q("  what is a hashmap?  ")])
        assert len(merged) == 1

    def test_the_pool_is_capped_so_a_row_cannot_grow_without_bound(self):
        """
        A cache row is read and written whole. An uncapped pool would grow until the row itself
        became the cost the cache exists to avoid.
        """
        from app.api.v1.quiz import _MAX_POOL, _merge_pool

        merged = _merge_pool(
            [_q(f"old {i}") for i in range(_MAX_POOL)], [_q("fresh")]
        )
        assert len(merged) == _MAX_POOL
        # The newest question must survive the trim, or the pool can never take new material.
        assert any(m["question"] == "fresh" for m in merged)


class TestAStaleRowNeverReachesACandidate:
    """
    A cache row is JSONB written by whatever version was deployed when it was stored, and rows
    OUTLIVE DEPLOYS. This is the failure mode that matters: a row missing `correct_index` builds
    an answer key with a hole in it, and a row whose `options` became a string renders as
    one-character choices. Both would reach a candidate as a broken quiz rather than as an error
    anybody sees. So rows are validated on load, not trusted.
    """

    def test_a_well_formed_row_passes(self):
        from app.api.v1.quiz import _valid_pool_row

        assert _valid_pool_row(_q("What is a HashMap?")) is True

    @pytest.mark.parametrize(
        ("what", "row"),
        [
            ("not a dict", ["question"]),
            ("missing question", {k: v for k, v in _q("x").items() if k != "question"}),
            ("empty question", {**_q("x"), "question": ""}),
            ("missing correct_index", {k: v for k, v in _q("x").items() if k != "correct_index"}),
            ("options is a string", {**_q("x"), "options": "abcd"}),
            ("only one option", {**_q("x"), "options": ["a"]}),
            ("correct_index out of range", {**_q("x"), "correct_index": 9}),
            ("correct_index negative", {**_q("x"), "correct_index": -1}),
            ("missing explanation", {k: v for k, v in _q("x").items() if k != "explanation"}),
            ("missing difficulty", {k: v for k, v in _q("x").items() if k != "difficulty"}),
        ],
    )
    def test_a_malformed_row_is_rejected(self, what, row):
        from app.api.v1.quiz import _valid_pool_row

        assert _valid_pool_row(row) is False, what

    def test_a_bool_is_not_accepted_as_correct_index(self):
        """
        `True == 1` in Python, so a bool passes a naive isinstance(int) check and would silently
        mark option 1 correct. Worth its own case because it is the one that does not look wrong.
        """
        from app.api.v1.quiz import _valid_pool_row

        assert _valid_pool_row({**_q("x"), "correct_index": True}) is False

    def test_a_stale_pool_degrades_to_a_smaller_pool(self):
        """
        THE BEHAVIOUR, not just the predicate: bad rows are dropped, good ones survive, so a
        partly-stale pool becomes a smaller pool and then a generation - the same path a miss
        takes. It must never raise.
        """
        from app.api.v1.quiz import _valid_pool_row

        rows = [_q("good one"), {"question": "broken"}, _q("good two"), "not even a dict"]
        assert [r for r in rows if _valid_pool_row(r)] == [_q("good one"), _q("good two")]


class TestTheWiringIsReal:
    """A helper nobody calls protects nothing - the NudgeDeck mistake in docs/MISTAKES.md M11."""

    def test_the_endpoint_looks_the_pool_up_before_generating(self):
        import inspect

        from app.api.v1 import quiz

        src = inspect.getsource(quiz)
        lookup = src.index('feature="quiz_pool"')
        launch = src.index("batch_max = int(")
        assert lookup < launch, "the pool must be consulted before the batches are launched"

    def test_the_endpoint_stores_what_it_generated(self):
        import inspect

        from app.api.v1 import quiz

        src = inspect.getsource(quiz)
        assert "vector_cache.store" in src
        assert "_merge_pool" in src

    def test_a_pool_hit_does_not_short_circuit_the_endpoint(self):
        """
        An early `return` on a hit would bypass the quiz row, the session id and the bank
        top-up. The hit must fill `picked` and skip only the generation.
        """
        import inspect

        from app.api.v1 import quiz

        src = inspect.getsource(quiz)
        # THE POOL-HIT BRANCH ONLY - from the draw to the `if not picked:` guard that begins the
        # generation path. Scanning further would catch `return list(quiz.questions)` inside the
        # nested _generate_batch helper, which is that function returning its own batch and has
        # nothing to do with the endpoint returning early.
        hit = src.index("if len(pool) >= request.count:")
        guard = src.index("if not picked:", hit)
        branch = src[hit:guard]
        assert "_served_from_pool = True" in branch, "wrong region located"
        assert "return" not in branch, f"a pool hit must not return early:\n{branch}"

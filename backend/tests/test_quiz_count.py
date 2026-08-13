"""
A quiz has the number of questions you asked for — tests/test_quiz_count.py

REPORTED: "if the user is selecting 5 questions for the quiz then only 3 or 2 are coming".

The generated path validated the model's output with `is_valid=lambda q: bool(q.questions)`.
Non-empty was the ONLY check, so a model asked for five and returning three passed on the
first attempt — and the score was then reported out of three, with nothing on screen saying
the quiz had been silently shortened. Models undershoot a requested count routinely; nothing
downstream was checking, so the count was effectively a suggestion.

The bank path had the same defect one step later, in `min(count, len(pool))`.
"""

from __future__ import annotations

from app.api.v1.quiz import _bank_fill, _PickedQuestion


class TestTheBankCanBackfillAShortGeneration:
    def test_it_returns_exactly_what_was_asked_for(self):
        assert len(_bank_fill(5)) == 5
        assert len(_bank_fill(1)) == 1

    def test_it_never_repeats_a_question_the_model_already_produced(self):
        # Two near-identical questions in one quiz is a more obvious defect to a candidate
        # than the quiz being one question short.
        first = _bank_fill(3)
        texts = [q["question"] for q in first]
        again = _bank_fill(5, exclude=texts)
        assert not ({q["question"] for q in again} & set(texts))

    def test_it_is_shaped_like_the_generated_path(self):
        # The answer key is built from both sources in one loop, so a missing key here is a
        # KeyError mid-request rather than a type error at import.
        for q in _bank_fill(4):
            assert set(q) == set(_PickedQuestion.__annotations__)
            assert isinstance(q["options"], list) and len(q["options"]) >= 2
            assert 0 <= q["correct_index"] < len(q["options"])

    def test_it_returns_fewer_only_when_the_bank_truly_cannot_cover_it(self):
        # The caller surfaces a shortfall rather than papering over it, so this must not
        # silently pad or loop.
        huge = _bank_fill(10_000)
        assert len(huge) < 10_000
        assert len({q["question"] for q in huge}) == len(huge), "no duplicates when exhausted"


class TestTheGeneratedPathDemandsTheFullCount:
    def test_the_validator_checks_the_count_not_just_emptiness(self):
        # Pinned in source: this is a one-line predicate that reads as harmless and was the
        # entire bug. `bool(q.questions)` accepts three questions when five were requested.
        import pathlib

        src = (pathlib.Path(__file__).resolve().parent.parent / "app/api/v1/quiz.py").read_text()
        assert "is_valid=lambda q: len(q.questions) >= request.count" in src
        assert "is_valid=lambda q: bool(q.questions)" not in src

    def test_an_over_delivery_is_trimmed_rather_than_served(self):
        import pathlib

        src = (pathlib.Path(__file__).resolve().parent.parent / "app/api/v1/quiz.py").read_text()
        assert "quiz.questions[: request.count]" in src

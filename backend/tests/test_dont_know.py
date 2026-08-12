"""
The "I don't know" detector — tests/test_dont_know.py

The asymmetry is the whole design and it is what these tests are mostly about. A MISSED
give-up costs the candidate nothing: the interview carries on exactly as it does today. A
FALSE give-up interrupts somebody mid-answer to offer them an easier topic — and it lands on
the students who hedge before explaining, who are usually the careful ones.

So the false-positive suite below is longer than the true-positive one, on purpose.
"""

from __future__ import annotations

import pytest

from app.services.interview.dont_know import said_dont_know


class TestGivingUp:
    @pytest.mark.parametrize(
        "answer",
        [
            "I don't know.",
            "I don't know this one.",
            "I do not know sir.",
            "No idea.",
            "Sorry, no idea about this.",
            "I'm not sure about this one.",
            "Never heard of it.",
            "Sorry sir, I have not studied this one.",
            "We haven't covered this in college.",
            "I can't recall right now.",
            "I forgot this topic.",
            "Skip this one please.",
            "Can we leave this and move on?",
            "Pass.",
            "Next question please.",
            "No clue.",
            "My mind is blank.",
            "Not prepared for this.",
        ],
    )
    def test_declining_is_detected(self, answer: str):
        assert said_dont_know(answer) is True

    @pytest.mark.parametrize("answer", ["no", "Nope", "nothing", "idk", "dunno", "-", "N/A"])
    def test_bare_fragments_are_declining(self, answer: str):
        # No phrase list catches these, and at three words there is no answer to protect.
        assert said_dont_know(answer) is True


class TestNotGivingUp:
    """The expensive errors. Every one of these is a real answer that must not be interrupted."""

    def test_a_hedge_followed_by_a_real_answer(self):
        # THE case this module exists for. Opens with the phrase, then answers correctly.
        assert (
            said_dont_know(
                "I don't know the exact syntax, but you'd use a ConcurrentHashMap and "
                "compute() is atomic so two threads can't interleave."
            )
            is False
        )

    def test_not_knowing_the_WORD_is_not_not_knowing_the_TOPIC(self):
        # Common among students who learned from lectures rather than a textbook, and it is
        # arguably a better answer than reciting the term would have been.
        assert (
            said_dont_know(
                "I don't know the term for it but it's when a subclass gives its own "
                "version of a method the parent already has."
            )
            is False
        )

    @pytest.mark.parametrize(
        "answer",
        [
            "I'm not sure, but I think it's because String is immutable.",
            "I don't remember the name, however the idea is that the JVM caches it.",
            "Not sure sir, although I believe it uses a red-black tree internally.",
            "I don't know exactly, basically it prevents two threads writing at once.",
            "I can't recall the annotation, I think it's @Transactional though.",
        ],
    )
    def test_hedging_before_an_attempt_is_answering(self, answer: str):
        assert said_dont_know(answer) is False

    def test_a_long_answer_that_happens_to_contain_the_phrase(self):
        # Length does most of the work. Nobody says forty words and has given up.
        long = (
            "So a HashMap allows one null key and many null values, and I don't know "
            "whether that is true for Hashtable, but the main difference is that "
            "Hashtable is synchronised and HashMap is not, which is why you would use "
            "ConcurrentHashMap in modern code instead of either of them."
        )
        assert said_dont_know(long) is False

    def test_declining_then_attempting_anyway(self):
        # No hedge word, but a real sentence follows. That is somebody answering after
        # saying they cannot, which is not the same as refusing.
        assert (
            said_dont_know(
                "I don't know. A HashMap stores key value pairs and allows one null key."
            )
            is False
        )

    def test_a_wrong_answer_is_not_a_refusal(self):
        # It must reach the panel's CORRECTION path, not the pivot. Being wrong and being
        # unwilling are different things and get different responses from a real panel.
        assert said_dont_know("A HashMap is synchronised and a Hashtable is not.") is False

    def test_a_short_but_correct_answer(self):
        assert said_dont_know("It's immutable.") is False
        assert said_dont_know("Because String is immutable.") is False

    def test_the_word_pass_inside_a_real_answer(self):
        # "pass" is in the refusal list as a bare word. It is also ordinary vocabulary.
        assert said_dont_know("You pass the object by reference value.") is False

    def test_an_empty_submission_is_not_a_refusal(self):
        # Far more likely a microphone that failed or a mis-click. Pivoting somebody's
        # interview on a hardware fault would be a strange thing to do to them.
        assert said_dont_know("") is False
        assert said_dont_know("   ") is False


class TestTheBiasIsTowardsAnswering:
    def test_ambiguous_input_resolves_to_answered(self):
        # A sentence with a give-up phrase AND real content is an answer. If this ever
        # flips, the detector starts interrupting the students who think out loud.
        borderline = "Not sure, it might be the heap where objects live."
        assert said_dont_know(borderline) is False

    def test_the_threshold_is_where_it_is_claimed_to_be(self):
        # Pins the 25-word rule so a future tweak has to be deliberate. Twenty-six words of
        # anything is an answer; the same opening in six words is not.
        twenty_six = "I don't know " + " ".join(f"word{i}" for i in range(23))
        assert len(twenty_six.split()) > 25
        assert said_dont_know(twenty_six) is False
        assert said_dont_know("I don't know this topic sir") is True

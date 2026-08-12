"""
Did the candidate give up? — services/interview/dont_know.py

A real interviewer, told "I don't know", does not sit in silence and does not plough on to
the next unrelated question. They say "okay — do you know about X?" and find something the
candidate CAN talk about. That is what this exists to trigger.

WHY THIS IS ITS OWN MODULE WITH ITS OWN TESTS.

The naive version is `"i don't know" in answer.lower()`, and it is wrong in both directions
in ways that matter to a real candidate:

    "I don't know the exact syntax, but you'd use a ConcurrentHashMap and the
     compute() method is atomic, so..."

is a GOOD answer that opens with the phrase. Treating it as giving up would interrupt
somebody mid-explanation to offer them an easier topic — humiliating, and it would happen to
the careful students who hedge, which is the worst possible selection.

    "no idea"
    "sorry sir, I have not studied this one"
    "pass"

are all giving up and none of them contain the phrase.

So the rule is not keyword presence. It is: SHORT, and dominated by giving up, with nothing
substantive after it. Length is doing most of the work — somebody who says three hundred
words has not given up whatever they opened with.

FAILING SAFE MEANS FAILING TO *false*. A missed give-up costs the candidate nothing: the
interview continues exactly as it does today, and they get the next planned question. A
false positive interrupts a real answer. The two errors are not symmetric, so every
borderline case here resolves to "they answered".
"""

from __future__ import annotations

import re

#: Phrases that, on their own, are somebody declining to answer.
#:
#: Deliberately includes the Indian-campus register — "sir", "I have not studied it",
#: "leave it" — because the alternative is a detector that works for the way an American
#: writes and not for the way this product's actual users speak.
_GIVE_UP = (
    r"i don'?t know",
    r"i do not know",
    r"dont know",
    r"no idea",
    r"not sure",
    r"i'?m not aware",
    r"i am not aware",
    r"never heard",
    r"not studied",
    r"haven'?t studied",
    r"have not studied",
    r"haven'?t covered",
    r"not covered",
    r"not prepared",
    r"can'?t recall",
    r"cannot recall",
    r"don'?t remember",
    r"do not remember",
    r"forgot",
    r"skip (this|it)",
    r"leave (this|it)",
    r"\bpass\b",
    r"next question",
    r"no clue",
    r"blank",
)

_GIVE_UP_RE = re.compile("|".join(_GIVE_UP), re.IGNORECASE)

#: Words that carry no information about whether the candidate knows the topic.
#:
#: Politeness, filler, pronouns and the scaffolding of a sentence. Removing these is what
#: turns "is the give-up phrase present?" — which is the wrong question — into "is there an
#: ANSWER around it?", which is the right one.
_NOISE = {
    "sir", "maam", "ma", "am", "sorry", "please", "actually", "really", "exactly", "much",
    "well", "hmm", "uh", "um", "umm", "err", "yeah", "yes", "ok", "okay", "right", "now",
    "this", "that", "these", "those", "one", "it", "its", "the", "a", "an", "and", "or",
    "about", "for", "from", "with", "into", "onto", "of", "on", "in", "to", "at", "by",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "can", "could", "will", "would", "shall", "should", "may", "might", "must",
    "i", "me", "my", "we", "our", "us", "you", "your", "he", "she", "they", "them",
    "so", "but", "not", "no", "yet", "still", "just", "very", "too", "also", "any", "all",
    "question", "answer", "topic", "thing", "part", "like", "know", "think", "sure",
}


def _content_words(text: str) -> int:
    """
    How many words carrying actual subject matter are in this text.

    Three-letter minimum on top of the noise list, because the residue of a decline is
    almost entirely short function words and one more filter is cheaper than enumerating
    them all.
    """
    return sum(
        1
        for w in re.findall(r"[a-zA-Z][a-zA-Z'-]*", text.lower())
        if len(w) > 2 and w not in _NOISE
    )


#: A hedge followed by an actual attempt. If any of these appears AFTER the give-up phrase,
#: the candidate carried on and this is not a refusal.
#:
#: "but" is the whole family: "I don't know the term BUT it's when a subclass..." is a
#: correct answer from somebody who does not know the vocabulary, which is a completely
#: different thing from not knowing the topic — and arguably the more common case among
#: students who learned from video lectures rather than a textbook.
_CONTINUES_RE = re.compile(
    r"\b(but|however|although|though|still|basically|i think|i believe|as far as|"
    r"from what|it'?s when|it is when|maybe it|probably it|i guess it)\b",
    re.IGNORECASE,
)

#: Above this, it is an answer whatever it opens with.
#:
#: Twenty-five words is roughly two spoken sentences. Nobody says twenty-five words and has
#: given up; at that length they are explaining something, even if they are explaining it
#: badly, and a badly-explained answer is the orchestrator's business to score rather than
#: this function's business to interrupt.
_MAX_WORDS_TO_COUNT_AS_GIVING_UP = 25

#: Below this, a bare fragment counts even without a matching phrase.
#:
#: "no", "nope", "nothing", "-" are refusals that no phrase list would catch, and at three
#: words there is no answer present to protect.
_BARE_FRAGMENT_WORDS = 3

_BARE_REFUSALS = {
    "no",
    "nope",
    "nothing",
    "none",
    "na",
    "n/a",
    "-",
    "idk",
    "dunno",
    "sorry",
    "skip",
    "pass",
    "next",
    "blank",
}


def said_dont_know(answer: str) -> bool:
    """
    True when the candidate declined to answer rather than answered badly.

    Biased hard towards False. A missed give-up costs nothing — the interview proceeds as it
    always has. A false positive interrupts somebody mid-answer to offer them an easier
    topic, which is both humiliating and lands on exactly the careful students who hedge.
    """
    text = (answer or "").strip()
    if not text:
        # An empty submission is not a spoken "I don't know" — it is far more likely a
        # microphone that failed or a mis-click, and pivoting the interview on a hardware
        # fault would be a strange thing to do to somebody.
        return False

    words = text.split()

    # A bare fragment. No answer is present, so there is nothing to protect.
    if len(words) <= _BARE_FRAGMENT_WORDS:
        stripped = re.sub(r"[^\w/\- ]", "", text).strip().lower()
        if stripped in _BARE_REFUSALS:
            return True
        return bool(_GIVE_UP_RE.search(text))

    # Long enough to be an answer, whatever it opens with.
    if len(words) > _MAX_WORDS_TO_COUNT_AS_GIVING_UP:
        return False

    match = _GIVE_UP_RE.search(text)
    if not match:
        return False

    # Something after the phrase that signals an attempt? Then they carried on.
    tail = text[match.end() :]
    if _CONTINUES_RE.search(tail):
        return False

    # IS THERE AN ANSWER AROUND THE PHRASE? This, not the phrase itself, is the test.
    #
    # Presence was never the right question. "You PASS the object by reference value" is a
    # correct answer containing a refusal word, and "Not sure, it might be the heap where
    # objects live" is a hedged attempt at one — both were false positives until the rule
    # changed to this. What actually distinguishes a decline is that once you remove the
    # phrase, NOTHING IS LEFT: no nouns, no mechanism, no subject matter, just politeness
    # and filler.
    #
    # Two content words is the bar. One survives things like "we haven't covered this in
    # COLLEGE", which is still a decline; two means they named something.
    remainder = text[: match.start()] + " " + tail
    return _content_words(remainder) < 2

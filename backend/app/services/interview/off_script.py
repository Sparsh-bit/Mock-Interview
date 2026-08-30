"""
They asked US something — services/interview/off_script.py

A real candidate does not only answer. They say "sorry, could you repeat that?", "do you mean
in Java specifically?", "what was the question again?" — and until now every one of those was
filed as their ANSWER to the question, counted against the twelve they paid for, and read out
to the report generator as an attempt.

That is the bug this module exists for, and it is worth being exact about why it is a bug and
not merely untidy. A candidate who asks for a repeat has not been asked their question yet.
Consuming it means:

  · the interview is one question shorter than the dashboard promised
  · the report scores "can you say that again?" as their answer on that topic, which reads to
    them as being marked down for something they never said
  · the panel's next turn corrects a wrong answer they did not give

WHAT THIS MODULE DOES AND, MUCH MORE IMPORTANTLY, WHAT IT DOES NOT.

It answers ONE question — did the candidate put a question to the panel instead of answering?
— and nothing else. It does not decide whether an answer was off-topic, whether it was
gibberish, whether it was in another language, or whether it was an attempt to talk the
interviewer out of its instructions.

THOSE ARE DELIBERATELY NOT HERE, and the reason is the same in every case: a real interviewer
does not un-ask a question because you rambled, answered about the wrong thing, or answered in
Hindi. They react — "that's a different question", "say that again in English", "we've drifted"
— and move on, and the question WAS asked. So the right place for those is the panel's own
prompt, which already receives what the candidate last said, and `interview_panel.md` now
carries a section for each. Trying to detect them here would mean a keyword list deciding
whether somebody's answer counted, which is both unreliable and the wrong shape of authority.

FAILING SAFE MEANS FAILING TO "THEY ANSWERED", exactly as `dont_know.py` fails to False, and
for a sharper reason than there. A missed clarification costs the candidate one question out
of twelve — bad. A FALSE one is worse in kind: it does not consume the question, so the same
question is put again, and a candidate whose real answer happened to end in a question mark
("...so it would be the heap, right?") is asked the same thing twice and told nothing about
why. Every borderline case here resolves to "they answered".

`said_dont_know` IS CHECKED FIRST BY THE CALLER, and the ordering matters. "I don't know, can
we move on?" is both a decline and a question; the decline is the better reaction, because it
triggers the pivot — the panel offers them a topic they can stand on — and this module would
merely repeat the question they have just told us they cannot answer.
"""

from __future__ import annotations

import re
from typing import Literal

#: What the candidate's turn was. "" means they answered, which is almost always the case.
OffScript = Literal["", "asked_panel"]

#: Phrases that are unambiguously a request aimed at the interviewer rather than an answer.
#:
#: Deliberately includes the Indian-campus register — "come again", "pardon sir", "one more
#: time" — for the reason `dont_know.py` gives: a detector tuned to the way an American writes
#: is a detector that does not work for this product's actual users.
#:
#: Every entry here is a request about the QUESTION or about being heard. None of them is a
#: hedge, and that is the line: "I think you mean overriding?" is an attempt at an answer and
#: must not be on this list.
_ASKED_US = (
    r"\brepeat\b",
    r"(say|said) (that|it) again",
    r"come again",
    r"pardon( me)?",
    r"one more time",
    r"what was the question",
    r"can you (re)?(phrase|frame|word)",
    r"could you (re)?(phrase|frame|word)",
    r"rephrase",
    r"i (did ?n[o']?t|could ?n[o']?t|can ?n[o']?t) (hear|catch|get) (that|you|it)",
    r"i (did ?n[o']?t|could ?n[o']?t) understand the question",
    r"(sorry|sir|maam)[, ]*(what|come again)\b",
    r"what do you mean",
    r"what does that mean",
    r"which (one|part|context)",
    r"are you asking",
    r"do you mean",
    r"in what (context|sense)",
    r"is (this|that|it) about",
    r"can you (give|explain|clarify)",
    r"could you (give|explain|clarify)",
    r"clarify",
    r"louder",
    r"break(ing)? up",
    r"audio",
    r"cant hear|can'?t hear|not audible|inaudible",
)

_ASKED_US_RE = re.compile("|".join(_ASKED_US), re.IGNORECASE)

#: Above this it is an answer, whatever it contains.
#:
#: Thirty words rather than `dont_know.py`'s twenty-five, and the difference is deliberate: a
#: clarification is often wrapped in politeness ("Sorry sir, I didn't quite catch the second
#: part of that, could you say it once more please?") in a way a bare decline is not. Past
#: thirty words somebody is explaining something, and an explanation that ends in a question is
#: an answer with a question on the end — which is a good answer, not a non-answer.
_MAX_WORDS = 30

#: Words that carry no information about whether an ANSWER is present. The politeness and
#: scaffolding of a request, plus the vocabulary of asking itself.
#:
#: Kept separate from `dont_know._NOISE` rather than imported, because the two are answering
#: different questions and would drift apart under one list: "question" is noise there and is
#: noise here for a different reason, while "know" is noise there (it is part of the decline)
#: and must NOT be noise here (it is content in "how do you know which one to use").
_NOISE = {
    "sir", "maam", "ma", "am", "sorry", "please", "excuse", "kindly", "just", "actually",
    "really", "quite", "bit", "little", "again", "once", "more", "second", "first", "last",
    "hello", "hi", "hey", "yeah", "yes", "no", "ok", "okay", "right", "well", "hmm", "uh",
    "um", "umm", "err", "the", "a", "an", "and", "or", "but", "so", "then", "that", "this",
    "these", "those", "it", "its", "there", "here", "what", "which", "who", "whom", "how",
    "when", "where", "why", "was", "were", "is", "are", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "can", "could", "will", "would", "shall", "should", "may",
    "might", "must", "i", "me", "my", "we", "our", "us", "you", "your", "yours", "he", "she",
    "they", "them", "for", "from", "with", "about", "of", "on", "in", "to", "at", "by",
    "question", "questions", "ask", "asking", "asked", "say", "said", "saying", "tell",
    "hear", "heard", "catch", "understand", "understood", "mean", "means", "meant", "repeat",
    "pardon", "clarify", "rephrase", "context", "part", "one", "thing", "sure", "not",
    # The vocabulary of ASKING to be heard. "Can you speak a bit louder?" is a request about
    # the microphone, and counting "speak" and "louder" as subject matter would classify it as
    # an answer about nothing.
    "speak", "speaking", "spoke", "loud", "louder", "volume", "audio", "mic", "microphone",
    "voice", "sound", "audible", "inaudible", "connection", "network", "breaking", "topic",
    "properly", "clearly", "exactly", "specifically", "answer",
}


def _content_words(text: str) -> int:
    """
    How many words carrying actual subject matter are in this text.

    Three-letter minimum on top of the noise list, on the same reasoning `dont_know.py` gives:
    the residue of a request is almost entirely short function words, and one more filter is
    cheaper than enumerating them all.
    """
    return sum(1 for w in re.findall(r"[a-zA-Z][a-zA-Z'-]*", text.lower()) if _is_content(w))


def _is_content(word: str) -> bool:
    """
    Is this one word subject matter?

    CONTRACTIONS ARE SPLIT AT THE APOSTROPHE, and that is not a nicety — it was a real miss.
    "You're not audible sir" is somebody saying they cannot hear us, and "you're" is one
    six-letter token that is not in the noise list while "you" is. So the whole utterance
    looked like it carried a content word before the phrase, and a candidate reporting a dead
    microphone was told their answer was wrong. Speech-to-text emits these constantly.
    """
    if len(word) <= 2:
        return False
    stem = word.split("'", 1)[0]
    return word not in _NOISE and stem not in _NOISE and len(stem) > 2


#: Below this, a bare fragment counts as a request even with no matching phrase.
#:
#: "Sorry?", "Sir?", "What?", "Huh?" are all somebody asking to be repeated, and no phrase list
#: reaches them. At three words there is no answer present to protect.
_BARE_WORDS = 3

_BARE_REQUESTS = {
    "sorry", "what", "huh", "eh", "again", "pardon", "sir", "maam", "hello", "yes",
    "come again", "say again", "sorry sir", "sorry what", "what sir", "one more time",
    "hello sir", "say that again", "sorry maam", "what was that",
}

#: Content words allowed AFTER the request phrase.
#:
#: THREE, not zero, and that is what lets "what do you mean by IMMUTABLE?" and "is this about
#: Spring or plain Java?" through. Naming the term you did not understand — or the two things
#: you are choosing between — is the most useful form of a clarification and the panel can
#: answer it precisely. Refusing to recognise it would push exactly the candidates who ask
#: good questions back onto the "your answer was wrong" path. Past three they are making a
#: point rather than asking to be repeated.
_MAX_CONTENT_AFTER = 3

#: Content words allowed BEFORE it: none.
#:
#: THIS IS THE RULE THAT DOES THE REAL WORK, and splitting the budget by position rather than
#: counting the whole utterance is what makes it work. Substance BEFORE a question is an
#: ANSWER with a question attached to it —
#:
#:     "A HashMap isn't synchronised, so you'd use ConcurrentHashMap — do you mean under
#:      contention?"
#:
#: — and re-putting the question would throw away everything they just said and ask them for
#: it again. Substance AFTER it is the subject of the question itself. One count over the
#: whole sentence cannot tell those apart, and the first is the expensive one to get wrong.
_MAX_CONTENT_BEFORE = 0


def classify(answer: str) -> OffScript:
    """
    Did the candidate put a question to the PANEL instead of answering theirs?

    Returns "asked_panel" or "". Biased hard towards "": see the module docstring — a false
    positive re-asks a question the candidate has already answered and explains nothing.

    Callers must check `dont_know.said_dont_know` FIRST. A decline that is phrased as a
    question ("I don't know, next one?") should pivot, not be repeated back.
    """
    text = (answer or "").strip()
    if not text:
        # An empty submission is a failed microphone or a mis-click, not a spoken question,
        # and `dont_know.py` reaches the same conclusion about the same input for the same
        # reason. Pivoting or repeating on a hardware fault would be a strange thing to do.
        return ""

    words = text.split()

    if len(words) <= _BARE_WORDS:
        stripped = re.sub(r"[^\w ]", "", text).strip().lower()
        stripped = " ".join(stripped.split())
        if stripped in _BARE_REQUESTS:
            return "asked_panel"
        # A three-word fragment with a question mark and nothing else — "the heap?" — is a
        # hedged ANSWER, not a request, so it is only caught by the phrase list.
        return "asked_panel" if _ASKED_US_RE.search(text) else ""

    if len(words) > _MAX_WORDS:
        return ""

    match = _ASKED_US_RE.search(text)
    if not match:
        return ""

    # IS THERE AN ANSWER AROUND THE REQUEST? Presence of the phrase was never the test, for
    # the same reason it was never the test in `dont_know.py`.
    #
    # "A HashMap is not synchronised, so you'd use ConcurrentHashMap — do you mean under
    # contention?" contains "do you mean" and is a strong answer with a clarifying question
    # attached. It has to stay an answer: re-putting the question would throw away everything
    # they just said and ask them for it again.
    before = _content_words(text[: match.start()])
    after = _content_words(text[match.end() :])
    if before > _MAX_CONTENT_BEFORE:
        return ""
    return "asked_panel" if after <= _MAX_CONTENT_AFTER else ""

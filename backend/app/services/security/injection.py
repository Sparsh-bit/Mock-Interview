"""
Prompt-injection detection — services/security/injection.py

WHY THIS PRODUCT HAS THIS PROBLEM MORE THAN MOST. Everywhere else an LLM reads untrusted
text, the worst case is a rude answer. Here the model's output is a SCORE, and the person
supplying the text is the person being scored. A candidate who can talk the grader into
`overall_score: 95` has not found a prompt-injection curiosity; they have found the product's
only real adversary and its only real prize.

WHAT THIS MODULE IS FOR, AND WHAT IT IS NOT.

It is NOT the defence. The defence is structural and lives in `services/ai/untrusted.py`:
candidate text is never substituted into a system message, and wherever it appears it is
wrapped in a nonce-delimited block the system prompt names as data. That holds whether or
not anything below matches, which is the point — a blocklist of phrasings is a losing race
and must never be the thing standing between a candidate and their own score.

This is DETECTION, for two narrower jobs the structural defence cannot do:

  1. Rank a resume for a human to look at, when the phrasing appears in text the candidate
     took trouble to HIDE (see `services/resume/hidden_text.py`). Hidden text saying "ignore
     previous instructions" is not ambiguous and is worth somebody's attention.
  2. Give the audit log something to count, so "is anyone actually trying this?" has an
     answer that is not a guess.

NOTHING HERE REFUSES AN UPLOAD OR AN ANSWER. A candidate is allowed to write "ignore
previous instructions" in a resume — as a phrase in a project description about LLM safety,
say, which on this product's audience is a genuinely likely sentence. Refusing on a regex
would fail that person for writing about their own work. Flag, log, proceed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

#: Patterns that, in text a candidate supplied, read as an instruction aimed at the grader
#: rather than as a description of the candidate.
#:
#: EACH ONE IS A SHAPE, NOT A STRING. Matching the literal sentence "ignore previous
#: instructions" would be defeated by "ignore the previous instructions", so the gaps are
#: `\W+` and the nouns are alternated. This still loses to a determined rewrite, which is
#: fine and expected — see the module header for why that does not matter.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        re.compile(
            r"\b(ignore|disregard|forget|override|discard)\W+(all\W+|any\W+|the\W+|your\W+|"
            r"these\W+|those\W+|previous\W+|prior\W+|above\W+|earlier\W+)*"
            r"(instruction|prompt|rule|direction|guideline|context|system)",
            re.IGNORECASE,
        ),
    ),
    (
        "score_demand",
        re.compile(
            r"\b(give|award|assign|return|output|set|report|mark)\b[^.\n]{0,60}?\b"
            r"(perfect|maximum|max|full|highest|top|100|10\s*/\s*10|5\s*/\s*5)\b"
            r"[^.\n]{0,40}?\b(score|rating|mark|grade|point)",
            re.IGNORECASE,
        ),
    ),
    (
        "score_demand",
        re.compile(
            r"\b(score|rating|grade)\b[^.\n]{0,40}?\b(must|should|has\s+to|shall)\b"
            r"[^.\n]{0,20}?\b(be|equal)\b[^.\n]{0,20}?\b(100|perfect|maximum|max|10|5)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_reassignment",
        re.compile(
            r"\byou\s+are\s+(now|no\s+longer|actually)\b"
            r"|\bfrom\s+now\s+on\s+you\b"
            r"|\byour\s+new\s+(role|task|instruction|persona|job)\b"
            r"|\bact\s+as\s+(a|an|the)\b[^.\n]{0,30}\b(grader|evaluator|interviewer|assistant)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_token",
        # Chat-template control tokens and pseudo-XML role tags. Nothing a resume contains.
        re.compile(
            r"<\|(im_start|im_end|system|user|assistant|endoftext)\|>"
            r"|\[/?INST\]"
            r"|<\s*/?\s*(system|assistant)\s*>"
            r"|^\s*(system|assistant)\s*:",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "evaluator_address",
        # Text that speaks TO the grader. A resume describes a person; it does not brief
        # the reader on how to read it.
        re.compile(
            r"\b(note|message|instruction|reminder)\s+(to|for)\s+the\s+"
            r"(ai|llm|model|evaluator|grader|assistant|reviewer|system)"
            r"|\b(dear|hello|attention)\s+(ai|llm|model|evaluator|grader)\b"
            r"|\bif\s+you\s+are\s+an?\s+(ai|llm|language\s+model)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "output_hijack",
        re.compile(
            r"\b(respond|reply|answer|output|return)\s+(only\s+)?with\b[^.\n]{0,40}?"
            r"[{\[]|\bdo\s+not\s+(follow|obey|apply)\b[^.\n]{0,30}\b(rubric|rule|instruction)",
            re.IGNORECASE,
        ),
    ),
    (
        "bluff_suppression",
        re.compile(
            r"\b(is_bluffing|bluff(ing)?|confidence_penalty|red_flags?)\b[^.\n]{0,30}?"
            r"\b(false|none|zero|0|empty|skip|ignore)\b",
            re.IGNORECASE,
        ),
    ),
)

#: Characters with no business in extracted document text, whose only use here is to break a
#: pattern above ("ig​nore previous instructions") or to reorder what a human sees
#: relative to what the model reads (the bidi overrides).
#:
#: Note the deliberate absence of ordinary control characters: the extractor already rejects
#: text that is mostly unreadable, and a stray \x0c form feed is a page break, not an attack.
_INVISIBLE = re.compile(
    r"[​-‏‪-‮⁠-⁤⁪-⁯﻿\U000e0000-\U000e007f]"
)

#: Enough obfuscation characters to be a choice rather than an export artefact. A single
#: zero-width joiner survives copy-paste from a lot of places; thirty do not.
_INVISIBLE_FLOOR = 30


@dataclass(frozen=True)
class InjectionScan:
    """What a scan found. Never a verdict — a description."""

    #: Distinct signal names, sorted, so a log line and a stored row are stable.
    signals: tuple[str, ...] = ()
    #: The matched substrings, truncated. For a human deciding whether this is an attack or
    #: a candidate writing about LLM safety.
    samples: tuple[str, ...] = field(default=())
    #: Count of zero-width/bidi characters found.
    invisible_chars: int = 0

    @property
    def suspicious(self) -> bool:
        return bool(self.signals)


#: Longest matched substring kept per signal. An attacker controls the text, so the sample
#: has to be bounded or the log line is.
MAX_SAMPLE = 160

#: Nothing is scanned beyond this. Resume text is already capped at 20k by the extractor,
#: but a GD transcript is not, and these patterns are backtracking-bounded rather than
#: linear — a cap is cheaper than proving they are safe on a megabyte.
MAX_SCAN_CHARS = 40_000


def normalise(text: str) -> str:
    """
    Fold the text into the form the patterns are written against.

    NFKC first, because that is what collapses the homoglyph and full-width tricks — 'ｉｇｎｏｒｅ'
    (U+FF49…) becomes 'ignore', and the mathematical-bold alphabet folds the same way. Then
    the invisible characters come out, so a zero-width space between two letters cannot
    split a word the patterns expect whole.
    """
    folded = unicodedata.normalize("NFKC", text)
    return _INVISIBLE.sub("", folded)


def scan(text: str) -> InjectionScan:
    """
    Look for phrasings aimed at the grader rather than describing the candidate.

    Pure and side-effect free. Callers decide what a signal is worth.
    """
    if not text:
        return InjectionScan()

    clipped = text[:MAX_SCAN_CHARS]
    invisible = len(_INVISIBLE.findall(clipped))
    haystack = normalise(clipped)

    signals: set[str] = set()
    samples: list[str] = []
    for name, pattern in _PATTERNS:
        match = pattern.search(haystack)
        if match is None:
            continue
        signals.add(name)
        samples.append(match.group(0)[:MAX_SAMPLE])

    if invisible >= _INVISIBLE_FLOOR:
        signals.add("invisible_characters")

    return InjectionScan(
        signals=tuple(sorted(signals)),
        samples=tuple(samples),
        invisible_chars=invisible,
    )

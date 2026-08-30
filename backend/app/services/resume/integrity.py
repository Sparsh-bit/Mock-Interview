"""
Is this resume trying something? — services/resume/integrity.py

ONE ANSWER FROM TWO SIGNALS, so the upload path has a single call and the stored record has
a single shape.

  · `hidden_text.scan_pdf` reads the PDF content stream and reports text a human reading
    the printed page would never see
  · `security.injection.scan` reads phrasing and reports text aimed at the grader rather
    than describing the candidate

Separately, each is weak. Hidden text is routine — OCR layers under scans are invisible by
construction, and exporters leave white glyphs in table cells. Injection phrasing on its own
is a sentence this product's own audience plausibly writes, since they are students building
LLM projects and describing them in a CV.

TOGETHER THEY ARE NOT WEAK, and that is the whole design. Text that somebody took the
trouble to make invisible AND that reads as an instruction to the grader is not an
exporter's artefact and is not a project description. That combination is what `severity`
exists to say, so a reviewer opening the flagged list sees the two-signal cases first
instead of wading through OCR layers.

NOTHING HERE REFUSES AN UPLOAD. The structural defence in `services/ai/untrusted.py` is what
protects the score, and it works whether or not this finds anything. This is for the human
question that the structural defence cannot answer: should this candidate's submission be
looked at by a person? So the outcome is a record and a log line, never a rejection — a
false positive here costs a reviewer a minute, and a false rejection costs a real candidate
their interview.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.resume.hidden_text import scan_pdf
from app.services.security import injection

#: How much of the visible text's injection match to keep in the record. Short: a reviewer
#: opening a flagged resume reads the resume, and the record only has to say why it was
#: opened.
_MAX_SAMPLES = 4


@dataclass(frozen=True)
class ResumeIntegrity:
    """The finding, or an empty one. `flagged` is the only field a caller must read."""

    reasons: tuple[str, ...] = ()
    #: "high" when hidden text carries injection phrasing, "medium" when text is hidden but
    #: reads innocently, "low" when the phrasing is there but in plain sight, "" when clean.
    severity: str = ""
    #: The hidden text itself, bounded. Empty when nothing was hidden.
    hidden_text: str = ""
    hidden_chars: int = 0
    #: Injection signal names found anywhere — hidden or visible.
    injection_signals: tuple[str, ...] = ()
    #: The matched phrases, for a reviewer deciding whether this is an attack or a
    #: candidate writing about their LLM safety project.
    samples: tuple[str, ...] = ()

    @property
    def flagged(self) -> bool:
        return bool(self.reasons)

    def as_record(self) -> dict | None:
        """
        The JSONB payload for `resume_files.integrity_flags`, or None when clean.

        NONE RATHER THAN AN EMPTY DICT on a clean resume, deliberately. The column is NULL
        for the overwhelming majority of rows, so "show me the flagged ones" is
        `WHERE integrity_flags IS NOT NULL` — an index-friendly question with a small
        answer, rather than a filter over every resume ever uploaded.
        """
        if not self.flagged:
            return None
        return {
            "reasons": list(self.reasons),
            "severity": self.severity,
            "hidden_text": self.hidden_text,
            "hidden_chars": self.hidden_chars,
            "injection_signals": list(self.injection_signals),
            "samples": list(self.samples[:_MAX_SAMPLES]),
        }


def assess(file_bytes: bytes, resume_text: str) -> ResumeIntegrity:
    """
    Look at the uploaded bytes and the text extracted from them.

    BOTH ARE NEEDED and neither substitutes for the other. `file_bytes` is the only place
    the hidden-text question can be answered, because extraction flattens visible and
    invisible text into the same string. `resume_text` is what the model will actually
    read, so it is what the phrasing question has to be asked about.

    Never raises: `scan_pdf` swallows unparseable input by design, and `injection.scan` is
    pure. This runs on the upload path and must not be able to turn a bad file into a 500.
    """
    hidden = scan_pdf(file_bytes)
    visible = injection.scan(resume_text)

    reasons: list[str] = list(hidden.reasons)
    signals: set[str] = set(hidden.injection_signals) | set(visible.signals)
    samples: list[str] = list(visible.samples)

    if hidden.suspicious and "injection_phrasing" in hidden.reasons:
        severity = "high"
    elif hidden.suspicious:
        severity = "medium"
    elif visible.suspicious:
        # PLAIN SIGHT IS A DIFFERENT ACT. Whether it is an attack at all is genuinely
        # unclear — a project description saying "detects prompt injection" lands here —
        # so it is recorded at the bottom of the pile rather than treated as the same
        # thing as text somebody hid.
        reasons.append("visible_injection_phrasing")
        severity = "low"
    else:
        severity = ""

    if not reasons:
        return ResumeIntegrity()

    return ResumeIntegrity(
        reasons=tuple(sorted(set(reasons))),
        severity=severity,
        hidden_text=hidden.hidden_text,
        hidden_chars=hidden.hidden_chars,
        injection_signals=tuple(sorted(signals)),
        samples=tuple(samples),
    )

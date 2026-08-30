"""
Hidden text in an uploaded PDF — services/resume/hidden_text.py

WHAT THIS EXISTS FOR. `extractor.extract_text` flattens a PDF's text layer into a string,
and that string becomes prompt input. Flattening is lossy in exactly the direction that
matters: it cannot tell text a human can read from text a human cannot, because both are
the same characters in the same content stream. Four ways to be in a PDF and invisible on
the page:

  · a non-stroking colour of white on a white page — `1 1 1 rg`
  · a font size below the threshold of legibility — `/F1 0.3 Tf`
  · a normal font size crushed by the text or transformation matrix — `0.02 0 0 0.02 … Tm`
  · text render mode 3, which the PDF specification (ISO 32000-1, table 106) defines as
    "neither fill nor stroke" — invisible by design

The last one is not an exploit; it is the mechanism OCR uses to lay a searchable text layer
under a scanned image, which is precisely why it is not a refusal below.

So this reads the CONTENT STREAM rather than the extracted text, tracks the graphics state
the way a renderer would, and reports which text would never have reached a human's eye.

THIS FLAGS. IT DOES NOT REFUSE. Every signal here has a legitimate producer — OCR layers,
white text in a table cell left behind by an exporter, 4pt legal boilerplate at the foot of
a template. Refusing on any of them costs a real candidate their upload. What makes a flag
worth a human's time is the SECOND signal: hidden text that also reads like an instruction
to the grader, which is what `services/security/injection.py` adds.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import structlog

from app.services.security import injection

logger = structlog.get_logger(__name__)

#: Effective rendered size, in points, below which text is treated as not meant to be read.
#:
#: 1.0, not 4 or 6. A dense two-column CV genuinely sets its referees line at 6pt and its
#: footer at 5, and flagging those would flag a large share of real resumes. Nothing
#: legitimate is set below a single point: at 1pt a capital letter is roughly the thickness
#: of a printed rule.
_MIN_VISIBLE_POINTS = 1.0

#: How close to the page's white a fill colour has to be before the text it paints is
#: treated as invisible. Perceived luminance, not per-channel distance, because (1, 1, 0.9)
#: is as unreadable on white as (1, 1, 1) is.
#:
#: 0.94 leaves ordinary light-grey subheadings (0.6 grey ≈ 0.6 luminance) well clear.
_MAX_VISIBLE_LUMINANCE = 0.94

#: Hidden characters below this are export noise, not a message. A white space in a table
#: cell and a single crushed glyph at a column break are both routine; a sentence is not.
_MIN_HIDDEN_CHARS = 12

#: Longest hidden-text sample kept. An attacker chooses this text, so the report that gets
#: logged and stored has to be bounded.
MAX_HIDDEN_SAMPLE = 2_000

#: Pages read. A resume is one or two; a 400-page PDF is not one, and walking every page's
#: content stream on the request path is the kind of cost an attacker would choose for us.
_MAX_PAGES = 12


@dataclass(frozen=True)
class HiddenTextReport:
    """
    What was found. `suspicious` is the only field a caller has to understand.
    """

    #: Sorted, stable signal names: "invisible_colour", "tiny_font",
    #: "invisible_render_mode", plus "injection_phrasing" when the hidden text reads like
    #: an instruction to the grader.
    reasons: tuple[str, ...] = ()
    #: The hidden text itself, bounded by MAX_HIDDEN_SAMPLE. What a reviewer needs.
    hidden_text: str = ""
    #: Total hidden characters found, before truncation.
    hidden_chars: int = 0
    #: The injection signals found inside the hidden text, if any.
    injection_signals: tuple[str, ...] = ()

    @property
    def suspicious(self) -> bool:
        return bool(self.reasons)


def _luminance(rgb: tuple[float, float, float]) -> float:
    """Rec. 709 relative luminance. 0 is black, 1 is white."""
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _as_float(value: object) -> float | None:
    """Content-stream operands arrive as pypdf numeric objects; some are not numeric."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _matrix_scale(operands: list) -> float:
    """
    The uniform scale factor of a 6-element PDF matrix [a b c d e f].

    The geometric mean of the two axis lengths, so a matrix that squashes one axis only
    still reads as a shrink. Returns 1.0 for anything unparseable — a matrix we cannot read
    must not become a reason to flag.
    """
    if len(operands) < 4:
        return 1.0
    values = [_as_float(v) for v in operands[:4]]
    if any(v is None for v in values):
        return 1.0
    a, b, c, d = (float(v) for v in values if v is not None)
    x_axis = math.hypot(a, b)
    y_axis = math.hypot(c, d)
    if x_axis <= 0 or y_axis <= 0:
        return 0.0
    return math.sqrt(x_axis * y_axis)


def _text_of(operands: list, operator: bytes) -> str:
    """
    The string a text-showing operator paints.

    Tj and ' and " take one string. TJ takes an array of alternating strings and kerning
    numbers, and the numbers have to be dropped rather than stringified — a resume rendered
    with kerning is every resume, and "-250" between two glyphs is not text.
    """
    if operator in (b"Tj", b"'", b'"'):
        raw = operands[-1] if operands else ""
        return str(raw) if isinstance(raw, str) else ""
    if operator == b"TJ":
        array = operands[0] if operands else []
        if not isinstance(array, list):
            return ""
        return "".join(item for item in array if isinstance(item, str))
    return ""


def _scan_page(page, reader) -> tuple[list[tuple[str, str]], None]:  # noqa: ANN001
    """
    Walk one page's content stream, returning (reason, text) for each hidden run.

    Tracks the pieces of graphics state that decide visibility, the way a renderer would:
    the non-stroking colour, the current font size, the text render mode, and the two
    matrices that scale them. Everything else in the stream is ignored.
    """
    from pypdf.generic import ContentStream  # noqa: PLC0415

    contents = page.get_contents()
    if contents is None:
        return [], None
    stream = ContentStream(contents, reader)

    findings: list[tuple[str, str]] = []

    #: Graphics state. `q`/`Q` save and restore it, so the CTM stack is kept honestly —
    #: a `cm` inside a q…Q block must not leak out and mis-scale the rest of the page.
    fill: tuple[float, float, float] = (0.0, 0.0, 0.0)
    ctm_scale = 1.0
    state_stack: list[tuple[tuple[float, float, float], float]] = []

    font_size = 12.0
    text_scale = 1.0
    render_mode = 0

    for operands, operator in stream.operations:
        if operator == b"q":
            state_stack.append((fill, ctm_scale))
        elif operator == b"Q":
            if state_stack:
                fill, ctm_scale = state_stack.pop()
        elif operator == b"cm":
            ctm_scale *= _matrix_scale(operands)
        elif operator == b"g":  # grey fill
            level = _as_float(operands[0]) if operands else None
            if level is not None:
                fill = (level, level, level)
        elif operator == b"rg":  # RGB fill
            values = [_as_float(v) for v in operands[:3]]
            if len(values) == 3 and all(v is not None for v in values):
                r, g, b = (float(v) for v in values if v is not None)
                fill = (r, g, b)
        elif operator == b"k":  # CMYK fill
            values = [_as_float(v) for v in operands[:4]]
            if len(values) == 4 and all(v is not None for v in values):
                c, m, y, kk = (float(v) for v in values if v is not None)
                fill = ((1 - c) * (1 - kk), (1 - m) * (1 - kk), (1 - y) * (1 - kk))
        elif operator in (b"sc", b"scn"):
            # Colour in whatever space `cs` selected. Numeric operands only: a pattern name
            # is not a colour we can reason about, so it is left alone.
            values = [_as_float(v) for v in operands]
            numeric = [v for v in values if v is not None]
            if len(numeric) == 1:
                fill = (numeric[0], numeric[0], numeric[0])
            elif len(numeric) == 3:
                fill = (numeric[0], numeric[1], numeric[2])
        elif operator == b"BT":
            # A text object resets the text matrix to identity. Render mode and font
            # persist across BT/ET per the spec, so they are deliberately not reset.
            text_scale = 1.0
        elif operator == b"Tf":
            size = _as_float(operands[1]) if len(operands) > 1 else None
            if size is not None:
                font_size = size
        elif operator == b"Tr":
            mode = _as_float(operands[0]) if operands else None
            if mode is not None:
                render_mode = int(mode)
        elif operator == b"Tm":
            text_scale = _matrix_scale(operands)
        elif operator in (b"Tj", b"TJ", b"'", b'"'):
            text = _text_of(operands, operator)
            if not text.strip():
                continue
            effective_points = abs(font_size) * text_scale * ctm_scale
            if render_mode == 3 or render_mode == 7:
                # 3 is invisible; 7 is "clip only", which also paints nothing.
                findings.append(("invisible_render_mode", text))
            elif effective_points < _MIN_VISIBLE_POINTS:
                findings.append(("tiny_font", text))
            elif _luminance(fill) > _MAX_VISIBLE_LUMINANCE:
                findings.append(("invisible_colour", text))

    return findings, None


def scan_pdf(data: bytes) -> HiddenTextReport:
    """
    Report text in `data` that a reader of the printed page would never see.

    NEVER RAISES. This runs on the upload path, on bytes an anonymous user chose, and is
    handed DOCX and rubbish as well as PDFs — a detector that throws on unexpected input
    turns an ordinary bad upload into a 500. Anything it cannot parse is "nothing found",
    which is the safe direction: the structural defence in `services/ai/untrusted.py` does
    not depend on this succeeding.
    """
    try:
        from pypdf import PdfReader  # noqa: PLC0415

        reader = PdfReader(io.BytesIO(data))
        findings: list[tuple[str, str]] = []
        for page in reader.pages[:_MAX_PAGES]:
            page_findings, _ = _scan_page(page, reader)
            findings.extend(page_findings)
    except Exception:  # noqa: BLE001 - see the docstring; any parse failure means "nothing"
        logger.debug("hidden_text_scan_skipped", reason="unparseable")
        return HiddenTextReport()

    if not findings:
        return HiddenTextReport()

    hidden_text = " ".join(text.strip() for _, text in findings).strip()
    hidden_chars = len(hidden_text)
    if hidden_chars < _MIN_HIDDEN_CHARS:
        return HiddenTextReport()

    reasons = {reason for reason, _ in findings}

    # THE SECOND SIGNAL. Hidden text on its own is common enough that a reviewer told to
    # look at every instance would stop looking. Hidden text that reads as an instruction to
    # the grader is the thing worth interrupting somebody for.
    scanned = injection.scan(hidden_text)
    if scanned.suspicious:
        reasons.add("injection_phrasing")

    return HiddenTextReport(
        reasons=tuple(sorted(reasons)),
        hidden_text=hidden_text[:MAX_HIDDEN_SAMPLE],
        hidden_chars=hidden_chars,
        injection_signals=scanned.signals,
    )

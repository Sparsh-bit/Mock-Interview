"""
Resume text extraction — services/resume/extractor.py

Turns an uploaded PDF or DOCX into plain text the AI analyser can read.

Pure functions over bytes: no database, no network, no filesystem. That keeps them
testable without fixtures on disk, and means extraction can run on the bytes we
already hold in memory at upload time rather than downloading the file back out of
Supabase Storage afterwards.

Deliberately conservative about failure. A resume that cannot be read must produce
a clear, catchable error, because the alternative -- storing empty text and
carrying on -- is what left every upload sitting at parsing_status="pending" while
the interview silently ignored the resume. Silence is the failure mode to avoid.
"""

from __future__ import annotations

import io
import re

import structlog

logger = structlog.get_logger(__name__)

#: MIME types we can actually extract, mapped to a short kind for dispatch.
_PDF_MIMES = frozenset(
    {
        "application/pdf",
        "application/x-pdf",
    }
)
_DOCX_MIMES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/docx",
    }
)

#: Below this, extraction "succeeded" but produced nothing usable. The usual cause
#: is a scanned/photographed resume: a PDF whose pages are images, with no text
#: layer at all. That needs OCR, which we do not do -- so say so plainly instead of
#: handing the interviewer three characters of noise.
_MIN_USEFUL_CHARS = 200

#: Upper bound on the text we keep. A resume is one or two pages; anything far
#: beyond that is a portfolio, a thesis, or a PDF with a pathological text layer.
#: The cap matters because this text becomes AI input on every interview plan --
#: unbounded here means unbounded token spend later.
MAX_RESUME_CHARS = 20_000


class ResumeExtractionError(Exception):
    """
    Raised when a resume's text cannot be extracted.

    Carries a message written for the candidate, not the developer: it is surfaced
    directly in the upload response so they know whether to re-export the file,
    convert it, or type their details instead.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        #: Short machine-readable cause, for logs and metrics.
        self.reason = reason


def normalise_whitespace(text: str) -> str:
    """
    Collapse the ragged whitespace PDF extraction produces.

    PDF text layers have no concept of a paragraph: extraction yields hard line
    breaks mid-sentence, runs of spaces where the layout used columns, and blank
    lines between every bullet. Left alone this wastes tokens and makes the text
    harder for the model to read, so lines are joined and blank runs collapsed
    while genuine paragraph breaks are preserved.
    """
    # Normalise line endings first so the paragraph rules below see one form.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Non-breaking spaces and zero-width characters are common in exported PDFs
    # and would otherwise survive into the prompt as invisible noise.
    text = text.replace(" ", " ").replace("​", "")
    # Three or more newlines is never meaningful structure — cap at a blank line.
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse runs of spaces/tabs, but not newlines.
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Trim each line so indentation from a two-column layout does not survive.
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip()


def looks_like_a_resume(text: str) -> bool:
    """
    Cheap sanity check that the extracted text is plausibly a resume.

    Not validation and not security -- purely a guard against the common mistake
    of uploading the wrong PDF (a ticket, an offer letter, a question bank) and
    then wondering why the interviewer asks about nothing on it. Two or more of
    the usual section headings is enough signal; a real resume always has several.
    """
    lowered = text.lower()
    markers = (
        "experience",
        "education",
        "skill",
        "project",
        "internship",
        "certification",
        "achievement",
        "objective",
        "summary",
        "college",
        "university",
        "b.tech",
        "bachelor",
    )
    return sum(1 for marker in markers if marker in lowered) >= 2


def _extract_pdf(data: bytes) -> str:
    """Extract text from every page of a PDF."""
    from PyPDF2 import PdfReader  # noqa: PLC0415
    from PyPDF2.errors import PdfReadError  # noqa: PLC0415

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise ResumeExtractionError(
            "That PDF could not be opened — it may be corrupted. Try re-exporting "
            "or re-saving it, then upload again.",
            reason="pdf_unreadable",
        ) from exc

    # An encrypted PDF yields empty pages rather than raising, so check first and
    # give the real reason instead of the generic "no text found".
    if getattr(reader, "is_encrypted", False):
        # A blank owner password is common on "protected" exports and often opens.
        # decrypt() returns a PasswordType enum whose members are falsy only for
        # failure, so coerce to bool rather than comparing against an int.
        opened = False
        try:
            opened = bool(reader.decrypt(""))
        except Exception:  # noqa: BLE001 - any failure means we cannot read it
            opened = False
        if not opened:
            raise ResumeExtractionError(
                "That PDF is password-protected, so its text cannot be read. "
                "Upload an unprotected copy.",
                reason="pdf_encrypted",
            )

    parts: list[str] = []
    for index, page in enumerate(reader.pages):
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page must not lose the rest
            logger.warning("resume_pdf_page_extract_failed", page=index)
    return "\n".join(parts)


def _extract_docx(data: bytes) -> str:
    """Extract text from a DOCX: paragraphs plus table cells."""
    import docx  # noqa: PLC0415

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - python-docx raises several types
        raise ResumeExtractionError(
            "That DOCX could not be opened — it may be corrupted, or it may be an "
            "older .doc file saved with a .docx name. Re-save it as .docx and try "
            "again.",
            reason="docx_unreadable",
        ) from exc

    parts = [p.text for p in document.paragraphs]
    # Many resume templates lay everything out in a table, so paragraphs alone
    # would come back nearly empty and look like a scanned file.
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def extract_text(data: bytes, mime_type: str, *, filename: str = "") -> str:
    """
    Extract normalised plain text from resume file bytes.

    Raises ResumeExtractionError with a candidate-facing message if the file
    cannot be read, is the wrong format, or contains no text layer.
    """
    if not data:
        raise ResumeExtractionError(
            "That file is empty. Upload the resume file itself, not a shortcut or "
            "link to it.",
            reason="empty_file",
        )

    kind = mime_type.split(";")[0].strip().lower()
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # Browsers occasionally send a generic or wrong content type (notably
    # application/octet-stream from some file managers), so fall back to the
    # extension rather than rejecting a perfectly good PDF.
    if kind in _PDF_MIMES or (kind not in _DOCX_MIMES and suffix == "pdf"):
        raw = _extract_pdf(data)
    elif kind in _DOCX_MIMES or suffix == "docx":
        raw = _extract_docx(data)
    else:
        raise ResumeExtractionError(
            f"Unsupported resume format ({mime_type or 'unknown'}). Upload a PDF "
            "or DOCX.",
            reason="unsupported_type",
        )

    text = normalise_whitespace(raw)

    if len(text) < _MIN_USEFUL_CHARS:
        raise ResumeExtractionError(
            "No readable text was found in that file. If it is a scan or a photo "
            "of your resume, the text cannot be read — upload the original PDF "
            "exported from your editor instead.",
            reason="no_text_layer",
        )

    if len(text) > MAX_RESUME_CHARS:
        logger.info(
            "resume_text_truncated",
            original_chars=len(text),
            kept_chars=MAX_RESUME_CHARS,
        )
        text = text[:MAX_RESUME_CHARS]

    return text

"""
What the uploaded bytes actually are — services/resume/file_safety.py

THE RESUME UPLOAD IS THE ONE PLACE this product takes arbitrary bytes chosen by the caller,
hands them to a third-party document parser, and writes them to shared storage. Everything
else a user can reach is a JSON body checked against a Pydantic schema. So this is where the
interesting attacks are, and before this module existed each of the three below was measured
succeeding against the live path.

  ACTIVE CONTENT — a document that does something when opened. A PDF carrying
  `/Names << /JavaScript … >>`, and one carrying `/OpenAction << /S /Launch … >>` with an
  embedded `MZ` payload, were both accepted: text extracted, row written, file stored. So
  was a DOCX carrying `word/vbaProject.bin`. The file is then downloadable, which made the
  product a delivery mechanism for a macro-bearing document that arrives looking like a CV.

  DECOMPRESSION — a DOCX is a zip. A 399 KB archive was measured taking resident memory
  from 440 MB to 834 MB before python-docx refused it. There WAS a zip-bomb test and it
  passed, because it asserted the status code and the status code was right: the refusal
  simply happened after the expansion. The upload size cap measures the COMPRESSED size and
  cannot see this coming.

  TYPE CONFUSION — dispatch followed `file.content_type` and the filename extension, both
  chosen by the caller, with "does the parser cope" as the real check. That works by
  accident and it means a string the caller wrote decided which parser saw the bytes.

WHY THIS REFUSES WHEN `hidden_text.py` ONLY FLAGS. The distinction is whether a legitimate
producer exists. Invisible text has several — OCR layers are invisible by construction — so
refusing on it would cost real candidates their upload. A resume does not need JavaScript,
does not need a VBA project, does not need to fetch a template over the network and does not
need to expand to 400 MB. There is nothing legitimate to protect, so these are hard refusals
with a message written for the candidate.

THE FALSE POSITIVE IS STILL THE EXPENSIVE FAILURE, which is why the checks below are narrow
on purpose: `/OpenAction` is not a refusal, because `[3 0 R /Fit]` means "open at page one"
and half the exporters in the world write it; a URI link annotation is not a refusal,
because a resume links to GitHub; an External relationship is not a refusal unless it is one
Word RESOLVES on open, because a LinkedIn hyperlink is the commonest external target there
is. Each of those is pinned by a test.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

#: What `verify` is willing to say a file is.
#:
#: `pptx` JOINED THIS FOR THE DECK EVALUATOR, and it goes through the identical archive
#: and member checks a DOCX does — it is the same OOXML container with a different main
#: part, so every one of the three attacks in the module docstring applies unchanged. A
#: presentation has no more business carrying a VBA project than a resume does.
#:
#: LEGACY `.ppt` IS DELIBERATELY ABSENT. It is an OLE compound file, not a zip, so none of
#: the checks below can see inside it — and it is the format whose macro story is worst.
#: `sniff` returns None for it and the candidate is told to save as .pptx.
DocumentKind = Literal["pdf", "docx", "pptx"]

# ── Archive limits ──────────────────────────────────────────────────────────────

#: Total expanded size allowed across all members.
#:
#: 64 MB against a 10 MB upload cap. A real resume's largest member is `word/document.xml`
#: plus any embedded images, and a text-heavy 40-page academic CV measures well under a
#: megabyte — the headroom check in the tests asserts a large one stays below a tenth of
#: this. The number is chosen so that a worker holding several concurrent uploads at the
#: ceiling is still nowhere near a container limit.
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024

#: Expansion ratio at which an archive stops being a document.
#:
#: DEFLATE on XML routinely reaches 10:1 and highly repetitive XML can reach 40:1 honestly,
#: so 200 is deliberately far above anything a real file produces. This is the second line
#: anyway; the byte ceiling above is the one that does the work.
MAX_COMPRESSION_RATIO = 200

#: Below this, ratio is not evidence. A 300-byte `.rels` file compressing to 12 bytes is a
#: ratio of 25 and means nothing, and a tiny member cannot exhaust anything.
_RATIO_FLOOR_BYTES = 1024 * 1024

#: A DOCX has on the order of a dozen parts, plus one per embedded image. Thousands of
#: members is a different kind of file, and each one costs a directory entry and a syscall.
MAX_ARCHIVE_MEMBERS = 512

#: Read budget per member while verifying the declared sizes. See `inspect_archive`.
_READ_CHUNK = 512 * 1024

# ── What must not be in a DOCX ──────────────────────────────────────────────────

#: Archive members that carry executable or embeddable content.
#: `vbaproject.bin` is matched as a SUBSTRING, so it catches `word/vbaProject.bin` and
#: `ppt/vbaProject.bin` alike — the part name differs by package, the payload does not.
#: The embeddings directory has to be named per package, hence both.
_MACRO_MEMBERS = (
    "vbaproject.bin",
    "vbadata.xml",
    "word/embeddings/",
    "ppt/embeddings/",
    "macros/",
)

#: Content-type declarations that mean "this document can run code".
#: `macroenabled` alone already catches every one of these — the two specific strings are
#: kept because they name what was actually measured getting through, and the PowerPoint
#: one is listed for the same reason now that presentations are accepted.
_MACRO_CONTENT_TYPES = (
    b"macroenabled",
    b"ms-office.vbaproject",
    b"ms-word.document.macroenabled",
    b"ms-powerpoint.presentation.macroenabled",
)

#: Relationship types Word RESOLVES when the document opens, rather than when a human clicks.
#: An External Target on one of these is fetched on open, which is the mechanism behind a
#: known family of Office exploits. `hyperlink` is deliberately absent — a resume linking to
#: LinkedIn is the commonest external relationship there is and nothing fetches it unasked.
#:
#: MATCHED AS THE LAST SEGMENT OF THE TYPE URI, never as a substring of the file. The first
#: version of this searched the whole `.rels` body for these words and flagged every resume
#: containing a LinkedIn link — because the standard relationships namespace is
#: `schemas.openxmlformats.org/package/2006/relationships`, and "package" is on this list.
#: A test caught it. Substring matching against a document that contains its own schema URLs
#: is a false-positive machine.
_AUTO_RESOLVED_RELATIONSHIPS = frozenset(
    {
        "attachedtemplate",
        "frame",
        "oleobject",
        "package",
        "subdocument",
        "externallinkpath",
        "aformdata",
    }
)

#: One `<Relationship .../>` element. Parsed with a regex rather than an XML parser on
#: purpose: this is attacker-supplied XML, `xml.etree` is not hardened against entity
#: expansion, and adding `defusedxml` to parse four attributes is a dependency for nothing.
#: The regex cannot be tricked into missing an element in a way that matters, because a
#: relationship Word does not parse is a relationship Word does not resolve.
_RELATIONSHIP = re.compile(rb"<Relationship\b[^>]*>", re.IGNORECASE)
_REL_TYPE = re.compile(rb'Type\s*=\s*"([^"]*)"', re.IGNORECASE)
_REL_MODE = re.compile(rb'TargetMode\s*=\s*"([^"]*)"', re.IGNORECASE)

#: Relationship elements examined per `.rels` member. A real one has a handful.
_MAX_RELATIONSHIPS = 512

# ── What must not be in a PDF ───────────────────────────────────────────────────

#: Action types that do something other than move around the document.
_DANGEROUS_ACTIONS = frozenset(
    {"/JavaScript", "/Launch", "/SubmitForm", "/ImportData", "/GoToR", "/GoToE", "/Rendition"}
)

#: How many objects the walk will visit before giving up. A PDF can contain reference
#: cycles and can be built to have an enormous object graph; the walk is on the request
#: path, so it is bounded rather than exhaustive. A document that hits this ceiling is
#: refused, not accepted — an unauditable document is not a resume.
_MAX_PDF_NODES = 20_000


@dataclass(frozen=True)
class ArchiveReport:
    """What the central directory and a bounded read say about a zip."""

    uncompressed_bytes: int = 0
    compressed_bytes: int = 0
    members: int = 0
    #: None when the archive is acceptable; otherwise the machine-readable refusal reason.
    refuse_reason: str | None = None
    #: The member that caused the refusal, for the log line. Never shown to the candidate.
    offending_member: str = ""


class UnsafeDocument(Exception):
    """
    Raised when a document carries something a resume has no business carrying.

    Shaped like `ResumeExtractionError` — a candidate-facing message plus a short machine
    reason — but a distinct type so `file_safety` does not have to import from `extractor`
    and create a cycle. `extractor` translates it.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


# ── Type detection ──────────────────────────────────────────────────────────────


def sniff(data: bytes) -> DocumentKind | None:
    """
    The document kind, decided by the bytes and nothing else.

    Returns None when the bytes are neither a PDF nor a DOCX — including for a plain zip,
    which shares its signature with DOCX. `PK\\x03\\x04` is not evidence of a Word document;
    the OOXML structure is, so the manifest and the main document part are both required.

    A leading BOM or stray whitespace before `%PDF-` is tolerated because real exporters
    produce it and every PDF reader accepts it.
    """
    if not data or len(data) < 8:
        return None

    head = data[:1024].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"%PDF-"):
        return "pdf"

    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                # NOT SLICED. `namelist()` reads the central directory, which is already
                # in memory, so there is nothing to save by truncating it — and truncating
                # it means a valid document with many embedded images fails to be
                # recognised AS a document and gets refused for the wrong reason. The
                # member count is `inspect_archive`'s question, and it gives the accurate
                # refusal.
                names = {name.lower() for name in archive.namelist()}
        except (zipfile.BadZipFile, OSError, ValueError):
            return None
        # BOTH required. The manifest alone is any OOXML file — a spreadsheet has one too.
        if "[content_types].xml" not in names:
            return None
        if "word/document.xml" in names:
            return "docx"
        # The main part is what distinguishes a presentation from a document or a workbook.
        # `ppt/presentation.xml` is mandatory in the OOXML presentation package.
        if "ppt/presentation.xml" in names:
            return "pptx"
        return None

    return None


# ── Archive inspection ──────────────────────────────────────────────────────────


def _member_is_unsafe(name: str) -> bool:
    """Zip-slip: a member name that resolves outside the archive root."""
    normalised = name.replace("\\", "/")
    if normalised.startswith("/") or normalised[1:3] == ":/":
        return True
    return any(part == ".." for part in normalised.split("/"))


def inspect_archive(data: bytes) -> ArchiveReport:
    """
    Read a zip's shape without expanding it, then verify the shape it claimed.

    TWO PASSES, AND BOTH ARE NECESSARY.

    The first reads the central directory, which gives every member's declared uncompressed
    size for free — no decompression at all. That is what turns the measured 394 MB spike
    into a few kilobytes of directory parsing, and it catches an honest bomb, which is what
    a bomb normally is: its declared sizes are true because the attacker wants them true.

    The second exists because those sizes are attacker-controlled and a forged directory
    would walk straight past the first. So each member is decompressed in chunks with a
    RUNNING TOTAL against the same ceiling, and the read stops the moment the ceiling is
    crossed. The cost of a lie is therefore bounded by `MAX_UNCOMPRESSED_BYTES` rather than
    by whatever the attacker chose — which is the difference between a guard and a
    suggestion.

    Never raises. A malformed archive is reported, not thrown, because the caller is
    already handling "this file cannot be read" and a second failure mode there buys
    nothing.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError):
        return ArchiveReport(refuse_reason=None)

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            return ArchiveReport(
                members=len(infos),
                refuse_reason="archive_unsafe",
                offending_member=f"{len(infos)} members",
            )

        declared_total = 0
        compressed_total = 0
        for info in infos:
            if _member_is_unsafe(info.filename):
                return ArchiveReport(
                    members=len(infos),
                    refuse_reason="archive_unsafe",
                    offending_member=info.filename,
                )
            declared_total += info.file_size
            compressed_total += info.compress_size
            if declared_total > MAX_UNCOMPRESSED_BYTES:
                return ArchiveReport(
                    uncompressed_bytes=declared_total,
                    compressed_bytes=compressed_total,
                    members=len(infos),
                    refuse_reason="archive_too_large",
                    offending_member=info.filename,
                )

        if (
            declared_total > _RATIO_FLOOR_BYTES
            and compressed_total > 0
            and declared_total / compressed_total > MAX_COMPRESSION_RATIO
        ):
            return ArchiveReport(
                uncompressed_bytes=declared_total,
                compressed_bytes=compressed_total,
                members=len(infos),
                refuse_reason="archive_too_large",
                offending_member="compression ratio",
            )

        # ── Second pass: does it expand to what it said? ─────────────────────
        actual_total = 0
        for info in infos:
            try:
                with archive.open(info) as member:
                    while True:
                        chunk = member.read(_READ_CHUNK)
                        if not chunk:
                            break
                        actual_total += len(chunk)
                        if actual_total > MAX_UNCOMPRESSED_BYTES:
                            return ArchiveReport(
                                uncompressed_bytes=actual_total,
                                compressed_bytes=compressed_total,
                                members=len(infos),
                                refuse_reason="archive_too_large",
                                offending_member=info.filename,
                            )
            except (zipfile.BadZipFile, OSError, ValueError, EOFError):
                # A member that will not decompress is python-docx's problem, not a
                # refusal here — the extractor's own error is the better message.
                continue

        return ArchiveReport(
            uncompressed_bytes=actual_total,
            compressed_bytes=compressed_total,
            members=len(infos),
        )


def _scan_ooxml_members(data: bytes, kind: DocumentKind) -> tuple[str, str] | None:
    """
    Look for macros, OLE objects and auto-resolved external references.

    ONE SCAN FOR EVERY OOXML PACKAGE. A .pptx is the same zip with a different main part,
    so the members that can carry executable content are the same members and the checks
    below are byte-for-byte the ones a .docx gets. `kind` only names the reason, so a log
    line and a test can tell a presentation refusal from a document one.

    Returns `(reason, member)` or None. Reads only the parts that can carry the evidence,
    each with a bounded read — the archive has already passed `inspect_archive`, so the
    sizes here are known, but a bounded read costs nothing and keeps this safe to call on
    its own.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError):
        return None

    with archive:
        for name in archive.namelist():
            lowered = name.lower()
            if any(marker in lowered for marker in _MACRO_MEMBERS):
                return (f"{kind}_macro", name)

        for name in archive.namelist():
            lowered = name.lower()
            if lowered == "[content_types].xml":
                try:
                    with archive.open(name) as member:
                        body = member.read(_READ_CHUNK).lower()
                except (zipfile.BadZipFile, OSError, ValueError):
                    continue
                if any(marker in body for marker in _MACRO_CONTENT_TYPES):
                    return (f"{kind}_macro", name)

            if lowered.endswith(".rels"):
                try:
                    with archive.open(name) as member:
                        body = member.read(_READ_CHUNK)
                except (zipfile.BadZipFile, OSError, ValueError):
                    continue
                if b"targetmode" not in body.lower():
                    continue
                # PER ELEMENT. Both halves have to be true of the SAME relationship: an
                # External target, and a type Word resolves without being asked. Checking
                # them across the whole file would flag a document that has an ordinary
                # external hyperlink and, separately, an internal OLE part.
                for element in _RELATIONSHIP.findall(body)[:_MAX_RELATIONSHIPS]:
                    mode = _REL_MODE.search(element)
                    if mode is None or mode.group(1).lower() != b"external":
                        continue
                    rel_type = _REL_TYPE.search(element)
                    if rel_type is None:
                        continue
                    # The last path segment of the type URI is the relationship's name.
                    leaf = rel_type.group(1).rstrip(b"/").rsplit(b"/", 1)[-1].lower()
                    if leaf.decode("ascii", "ignore") in _AUTO_RESOLVED_RELATIONSHIPS:
                        return (f"{kind}_remote_reference", name)

    return None


# ── PDF inspection ──────────────────────────────────────────────────────────────


def _pdf_active_content(data: bytes) -> str | None:
    """
    Walk the object graph for anything that acts. Returns the finding, or None.

    STRUCTURAL RATHER THAN A BYTE GREP, deliberately. Since PDF 1.5 the catalog can live
    inside a compressed object stream, so the literal text `/JavaScript` need not appear in
    the file at all — a grep would miss the very documents most likely to be deliberate.
    pypdf resolves object streams and indirect references, so walking from the trailer sees
    what a reader sees.

    Bounded by `_MAX_PDF_NODES` with a visited set, because the graph can contain cycles and
    can be made enormous, and this runs on the request path.
    """
    from pypdf import PdfReader  # noqa: PLC0415
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:  # noqa: BLE001 - an unopenable PDF is the extractor's error to give
        return None

    seen: set[int] = set()
    budget = _MAX_PDF_NODES

    def walk(node: object) -> str | None:
        nonlocal budget
        if budget <= 0:
            return "object graph too large to audit"
        budget -= 1

        if isinstance(node, IndirectObject):
            key = id(node.idnum), node.generation
            marker = hash(key)
            if marker in seen:
                return None
            seen.add(marker)
            try:
                return walk(node.get_object())
            except Exception:  # noqa: BLE001 - a broken reference is not active content
                return None

        if isinstance(node, DictionaryObject):
            #: `/S` names the action type. This is the check that lets `/OpenAction`
            #: through when it is a destination and refuses it when it is a program.
            subtype = node.get("/S")
            if isinstance(subtype, NameObject) and str(subtype) in _DANGEROUS_ACTIONS:
                return f"action {subtype}"
            if "/JS" in node:
                return "embedded script"
            if "/JavaScript" in node:
                return "JavaScript name tree"
            if "/EmbeddedFiles" in node or "/EF" in node:
                return "embedded file"
            if "/XFA" in node:
                return "XFA form"
            if "/RichMedia" in node or "/Movie" in node or "/Sound" in node:
                return "embedded media"
            for key, value in node.items():
                #: `/Parent` is skipped: following it walks back up the page tree on every
                #: page and turns a shallow walk into a quadratic one for no new objects.
                if str(key) == "/Parent":
                    continue
                found = walk(value)
                if found:
                    return found
            return None

        if isinstance(node, ArrayObject):
            for item in node:
                found = walk(item)
                if found:
                    return found
            return None

        return None

    try:
        root = reader.trailer.get("/Root")
        found = walk(root)
        if found:
            return found
        for page in reader.pages[:64]:
            found = walk(page)
            if found:
                return found
    except Exception:  # noqa: BLE001 - a document we cannot audit is handled below
        return None

    return None


# ── The one entry point ─────────────────────────────────────────────────────────


#: What the resume upload accepts. The historical behaviour of `verify`, and its default,
#: so adding presentations to `DocumentKind` did not quietly make a slide deck a valid CV.
RESUME_KINDS: tuple[DocumentKind, ...] = ("pdf", "docx")

#: What the deck evaluator accepts. A deck is a presentation or a PDF export of one; a
#: Word document is not a deck and is refused with a message that says so.
DECK_KINDS: tuple[DocumentKind, ...] = ("pdf", "pptx")

#: How each kind is named to somebody who just had their file refused.
_KIND_NAMES: dict[DocumentKind, str] = {
    "pdf": "PDF",
    "docx": "Word document",
    "pptx": "PowerPoint presentation",
}


def _accepted_phrase(allowed: tuple[DocumentKind, ...]) -> str:
    """"a PDF or a Word document" — the accepted kinds, written for a human."""
    names = [f"a {_KIND_NAMES[k]}" for k in allowed]
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} or {names[-1]}"


def verify(
    data: bytes,
    *,
    declared_mime: str = "",
    filename: str = "",
    allowed: tuple[DocumentKind, ...] = RESUME_KINDS,
) -> DocumentKind:
    """
    Decide what this file is, and refuse it if it carries something the caller should not take.

    Returns the kind, so the caller dispatches on the answer rather than on what the
    caller was told. `declared_mime` and `filename` are accepted only so a refusal can be
    logged against what was claimed; NEITHER influences the decision.

    `allowed` IS THE CALLER'S LIST, AND IT DEFAULTS TO THE RESUME'S. `sniff` recognising a
    format is not the same as an endpoint wanting it: presentations were added to
    `DocumentKind` for the deck evaluator, and without this the resume upload would have
    started accepting a slide deck as a CV on the same commit. Every caller states what it
    takes; the default is what this module accepted before there was more than one caller.

    Raises `UnsafeDocument` with a message written for the candidate.
    """
    kind = sniff(data)
    if kind is None or kind not in allowed:
        # SNIFFED-BUT-UNWANTED READS DIFFERENTLY FROM UNRECOGNISED, because the fix is
        # different: one person uploaded the wrong file, the other exported it wrongly.
        if kind is not None:
            raise UnsafeDocument(
                f"That is a {_KIND_NAMES[kind]}, and this upload takes "
                f"{_accepted_phrase(allowed)}.",
                reason="unsupported_type",
            )
        raise UnsafeDocument(
            f"That file is not {_accepted_phrase(allowed)} "
            f"({declared_mime or 'unknown type'}). "
            "Upload the document itself — a PDF exported from your editor works best.",
            reason="unsupported_type",
        )

    if kind in ("docx", "pptx"):
        readable = _KIND_NAMES[kind]
        report = inspect_archive(data)
        if report.refuse_reason == "archive_too_large":
            logger.warning(
                "upload_archive_bomb",
                declared_mime=declared_mime,
                compressed_bytes=report.compressed_bytes,
                uncompressed_bytes=report.uncompressed_bytes,
                members=report.members,
                offending_member=report.offending_member,
            )
            raise UnsafeDocument(
                f"That {readable} expands to far more data than a document contains, so it "
                "was not opened. Re-save it from the app that made it, or export it as a "
                "PDF, and try again.",
                reason="archive_too_large",
            )
        if report.refuse_reason == "archive_unsafe":
            logger.warning(
                "upload_archive_unsafe",
                declared_mime=declared_mime,
                offending_member=report.offending_member,
                members=report.members,
            )
            raise UnsafeDocument(
                f"That {readable} is not structured like a document and was not opened. "
                "Re-save it from the app that made it, or export it as a PDF, and try again.",
                reason="archive_unsafe",
            )

        macro_found = _scan_ooxml_members(data, kind)
        if macro_found is not None:
            reason, member = macro_found
            logger.warning("upload_active_content", kind=kind, reason=reason, member=member)
            raise UnsafeDocument(
                f"That {readable} contains a macro or a linked object, so it was not "
                "opened. It does not need either, and a document that can run code is not "
                "something this service will store. Export it as a PDF and upload that "
                "instead.",
                reason=reason,
            )

    if kind == "pdf":
        active = _pdf_active_content(data)
        if active is not None:
            logger.warning(
                "upload_active_content", kind="pdf", reason=active, declared_mime=declared_mime
            )
            raise UnsafeDocument(
                # NAMES NO PDF INTERNALS. The candidate did not choose `/OpenAction` and
                # cannot act on being told about it — very often their employer's or
                # university's template put it there. What they can act on is the fix.
                "That PDF contains active content — a script, an embedded file, or a form "
                "action — so it was not opened. Resumes do not need any of those. Open it "
                "and use Print to PDF to make a flat copy, then upload that.",
                reason="active_content",
            )

    return kind

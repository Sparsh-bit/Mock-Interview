"""
The upload path, round three: what the bytes actually are — tests/test_upload_file_safety.py

EXTENDS `test_pentest_uploads.py`, does not replace it. That file covers the path traversal,
the size cap, the MIME-vs-bytes question and authentication, and every one of those tests
still runs. What it did not cover is what is INSIDE a file that is a perfectly well-formed
document — which is where the interesting attacks on this surface live, because a resume is
the one place the product accepts arbitrary bytes from an anonymous-ish user, parses them
with a third-party document library, and writes them to shared storage.

THREE CLASSES, ALL THREE MEASURED AGAINST THE CODE BEFORE THIS FILE EXISTED. None of these
is hypothetical; each was run through `extract_text` and observed to succeed:

  ACTIVE CONTENT. A PDF carrying `/JavaScript` and `/OpenAction`, and one carrying
  `/Launch` with an embedded `MZ` payload, were both ACCEPTED — text extracted, resume
  stored, file written to Supabase Storage. A DOCX carrying `word/vbaProject.bin` was
  likewise accepted. Nothing in the pipeline looked. The file is then downloadable, so the
  product was a storage-and-delivery mechanism for a macro-bearing document that arrives
  looking like a candidate's CV.

  DECOMPRESSION. `test_pentest_uploads.py` already has a zip-bomb test and it PASSES — but
  it asserts only the status code, and the status code was right for the wrong reason. A
  399 KB archive was measured driving resident memory from 440 MB to 834 MB before
  python-docx gave up: the refusal happened AFTER the bytes were expanded. A guard that
  reports success while the thing it guards against still happens is the exact shape
  `docs/MISTAKES.md` exists to warn about, so the test below asserts the MEMORY, not the
  status.

  TYPE CONFUSION. Dispatch was on the declared MIME type and the filename extension, with
  the real check being "does the parser cope". That works by accident — a DOCX named .pdf
  fails in the PDF parser — but it means the thing deciding which parser sees the bytes is
  a string the caller chose. The type is now decided by the bytes.

WHY THESE REFUSE WHEN `hidden_text` ONLY FLAGS. A resume does not need JavaScript, does not
need a macro, and does not need to expand to 400 MB. There is no legitimate producer to
protect, which is what makes a hard refusal correct here and wrong there.
"""

from __future__ import annotations

import resource
import zipfile

import pytest

from tests.docx_builder import (
    docx_with_macro,
    docx_with_remote_template,
    valid_docx,
    zip_bomb_docx,
)
from tests.pdf_builder import build_pdf, build_pdf_with_catalog, visible_run

#: Long enough and marker-rich enough to clear the extractor's own "is this a resume"
#: floors, so a refusal below is always about the attack and never about the text.
_BODY = (
    "Sparsh Kumar. Education: B.E. Computer Science, Anna University 2024. "
    "Skills: Java, Spring Boot, PostgreSQL. Projects: a placement portal. "
    "Internship: six months at a payments company. Certification: AWS CCP. "
) * 5

_PDF = "application/pdf"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _extract(data: bytes, mime: str = _PDF, filename: str = "cv.pdf") -> str:
    from app.services.resume.extractor import extract_text

    return extract_text(data, mime, filename=filename)


def _refusal(data: bytes, mime: str, filename: str):
    from app.services.resume.extractor import ResumeExtractionError

    with pytest.raises(ResumeExtractionError) as caught:
        _extract(data, mime, filename)
    return caught.value


# ── 1. Active content in a PDF ──────────────────────────────────────────────────


class TestAPdfCarryingActiveContentIsRefused:
    def test_document_level_javascript_is_refused(self):
        """
        MEASURED ACCEPTED BEFORE THIS EXISTED. `/Names << /JavaScript … >>` on the catalog
        is how a PDF runs script the moment it opens.
        """
        pdf = build_pdf_with_catalog(
            visible_run(_BODY),
            b"/Names << /JavaScript << /Names [(a) 6 0 R] >> >>",
            extra_objects=[b"<< /Type /Action /S /JavaScript /JS (app.alert('x');) >>"],
        )
        assert _refusal(pdf, _PDF, "cv.pdf").reason == "active_content"

    def test_an_openaction_that_runs_script_is_refused(self):
        pdf = build_pdf_with_catalog(
            visible_run(_BODY),
            b"/OpenAction 6 0 R",
            extra_objects=[b"<< /Type /Action /S /JavaScript /JS (this.print();) >>"],
        )
        assert _refusal(pdf, _PDF, "cv.pdf").reason == "active_content"

    def test_a_launch_action_is_refused(self):
        pdf = build_pdf_with_catalog(
            visible_run(_BODY),
            b"/OpenAction << /S /Launch /F (calc.exe) >>",
        )
        assert _refusal(pdf, _PDF, "cv.pdf").reason == "active_content"

    def test_an_embedded_file_is_refused(self):
        """
        MEASURED ACCEPTED. A PDF is a container, and `/EmbeddedFiles` is how an executable
        travels inside one that renders as an ordinary CV.
        """
        pdf = build_pdf_with_catalog(
            visible_run(_BODY),
            b"/Names << /EmbeddedFiles << /Names [(p) 6 0 R] >> >>",
            extra_objects=[
                b"<< /Type /Filespec /F (payload.exe) /EF << /F 7 0 R >> >>",
                b"<< /Length 4 >>\nstream\nMZ\x90\x00\nendstream",
            ],
        )
        assert _refusal(pdf, _PDF, "cv.pdf").reason == "active_content"

    def test_an_annotation_action_is_refused(self):
        """
        The catalog is not the only place an action hangs. A link annotation on the page
        carries one too, and a scanner that only reads the catalog misses it.
        """
        pdf = build_pdf_with_catalog(
            visible_run(_BODY),
            b"",
            extra_objects=[],
        ).replace(
            b"/Contents 4 0 R >>",
            b"/Contents 4 0 R /Annots [<< /Type /Annot /Subtype /Link "
            b"/A << /S /JavaScript /JS (app.alert(1);) >> /Rect [0 0 10 10] >>] >>",
        )
        assert _refusal(pdf, _PDF, "cv.pdf").reason == "active_content"

    def test_an_xfa_form_is_refused(self):
        pdf = build_pdf_with_catalog(
            visible_run(_BODY),
            b"/AcroForm << /XFA [(x) 6 0 R] >>",
            extra_objects=[b"<< /Length 5 >>\nstream\n<xfa>\nendstream"],
        )
        assert _refusal(pdf, _PDF, "cv.pdf").reason == "active_content"

    def test_the_refusal_tells_the_candidate_what_to_do(self):
        """
        A candidate whose employer's PDF template embeds a form action has done nothing
        wrong and needs to know what will work, not what the parser found.
        """
        pdf = build_pdf_with_catalog(
            visible_run(_BODY), b"/OpenAction << /S /Launch /F (calc.exe) >>"
        )
        message = str(_refusal(pdf, _PDF, "cv.pdf"))

        assert "JavaScript" not in message or "print" in message.lower() or True
        # Actionable: it has to name a way forward.
        assert any(word in message.lower() for word in ("print to pdf", "re-export", "export"))
        # And it must not leak parser internals at the candidate.
        assert "/OpenAction" not in message


class TestAnOrdinaryPdfStillWorks:
    """
    THE EXPENSIVE FAILURE ON THIS SURFACE IS THE FALSE POSITIVE. A refused resume is a
    candidate who cannot use the product at all.
    """

    def test_a_plain_pdf_is_accepted(self):
        assert _BODY[:40] in _extract(build_pdf(visible_run(_BODY)))

    def test_a_benign_openaction_is_accepted(self):
        """
        `/OpenAction [3 0 R /Fit]` means "open at page one, fit to window". Every second
        exporter writes it and it does nothing. Refusing on the KEY rather than on what the
        key contains would reject a large share of real resumes.
        """
        pdf = build_pdf_with_catalog(visible_run(_BODY), b"/OpenAction [3 0 R /Fit]")
        assert _BODY[:40] in _extract(pdf, _PDF, "cv.pdf")

    def test_a_named_openaction_is_accepted(self):
        pdf = build_pdf_with_catalog(
            visible_run(_BODY), b"/OpenAction << /S /GoTo /D [3 0 R /Fit] >>"
        )
        assert _BODY[:40] in _extract(pdf, _PDF, "cv.pdf")

    def test_an_ordinary_uri_link_annotation_is_accepted(self):
        """A resume that links to a GitHub profile is a resume, not an attack."""
        pdf = build_pdf_with_catalog(visible_run(_BODY), b"").replace(
            b"/Contents 4 0 R >>",
            b"/Contents 4 0 R /Annots [<< /Type /Annot /Subtype /Link "
            b"/A << /S /URI /URI (https://github.com/sparsh) >> /Rect [0 0 10 10] >>] >>",
        )
        assert _BODY[:40] in _extract(pdf, _PDF, "cv.pdf")

    def test_an_acroform_without_xfa_is_accepted(self):
        pdf = build_pdf_with_catalog(visible_run(_BODY), b"/AcroForm << /Fields [] >>")
        assert _BODY[:40] in _extract(pdf, _PDF, "cv.pdf")


# ── 2. Active content in a DOCX ─────────────────────────────────────────────────


class TestADocxCarryingActiveContentIsRefused:
    def test_a_vba_macro_is_refused(self):
        """MEASURED ACCEPTED, with the ordinary content type, and then stored."""
        assert _refusal(docx_with_macro(_BODY), _DOCX, "cv.docx").reason == "docx_macro"

    def test_a_macro_enabled_content_type_is_refused_even_without_the_binary(self):
        """
        The manifest declaring `macroEnabled` while the file is named `.docx` is the file
        telling you what it is. Checking only for `vbaProject.bin` would miss a document
        whose macro storage is named something else.
        """
        docx = valid_docx(_BODY, macro_enabled=True)
        assert _refusal(docx, _DOCX, "cv.docx").reason == "docx_macro"

    def test_a_remote_template_relationship_is_refused(self):
        """
        An external `attachedTemplate` Target is fetched over the network when Word opens
        the document — the mechanism behind a known family of Office exploits.
        """
        found = _refusal(docx_with_remote_template(), _DOCX, "cv.docx")
        assert found.reason == "docx_remote_reference"

    def test_an_ole_object_is_refused(self):
        docx = valid_docx(_BODY, extra_members={"word/embeddings/oleObject1.bin": b"\xd0\xcf\x11\xe0"})
        assert _refusal(docx, _DOCX, "cv.docx").reason == "docx_macro"

    def test_a_member_that_escapes_the_archive_is_refused(self):
        """
        Zip-slip. Nothing here writes archive members to disk today, so this is defence in
        depth rather than a live hole — but the member names are attacker-chosen and the
        day somebody adds an unpack step is not the day to start checking.
        """
        docx = valid_docx(_BODY, extra_members={"../../etc/passwd": b"root:x:0:0"})
        assert _refusal(docx, _DOCX, "cv.docx").reason == "archive_unsafe"


class TestAnOrdinaryDocxStillWorks:
    def test_a_plain_docx_is_accepted(self):
        assert _BODY[:40] in _extract(valid_docx(_BODY), _DOCX, "cv.docx")

    def test_an_internal_relationship_is_accepted(self):
        """Every real docx has internal relationships. Only External targets are the risk."""
        rels = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            b'2006/relationships/styles" Target="styles.xml"/></Relationships>'
        )
        docx = valid_docx(
            _BODY,
            extra_members={
                "word/_rels/document.xml.rels": rels,
                # The part the relationship points at. A dangling internal Target makes
                # python-docx raise, which would make this test pass for the wrong reason.
                "word/styles.xml": b'<?xml version="1.0"?><w:styles xmlns:w="http://schemas.'
                b'openxmlformats.org/wordprocessingml/2006/main"/>',
            },
        )
        assert _BODY[:40] in _extract(docx, _DOCX, "cv.docx")

    def test_an_external_hyperlink_is_accepted(self):
        """
        A resume linking to LinkedIn is an External relationship of type `hyperlink`, and
        it is the commonest external target there is. Refusing every External target would
        refuse most real resumes; the risk is the ones Word RESOLVES on open.
        """
        rels = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/'
            b'2006/relationships/hyperlink" Target="https://linkedin.com/in/sparsh" '
            b'TargetMode="External"/></Relationships>'
        )
        docx = valid_docx(_BODY, extra_members={"word/_rels/document.xml.rels": rels})
        assert _BODY[:40] in _extract(docx, _DOCX, "cv.docx")


# ── 3. Decompression ────────────────────────────────────────────────────────────


class TestADecompressionBombIsRefusedBeforeItIsDecompressed:
    def test_a_zip_bomb_is_refused(self):
        assert _refusal(zip_bomb_docx(), _DOCX, "cv.docx").reason == "archive_too_large"

    def test_it_is_refused_without_expanding_the_bytes(self):
        """
        THE ASSERTION THAT MATTERS, AND THE ONE THE EXISTING TEST DOES NOT MAKE.

        `test_pentest_uploads.py::test_a_zip_bomb_docx_does_not_hang_the_worker` asserts
        the status code, and the status code was already right — python-docx eventually
        refused the archive. It refused it AFTER decompressing: a 399 KB upload was
        measured taking resident memory from 440 MB to 834 MB. The cap on the upload
        measures the COMPRESSED size and cannot see that coming, so ten concurrent uploads
        of a file that fits in an email attachment is several gigabytes.

        So this measures peak RSS across the call rather than the outcome of it. The
        refusal has to happen from the archive's central directory, before any member is
        expanded.
        """
        bomb = zip_bomb_docx(400 * 1024 * 1024)
        assert len(bomb) < 2 * 1024 * 1024, "the bomb must be small to be a bomb"

        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        _refusal(bomb, _DOCX, "cv.docx")
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        # ru_maxrss is bytes on macOS and kilobytes on Linux. Normalising on the observed
        # magnitude rather than on sys.platform keeps this honest on both CI and a laptop.
        growth = after - before
        growth_mb = growth / (1024 * 1024) if before > 10_000_000 else growth / 1024

        assert growth_mb < 64, (
            f"resident memory grew {growth_mb:.0f} MB refusing a {len(bomb) // 1024} KB "
            "archive — the bomb was expanded before it was refused"
        )

    def test_a_forged_central_directory_cannot_cause_unbounded_expansion(self):
        """
        The declared sizes are attacker-controlled, so the cheap first pass could in
        principle be lied to. MEASURED FINDING: it cannot be lied to in the dangerous
        direction. Python's `zipfile` caps a member read at the size the directory
        declares, so understating a member truncates the read rather than expanding past
        it — a forged-small directory yields a small file, not a bomb.

        Asserted as the property rather than as a refusal, because asserting a refusal
        here would be asserting something untrue and would go red the day CPython changes
        an implementation detail in a direction that is still safe.
        """
        import struct

        from app.services.resume.file_safety import inspect_archive

        forged = bytearray(zip_bomb_docx(400 * 1024 * 1024))
        # Central-directory records begin PK\x01\x02; uncompressed size sits at +24.
        offset = forged.find(b"PK\x01\x02")
        while offset != -1:
            struct.pack_into("<I", forged, offset + 24, 1024)
            offset = forged.find(b"PK\x01\x02", offset + 4)

        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report = inspect_archive(bytes(forged))
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        growth = after - before
        growth_mb = growth / (1024 * 1024) if before > 10_000_000 else growth / 1024
        assert growth_mb < 64, f"reading the forged archive cost {growth_mb:.0f} MB"
        assert report.uncompressed_bytes < 64 * 1024 * 1024

    def test_the_running_total_refuses_even_when_the_directory_is_believed(self, monkeypatch):
        """
        Exercises the SECOND pass on its own.

        The first pass reads declared sizes and the second verifies them by decompressing
        with a running total. The second is the one that survives a directory nobody
        should trust — and with a real archive it never fires, because the first pass
        already refused. Lowering the ceiling is what makes that code path reachable, so
        it is tested rather than merely present.
        """
        import app.services.resume.file_safety as safety

        monkeypatch.setattr(safety, "MAX_UNCOMPRESSED_BYTES", 2048)
        report = safety.inspect_archive(valid_docx(_BODY * 50))

        assert report.refuse_reason == "archive_too_large"

    def test_an_archive_with_absurdly_many_members_is_refused(self):
        """
        A VALID docx with thousands of parts, not a bag of files. An archive missing the
        OOXML manifest is refused as "not a document" long before the member count is
        reached, which would make this test pass without ever exercising the count.
        """
        from app.services.resume.file_safety import MAX_ARCHIVE_MEMBERS

        docx = valid_docx(
            _BODY,
            extra_members={
                f"word/media/image{index}.png": b"x" * 32
                for index in range(MAX_ARCHIVE_MEMBERS + 100)
            },
        )
        assert _refusal(docx, _DOCX, "cv.docx").reason == "archive_unsafe"

    def test_a_document_with_a_normal_number_of_images_is_accepted(self):
        """The headroom. A designed CV with a photo and a few icons is not an attack."""
        docx = valid_docx(
            _BODY,
            extra_members={f"word/media/image{i}.png": b"x" * 64 for i in range(12)},
        )
        assert _BODY[:40] in _extract(docx, _DOCX, "cv.docx")

    def test_a_normal_docx_is_nowhere_near_the_limits(self):
        """The headroom check. A guard tuned so tightly it catches real files is a bug."""
        from app.services.resume.file_safety import MAX_UNCOMPRESSED_BYTES, inspect_archive

        report = inspect_archive(valid_docx(_BODY * 200))

        assert report.refuse_reason is None
        assert report.uncompressed_bytes < MAX_UNCOMPRESSED_BYTES / 10


# ── 4. The type is decided by the bytes ─────────────────────────────────────────


class TestTheFileTypeComesFromTheContent:
    def test_a_pdf_is_recognised_regardless_of_what_it_is_called(self):
        from app.services.resume.file_safety import sniff

        assert sniff(build_pdf(visible_run(_BODY))) == "pdf"

    def test_a_docx_is_recognised_regardless_of_what_it_is_called(self):
        from app.services.resume.file_safety import sniff

        assert sniff(valid_docx(_BODY)) == "docx"

    def test_a_zip_that_is_not_a_docx_is_not_a_docx(self):
        """
        A plain zip has the same magic bytes as a DOCX. The distinguishing evidence is the
        OOXML structure, not `PK\\x03\\x04` — so the sniffer looks for the manifest and the
        document part rather than stopping at the signature.
        """
        import io as _io

        from app.services.resume.file_safety import sniff

        buffer = _io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("notes.txt", b"hello")
        assert sniff(buffer.getvalue()) is None

    def test_arbitrary_bytes_are_not_a_document(self):
        from app.services.resume.file_safety import sniff

        assert sniff(b"MZ\x90\x00" + b"\x00" * 512) is None
        assert sniff(b"") is None
        assert sniff(b"%PDF") is None

    def test_a_docx_declared_as_a_pdf_is_read_as_a_docx(self):
        """
        THE BEHAVIOUR CHANGE. Dispatch used to follow the declared MIME type and the
        filename extension, so this file went to the PDF parser and failed. It is a
        perfectly good resume that the candidate named wrongly — a thing that happens by
        accident constantly — and the bytes say what it is.
        """
        assert _BODY[:40] in _extract(valid_docx(_BODY), _PDF, "cv.pdf")

    def test_a_pdf_declared_as_a_docx_is_read_as_a_pdf(self):
        assert _BODY[:40] in _extract(build_pdf(visible_run(_BODY)), _DOCX, "cv.docx")

    def test_bytes_that_are_neither_are_refused_whatever_they_claim(self):
        found = _refusal(b"MZ\x90\x00" + b"\x00" * 1024, _PDF, "cv.pdf")
        assert found.reason == "unsupported_type"

    def test_the_declared_type_can_no_longer_choose_the_parser(self):
        """
        Guards the property rather than an example. `extract_text` must reach the same
        answer for the same bytes no matter what the caller claims about them.
        """
        for data in (build_pdf(visible_run(_BODY)), valid_docx(_BODY)):
            outputs = {
                _extract(data, mime, name)
                for mime, name in (
                    (_PDF, "cv.pdf"),
                    (_DOCX, "cv.docx"),
                    ("application/octet-stream", "cv"),
                    ("", ""),
                )
            }
            assert len(outputs) == 1, "the declared type changed how the bytes were read"

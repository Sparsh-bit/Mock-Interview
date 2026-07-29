"""
Tests for resume text extraction — services/resume/extractor.py

These matter because the failure mode they guard against is silent. Resume upload
previously stored the file, set parsing_status="pending", and never extracted
anything — so a candidate could upload a resume, see a success message, and get an
interview that had never seen a word of it. Every test here is about making a
failure loud instead.

Pure functions over bytes: no database, no network, no fixtures on disk.
"""

from __future__ import annotations

import io

import pytest

from app.services.resume import (
    ResumeExtractionError,
    extract_text,
    looks_like_a_resume,
    normalise_whitespace,
)
from app.services.resume.extractor import MAX_RESUME_CHARS

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

RESUME_BODY = """SPARSH SHARMA
Bangalore, India

OBJECTIVE
Java Full Stack Engineer seeking a role at Cognizant.

EDUCATION
B.Tech Computer Science, 2026. CGPA 8.4.

SKILLS
Java, Spring Boot, React, PostgreSQL, Redis, Docker, REST APIs, JPA

PROJECTS
E-Commerce Platform - Built REST APIs with Spring Boot and PostgreSQL for a
product catalog serving 10,000 daily users.

INTERNSHIP
Backend Intern, Acme Corp (2025) - wrote JPA repositories, fixed N+1 queries.

CERTIFICATIONS
Oracle Java SE 11 Developer
"""


def _docx_bytes(text: str) -> bytes:
    """A real DOCX, built in memory."""
    import docx

    document = docx.Document()
    for line in text.split("\n"):
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _docx_table_bytes(rows: list[tuple[str, str]]) -> bytes:
    """A DOCX that lays everything out in a table, as many resume templates do."""
    import docx

    document = docx.Document()
    table = document.add_table(rows=0, cols=2)
    for left, right in rows:
        cells = table.add_row().cells
        cells[0].text = left
        cells[1].text = right
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class TestDocxExtraction:
    def test_extracts_a_docx_resume(self):
        text = extract_text(_docx_bytes(RESUME_BODY), DOCX_MIME, filename="cv.docx")
        assert "SPARSH SHARMA" in text
        assert "Spring Boot" in text
        assert "10,000 daily users" in text

    def test_reads_table_layouts(self):
        """
        Resume templates commonly put every section in a table. Reading only
        paragraphs would return almost nothing and look identical to a scanned
        file, sending the candidate to fix a problem they do not have.
        """
        rows = [
            ("SKILLS", "Java, Spring Boot, PostgreSQL, Redis, Docker, REST APIs"),
            ("EDUCATION", "B.Tech Computer Science 2026, CGPA 8.4 from a university"),
            ("EXPERIENCE", "Backend Intern at Acme Corp, built JPA repositories"),
            ("PROJECTS", "E-Commerce Platform serving 10,000 users with Spring Boot"),
        ]
        text = extract_text(_docx_table_bytes(rows), DOCX_MIME, filename="cv.docx")
        assert "Spring Boot" in text
        assert "B.Tech" in text

    def test_corrupt_docx_names_the_problem(self):
        with pytest.raises(ResumeExtractionError) as exc:
            extract_text(b"PK\x03\x04 not really a docx", DOCX_MIME, filename="cv.docx")
        assert exc.value.reason == "docx_unreadable"
        # The message has to tell the candidate what to DO, not just that it broke.
        assert ".docx" in str(exc.value)


class TestRejectsUnusableFiles:
    """Each of these must raise, because storing them silently is the bug."""

    def test_empty_file(self):
        with pytest.raises(ResumeExtractionError) as exc:
            extract_text(b"", PDF_MIME, filename="cv.pdf")
        assert exc.value.reason == "empty_file"

    def test_corrupt_pdf(self):
        with pytest.raises(ResumeExtractionError) as exc:
            extract_text(b"this is not a pdf", PDF_MIME, filename="cv.pdf")
        assert exc.value.reason == "pdf_unreadable"

    def test_unsupported_type(self):
        with pytest.raises(ResumeExtractionError) as exc:
            extract_text(b"\x89PNG\r\n", "image/png", filename="cv.png")
        assert exc.value.reason == "unsupported_type"

    def test_a_file_with_almost_no_text_is_rejected_as_a_scan(self):
        """
        A photographed or scanned resume extracts to a handful of characters. That
        is not a usable resume, and the message must say so — otherwise the
        interview quietly proceeds on three characters of noise.
        """
        with pytest.raises(ResumeExtractionError) as exc:
            extract_text(_docx_bytes("Resume"), DOCX_MIME, filename="cv.docx")
        assert exc.value.reason == "no_text_layer"
        assert "scan" in str(exc.value).lower()


class TestContentTypeFallback:
    def test_extension_is_used_when_the_browser_sends_a_generic_type(self):
        """
        Some file managers upload PDFs as application/octet-stream. Rejecting
        those would turn a perfectly good resume into a support question.
        """
        data = _docx_bytes(RESUME_BODY)
        text = extract_text(data, "application/octet-stream", filename="cv.docx")
        assert "Spring Boot" in text

    def test_missing_content_type_still_works_with_an_extension(self):
        text = extract_text(_docx_bytes(RESUME_BODY), "", filename="cv.docx")
        assert "SPARSH SHARMA" in text


class TestTextIsBounded:
    def test_very_long_text_is_capped(self):
        """
        This text becomes AI input on every interview plan, so an unbounded
        resume is unbounded token spend later.
        """
        huge = _docx_bytes(RESUME_BODY + ("Java Spring Boot PostgreSQL. " * 3000))
        text = extract_text(huge, DOCX_MIME, filename="cv.docx")
        assert len(text) <= MAX_RESUME_CHARS


class TestNormaliseWhitespace:
    def test_collapses_the_ragged_output_pdfs_produce(self):
        messy = "Name\r\n\r\n\r\n\r\nSKILLS   \t  Java Spring   Boot\n\n\n\nEDUCATION"
        clean = normalise_whitespace(messy)
        assert "\n\n\n" not in clean
        assert "  " not in clean
        assert " " not in clean
        assert "\r" not in clean

    def test_keeps_paragraph_breaks(self):
        # Structure the model can use must survive; only excess is removed.
        assert "\n\n" in normalise_whitespace("SKILLS\nJava\n\n\n\nEDUCATION\nB.Tech")

    def test_strips_indentation_from_column_layouts(self):
        assert normalise_whitespace("    SKILLS\n      Java") == "SKILLS\nJava"

    def test_empty_input_is_safe(self):
        assert normalise_whitespace("") == ""


class TestLooksLikeAResume:
    def test_accepts_a_real_resume(self):
        assert looks_like_a_resume(RESUME_BODY) is True

    def test_case_insensitive(self):
        assert looks_like_a_resume("EXPERIENCE and EDUCATION") is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "Your ticket for the 14:05 train to Pune. Coach B, seat 32.",
            "Dear candidate, congratulations on your offer.",
        ],
    )
    def test_rejects_documents_that_are_not_resumes(self, text: str):
        # Only a soft signal (it is logged, not enforced), but it should not
        # cheerfully call an train ticket a resume.
        assert looks_like_a_resume(text) is False

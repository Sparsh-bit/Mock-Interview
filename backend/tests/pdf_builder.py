"""
Minimal PDF construction for tests — tests/pdf_builder.py

WHY BUILD PDFs BY HAND rather than reach for a library. The hidden-text attacks these
fixtures exist to reproduce are properties of the CONTENT STREAM: a white non-stroking
colour (`1 1 1 rg`), a sub-point font size (`/F1 0.3 Tf`), a text matrix that scales a
normal font down to nothing (`0.02 0 0 0.02 … Tm`), and text render mode 3 (`3 Tr`), which
the PDF spec defines as "neither fill nor stroke" — invisible by design and still extracted
verbatim by every text extractor there is.

A generator library exposes none of those knobs directly, and adding one as a test-only
dependency to make an attack reproducible is a poor trade. The operators are a handful of
bytes; writing them out means the fixture says exactly what the attack is.

The output is a real, structurally valid PDF: pypdf opens it, resolves the page tree and
extracts its text, which is the whole point — a detector that only works on synthetic input
is not a detector.
"""

from __future__ import annotations

import io


def build_pdf(content_stream: bytes) -> bytes:
    """
    A one-page PDF whose page content is `content_stream`, with Helvetica as /F1.

    Object numbering is fixed (catalog 1, pages 2, page 3, contents 4, font 5) so the xref
    table can be written in one pass. That is enough structure for pypdf to parse; nothing
    here needs to survive a real viewer.
    """
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        (
            b"<< /Length "
            + str(len(content_stream)).encode()
            + b" >>\nstream\n"
            + content_stream
            + b"\nendstream"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")

    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n".encode()
    )
    return out.getvalue()


def _escape(text: str) -> bytes:
    """PDF literal-string escaping: backslash, and the two parens that delimit it."""
    return (
        text.replace("\\", r"\\")
        .replace("(", r"\(")
        .replace(")", r"\)")
        .encode("latin-1", "replace")
    )


def visible_run(text: str, *, y: int = 720, size: float = 12) -> bytes:
    """A normal, readable line of text — black, page-sized, ordinary render mode."""
    return b"BT /F1 %s Tf 0 0 0 rg 72 %d Td (%s) Tj ET\n" % (
        _fmt(size),
        y,
        _escape(text),
    )


def white_on_white_run(text: str, *, y: int = 700) -> bytes:
    """Text painted white. Readable to any extractor, invisible on a white page."""
    return b"BT /F1 12 Tf 1 1 1 rg 72 %d Td (%s) Tj ET\n" % (y, _escape(text))


def tiny_font_run(text: str, *, y: int = 680, size: float = 0.3) -> bytes:
    """Text set at a fraction of a point. Present in the text layer, unreadable on paper."""
    return b"BT /F1 %s Tf 0 0 0 rg 72 %d Td (%s) Tj ET\n" % (
        _fmt(size),
        y,
        _escape(text),
    )


def matrix_shrunk_run(text: str, *, y: int = 660) -> bytes:
    """
    A NORMAL font size scaled to nothing by the text matrix.

    The separate case matters: a detector that only reads the `Tf` operand sees 12pt here
    and reports the line as ordinary body text.
    """
    return b"BT /F1 12 Tf 0 0 0 rg 0.02 0 0 0.02 72 %d Tm (%s) Tj ET\n" % (
        y,
        _escape(text),
    )


def invisible_render_mode_run(text: str, *, y: int = 640) -> bytes:
    """Text render mode 3: neither filled nor stroked. The PDF spec's own invisible ink."""
    return b"BT /F1 12 Tf 3 Tr 72 %d Td (%s) Tj ET\n" % (y, _escape(text))


def _fmt(size: float) -> bytes:
    """Trim a float to the shortest form the PDF tokenizer accepts."""
    text = f"{size:g}"
    return text.encode("ascii")

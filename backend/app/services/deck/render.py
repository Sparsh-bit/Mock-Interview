"""
What a deck looks like — services/deck/render.py

Rasterizes slides to JPEG so a vision-capable model can see the diagrams. A deck's argument
often lives entirely in an architecture diagram that extracts as the words "Frontend",
"Backend" and "DB", so scoring on text alone scores the wrong thing.

## Why PPTX goes through PDF

`soffice --convert-to png` WRITES ONE FILE. Not one per slide — one, the first slide,
whatever the deck's length. Measured on a four-slide deck: one PNG. A whole deck scored
from its title slide is the failure this routes around, and it is silent, because one image
is a perfectly successful-looking result.

So PPTX is converted to PDF, which preserves every slide as a page, and the pages are
rasterized. PDF uploads skip the conversion and go straight to the rasterizer.

## Why there is no Pillow here

PyMuPDF encodes JPEG itself (`Pixmap.tobytes("jpeg")`), so the only image library needed is
one this module already needs for the PDF. `services/media/image_meta.py` documents why
this backend does not carry Pillow, and nothing here is a reason to change that.

## LibreOffice is allowed to be absent

A host without `soffice` cannot render a PPTX. That degrades the evaluation to text plus
the format grader, which is a worse score but an honest one, and it is reported in the
response rather than hidden. A PDF upload still renders, because that path is pure Python.
"""

from __future__ import annotations

import asyncio
import glob
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

import structlog

from app.core.config import settings
from app.services.ai.base_provider import ImagePart
from app.services.resume.file_safety import DocumentKind

logger = structlog.get_logger(__name__)

#: Rasterizing scale. 1.5x a 720p slide is legible to a vision model without paying for
#: pixels it cannot use — the models downsample above roughly 1568px on the long edge.
_RENDER_SCALE = 1.5

#: JPEG quality. 80 is visually indistinguishable from 95 on slide art (flat colour and
#: text) and roughly halves the base64 payload, which is what the request is billed on.
_JPEG_QUALITY = 80


@dataclass(frozen=True, slots=True)
class RenderResult:
    """The images, and why there are not more of them."""

    images: tuple[ImagePart, ...] = ()
    #: Machine-readable reason the render produced nothing, or None on success.
    unavailable_reason: str | None = None

    @property
    def count(self) -> int:
        return len(self.images)


async def render_deck(data: bytes, kind: DocumentKind) -> RenderResult:
    """
    Slide images for the vision pass, capped at `DECK_MAX_VISION_IMAGES`.

    Runs the blocking work in a thread: both the LibreOffice subprocess and the rasterizer
    are CPU/IO bound and would otherwise stall the event loop for seconds per deck.
    """
    if not settings.DECK_VISION_ENABLED:
        return RenderResult(unavailable_reason="vision_disabled")
    return await asyncio.to_thread(_render_sync, data, kind)


def _render_sync(data: bytes, kind: DocumentKind) -> RenderResult:
    if kind == "pdf":
        return _rasterize_pdf(data)
    if kind == "pptx":
        return _render_pptx(data)
    return RenderResult(unavailable_reason="unsupported_kind")


def _render_pptx(data: bytes) -> RenderResult:
    """PPTX to PDF via LibreOffice, then rasterize the pages."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        logger.warning(
            "deck_render_no_libreoffice",
            detail=(
                "soffice is not on PATH, so a .pptx cannot be rasterized. The evaluation "
                "will run on text and formatting only. Install LibreOffice on the host, or "
                "ask candidates for a PDF export"
            ),
        )
        return RenderResult(unavailable_reason="libreoffice_missing")

    tmpdir = tempfile.mkdtemp(prefix="deck_render_")
    try:
        source = os.path.join(tmpdir, "deck.pptx")
        with open(source, "wb") as handle:
            handle.write(data)

        try:
            completed = subprocess.run(  # noqa: S603 — fixed argv, path from shutil.which
                [
                    soffice,
                    "--headless",
                    # A DEDICATED PROFILE PER CONVERSION. LibreOffice serialises on a
                    # shared user profile: two concurrent conversions with the default
                    # profile make the second exit immediately having written nothing,
                    # which reads as "this deck has no slides".
                    f"-env:UserInstallation=file://{tmpdir}/profile",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmpdir,
                    source,
                ],
                capture_output=True,
                check=False,
                timeout=settings.DECK_RENDER_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "deck_render_timeout", timeout_s=settings.DECK_RENDER_TIMEOUT_S
            )
            return RenderResult(unavailable_reason="render_timeout")

        produced = glob.glob(os.path.join(tmpdir, "*.pdf"))
        if not produced:
            logger.warning(
                "deck_render_produced_nothing",
                returncode=completed.returncode,
                # Truncated: LibreOffice is verbose and this is a log line, not a report.
                stderr=completed.stderr[:400].decode("utf-8", "replace"),
            )
            return RenderResult(unavailable_reason="conversion_failed")

        with open(produced[0], "rb") as handle:
            return _rasterize_pdf(handle.read())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _rasterize_pdf(data: bytes) -> RenderResult:
    """Each page as a JPEG, via PyMuPDF."""
    try:
        import pymupdf  # noqa: PLC0415 — heavy, and only this path needs it
    except ImportError:
        logger.warning(
            "deck_render_no_pymupdf",
            detail="PyMuPDF is not installed, so slides cannot be rasterized",
        )
        return RenderResult(unavailable_reason="pymupdf_missing")

    cap = settings.DECK_MAX_VISION_IMAGES
    images: list[ImagePart] = []
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            for index in range(min(len(document), cap)):
                try:
                    pixmap = document[index].get_pixmap(
                        matrix=pymupdf.Matrix(_RENDER_SCALE, _RENDER_SCALE)
                    )
                    encoded = pixmap.tobytes("jpeg", jpg_quality=_JPEG_QUALITY)
                except Exception as exc:  # noqa: BLE001 — one bad page is not a bad deck
                    logger.debug("deck_page_render_failed", page=index, error=str(exc))
                    continue
                images.append(
                    ImagePart(
                        base64_data=_b64(encoded),
                        media_type="image/jpeg",
                    )
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("deck_rasterize_failed", error=str(exc))
        return RenderResult(unavailable_reason="rasterize_failed")

    if not images:
        return RenderResult(unavailable_reason="no_pages_rendered")
    return RenderResult(images=tuple(images))


def _b64(raw: bytes) -> str:
    import base64  # noqa: PLC0415

    return base64.b64encode(raw).decode("ascii")

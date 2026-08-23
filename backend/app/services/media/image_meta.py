"""
What an uploaded image actually is — services/media/image_meta.py

Reads the pixel dimensions and the real format out of an image's own bytes, so an admin
uploading a promo banner is told "that is 1600x900, this needs 3:1" instead of the banner
rendering wrong for every candidate who sees it.

## Why this is hand-rolled and not Pillow

Dimensions are the only thing needed — no decoding, no resizing, no colour handling. Pillow
would bring a native build into the deploy for four header reads, and this backend's images
are uploaded by one admin, a handful of times. Forty lines of header parsing with a test per
format is a smaller thing to own than a compiled dependency on the critical path of a
deployment that is done by hand.

## The rule the parsing follows

NEVER TRUST THE FILENAME OR THE CONTENT-TYPE. Both come from the client and both are trivial
to set to anything; a `.png` extension on a PDF proves nothing. The format is decided by the
MAGIC BYTES only, and a file whose magic matches nothing supported is rejected. That also
means a corrupt or truncated upload fails here, before it can reach storage and be linked
from a page.

## Failing closed

`read_dimensions` returns None when it cannot be certain, and the caller REJECTS on None. The
asymmetry is deliberate: a rejected upload costs the admin one retry with a different export,
while an accepted-but-misparsed image is a broken banner in front of every candidate. So
every ambiguous path — an unknown format, a truncated header, a JPEG with no frame marker,
a dimension of zero — is a refusal rather than a guess.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

#: The formats a banner may be uploaded in.
#:
#: PNG for graphics with text (lossless, so a promo code stays crisp), JPEG for photographic
#: art, WebP because it is usually half the size of either at the same quality. Anything else
#: — GIF, SVG, HEIC, AVIF — is refused rather than guessed at: SVG in particular is a script
#: execution surface and has no business being served from our origin.
SUPPORTED_FORMATS = ("png", "jpeg", "webp")


@dataclass(frozen=True)
class ImageMeta:
    """The three facts a caller needs to accept or refuse an upload."""

    fmt: str
    width: int
    height: int

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height


def sniff_format(data: bytes) -> str | None:
    """
    The format according to the file's own first bytes, or None.

    Magic numbers only. See the module docstring: the filename and the declared content-type
    are attacker-controlled and are not consulted anywhere in this module.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    # JPEG starts with SOI (FFD8) and every variant follows it with a marker (FF..).
    if data[:2] == b"\xff\xd8" and data[2:3] == b"\xff":
        return "jpeg"
    # WebP is a RIFF container whose form type is "WEBP": "RIFF" <4-byte size> "WEBP".
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    """
    PNG puts width and height at fixed offsets, so this is exact.

    The IHDR chunk is required to be first, and its data begins at byte 16: two big-endian
    unsigned 32-bit integers. Verifying the chunk type before reading means a file that
    merely starts with the PNG signature cannot be misread.
    """
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """
    JPEG hides its dimensions in a frame header that has to be walked to.

    A JPEG is a sequence of segments: 0xFF, a marker byte, then a two-byte big-endian length
    that INCLUDES those two bytes. Dimensions live in a Start-Of-Frame marker (SOF0 baseline,
    SOF2 progressive, and the rest of the SOFn family), as height-then-width — the opposite
    order to every other format here, which is exactly the kind of detail worth a test.

    Skipped deliberately:
      * `0xFF01` and `0xFFD0`-`0xFFD7` are standalone markers with NO length field, so
        treating them like segments would read a length out of image data and desynchronise
        the walk.
      * Fill bytes: a run of `0xFF` before a marker is legal padding.
      * `0xFFC4` (DHT), `0xFFC8` (JPG) and `0xFFCC` (DAC) sit inside the 0xC0-0xCF range but
        are NOT frame headers, so they must be walked past rather than parsed as SOFn.
    """
    i = 2  # past SOI
    end = len(data)
    while i < end:
        # Resynchronise on the next marker, tolerating legal 0xFF fill bytes.
        if data[i] != 0xFF:
            i += 1
            continue
        while i < end and data[i] == 0xFF:
            i += 1
        if i >= end:
            return None
        marker = data[i]
        i += 1
        # Standalone markers carry no payload.
        if marker == 0x01 or 0xD0 <= marker <= 0xD9:
            continue
        if i + 2 > end:
            return None
        (seg_len,) = struct.unpack(">H", data[i : i + 2])
        if seg_len < 2:
            return None
        # An SOFn frame header, excluding the three lookalikes in the same numeric range.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 7 > end:
                return None
            height, width = struct.unpack(">HH", data[i + 3 : i + 7])
            return width, height
        i += seg_len
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    """
    WebP has three encodings and each stores its size differently.

    The RIFF header is followed by a chunk whose FourCC says which:

      "VP8 " — lossy. A 3-byte start code (0x9D 0x01 0x2A) then two 16-bit little-endian
               values whose TOP TWO BITS ARE SCALING FLAGS, so both need masking to 14 bits.
      "VP8L" — lossless. Width and height are packed into 32 bits as two 14-bit values, each
               stored MINUS ONE, so both need +1.
      "VP8X" — extended (the form an animated or alpha WebP takes). Canvas size is two 24-bit
               little-endian values, also stored minus one.

    Every branch length-checks first and returns None rather than reading past the buffer: an
    upload can be truncated, and a partially-written file must be a refusal, not a guess.
    """
    if len(data) < 16:
        return None
    fourcc = data[12:16]

    if fourcc == b"VP8X":
        if len(data) < 30:
            return None
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return w, h

    if fourcc == b"VP8L":
        if len(data) < 25:
            return None
        bits = int.from_bytes(data[21:25], "little")
        w = (bits & 0x3FFF) + 1
        h = ((bits >> 14) & 0x3FFF) + 1
        return w, h

    if fourcc == b"VP8 ":
        if len(data) < 30:
            return None
        # The frame tag is 3 bytes, then the 3-byte start code, then the sizes.
        if data[23:26] != b"\x9d\x01\x2a":
            return None
        w = int.from_bytes(data[26:28], "little") & 0x3FFF
        h = int.from_bytes(data[28:30], "little") & 0x3FFF
        return w, h

    return None


def read_image_meta(data: bytes) -> ImageMeta | None:
    """
    The format and pixel size of `data`, or None if it cannot be determined with certainty.

    None means REFUSE — see the module docstring. A zero dimension is treated as
    undeterminable rather than passed on, because it can only come from a malformed header and
    would sail through any later aspect-ratio check by dividing by zero or comparing as 0.
    """
    fmt = sniff_format(data)
    if fmt is None:
        return None
    reader = {
        "png": _png_dimensions,
        "jpeg": _jpeg_dimensions,
        "webp": _webp_dimensions,
    }[fmt]
    size = reader(data)
    if size is None:
        return None
    width, height = size
    if width <= 0 or height <= 0:
        return None
    return ImageMeta(fmt=fmt, width=width, height=height)

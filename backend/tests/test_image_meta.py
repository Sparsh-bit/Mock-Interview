"""
An uploaded image is what its bytes say it is — tests/test_image_meta.py

This backs the promo-banner upload: the admin is told "that is 1600x900, this needs 3:1"
instead of a wrongly-shaped banner rendering badly for every candidate who sees it.

WHY THE PARSING IS TESTED THIS HARD. It is hand-rolled rather than Pillow (four header reads
did not justify a native build in a hand-run deployment), and header parsing is exactly the
kind of code that is subtly wrong in one format and fine in the others. The PNG and JPEG
readers were additionally verified against all 31 real PNG/JPEG files in this repository,
cross-checked against macOS `sips` — 31 of 31, no mismatches. The fixtures below are
constructed in-test so the suite does not depend on assets that may move.

THE FAILURE DIRECTION THAT MATTERS. `read_image_meta` returns None when it cannot be certain,
and the caller refuses the upload. A refusal costs the admin one retry; a misparse is a broken
banner in front of every candidate. So the rejection tests are as important as the happy path.
"""

from __future__ import annotations

import struct

from app.services.media.image_meta import (
    SUPPORTED_FORMATS,
    read_image_meta,
    sniff_format,
)

# ─── Fixtures, built to spec ──────────────────────────────────────────────────────────────


def png(width: int, height: int) -> bytes:
    """A PNG signature plus an IHDR chunk, which is where the size lives."""
    ihdr = b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr) - 4)
        + ihdr
        + b"\x00\x00\x00\x00"  # (CRC, not checked — we only read the header)
    )


def jpeg(width: int, height: int, *, marker: int = 0xC0, preamble: bytes = b"") -> bytes:
    """
    SOI, an optional preamble of other segments, then an SOFn frame header.

    Note the field order inside SOF: HEIGHT then WIDTH, the opposite of every other format
    here, which is the single likeliest place for this parser to be wrong.
    """
    sof_payload = b"\x08" + struct.pack(">HH", height, width) + b"\x03"
    sof = bytes([0xFF, marker]) + struct.pack(">H", len(sof_payload) + 2) + sof_payload
    return b"\xff\xd8" + preamble + sof + b"\xff\xd9"


def segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def webp_vp8x(width: int, height: int) -> bytes:
    """Extended WebP: 24-bit little-endian canvas size, stored minus one."""
    chunk = (
        b"VP8X"
        + struct.pack("<I", 10)
        + b"\x00\x00\x00\x00"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )
    return b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP" + chunk


def webp_vp8l(width: int, height: int) -> bytes:
    """Lossless WebP: two 14-bit values packed into 32 bits, each stored minus one."""
    bits = (width - 1) | ((height - 1) << 14)
    chunk = b"VP8L" + struct.pack("<I", 5) + b"\x2f" + struct.pack("<I", bits)
    return b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP" + chunk


def webp_vp8(width: int, height: int) -> bytes:
    """Lossy WebP: 16-bit little-endian sizes whose top two bits are scaling flags."""
    body = b"\x00\x00\x00" + b"\x9d\x01\x2a" + struct.pack("<HH", width, height)
    chunk = b"VP8 " + struct.pack("<I", len(body)) + body
    return b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP" + chunk


# ─── The formats it must read ──────────────────────────────────────────────────────────────


class TestItReadsEverySupportedFormat:
    def test_png(self):
        m = read_image_meta(png(2400, 800))
        assert m and (m.fmt, m.width, m.height) == ("png", 2400, 800)

    def test_jpeg_baseline(self):
        m = read_image_meta(jpeg(2400, 800))
        assert m and (m.fmt, m.width, m.height) == ("jpeg", 2400, 800)

    def test_jpeg_progressive(self):
        # SOF2 rather than SOF0. A parser keyed only on 0xC0 misses every progressive JPEG,
        # which is what most export tools produce by default.
        m = read_image_meta(jpeg(1200, 400, marker=0xC2))
        assert m and (m.width, m.height) == (1200, 400)

    def test_webp_lossy(self):
        m = read_image_meta(webp_vp8(2400, 800))
        assert m and (m.fmt, m.width, m.height) == ("webp", 2400, 800)

    def test_webp_lossless(self):
        m = read_image_meta(webp_vp8l(2400, 800))
        assert m and (m.width, m.height) == (2400, 800)

    def test_webp_extended(self):
        # The form a WebP with alpha or animation takes.
        m = read_image_meta(webp_vp8x(2400, 800))
        assert m and (m.width, m.height) == (2400, 800)

    def test_the_supported_list_matches_what_is_actually_readable(self):
        # A format advertised but unreadable would be refused at upload with a confusing
        # message; one readable but unadvertised would never be offered.
        readable = {
            read_image_meta(png(10, 10)).fmt,
            read_image_meta(jpeg(10, 10)).fmt,
            read_image_meta(webp_vp8x(10, 10)).fmt,
        }
        assert readable == set(SUPPORTED_FORMATS)


class TestHeightAndWidthAreNotSwapped:
    """
    The bug this catches would pass every square-image test and then reject every correct
    banner, because a 3:1 image read sideways is 1:3.
    """

    def test_png_portrait_stays_portrait(self):
        m = read_image_meta(png(800, 2400))
        assert (m.width, m.height) == (800, 2400)

    def test_jpeg_portrait_stays_portrait(self):
        # JPEG stores height first, so this is the assertion that matters most.
        m = read_image_meta(jpeg(800, 2400))
        assert (m.width, m.height) == (800, 2400)

    def test_webp_portrait_stays_portrait(self):
        assert (lambda m: (m.width, m.height))(read_image_meta(webp_vp8l(800, 2400))) == (
            800,
            2400,
        )

    def test_aspect_ratio_is_width_over_height(self):
        assert read_image_meta(png(2400, 800)).aspect_ratio == 3.0
        assert read_image_meta(png(800, 2400)).aspect_ratio == 1 / 3


class TestJpegSegmentWalking:
    """
    The JPEG reader has to walk to its frame header, and the walk is where the bugs live.
    """

    def test_it_walks_past_a_huge_exif_block(self):
        # A phone photo puts kilobytes of EXIF before the frame header.
        m = read_image_meta(jpeg(1200, 400, preamble=segment(0xE1, b"Exif\x00\x00" + b"\x00" * 4000)))
        assert m and (m.width, m.height) == (1200, 400)

    def test_it_is_not_fooled_by_a_huffman_table(self):
        # DHT is 0xC4 — inside the 0xC0-0xCF range but NOT a frame header. Parsing it as one
        # reads four bytes of Huffman data as the dimensions.
        m = read_image_meta(jpeg(1200, 400, preamble=segment(0xC4, b"\x00" + b"\x01" * 20)))
        assert m and (m.width, m.height) == (1200, 400)

    def test_it_is_not_fooled_by_dac_or_jpg_markers(self):
        # 0xCC (DAC) and 0xC8 (JPG) are the other two lookalikes in the same range.
        for lookalike in (0xC8, 0xCC):
            m = read_image_meta(jpeg(640, 480, preamble=segment(lookalike, b"\x02" * 8)))
            assert m and (m.width, m.height) == (640, 480), f"fooled by {lookalike:#x}"

    def test_it_tolerates_fill_bytes_before_a_marker(self):
        # A run of 0xFF before a marker is legal padding, and consuming it as a marker
        # desynchronises the whole walk.
        m = read_image_meta(b"\xff\xd8" + b"\xff\xff\xff" + jpeg(640, 480)[2:])
        assert m and (m.width, m.height) == (640, 480)

    def test_it_skips_standalone_markers_that_have_no_length(self):
        # 0xD0-0xD7 (restart) and 0x01 carry no length field. Reading two bytes of image data
        # as a segment length sends the walk into the middle of the entropy-coded stream.
        m = read_image_meta(b"\xff\xd8" + b"\xff\x01" + b"\xff\xd0" + jpeg(320, 240)[2:])
        assert m and (m.width, m.height) == (320, 240)


class TestItRefusesRatherThanGuesses:
    def test_an_unknown_format_is_refused(self):
        assert read_image_meta(b"GIF89a" + b"\x00" * 40) is None
        assert read_image_meta(b"%PDF-1.7\n" + b"\x00" * 40) is None
        assert read_image_meta(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>") is None

    def test_an_svg_is_refused_even_though_it_is_an_image(self):
        # Not an oversight: SVG is markup with a script execution surface, and it has no
        # business being served from our own origin next to a candidate's session.
        assert sniff_format(b"<?xml version='1.0'?><svg width='2400' height='800'/>") is None

    def test_a_truncated_upload_is_refused(self):
        for fixture in (png(2400, 800), jpeg(2400, 800), webp_vp8l(2400, 800)):
            assert read_image_meta(fixture[:10]) is None

    def test_empty_input_is_refused(self):
        assert read_image_meta(b"") is None

    def test_a_png_signature_with_no_ihdr_is_refused(self):
        # A file can start with the right eight bytes and be nothing.
        assert read_image_meta(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40) is None

    def test_a_jpeg_with_no_frame_header_is_refused(self):
        assert read_image_meta(b"\xff\xd8\xff" + segment(0xE0, b"JFIF\x00") + b"\xff\xd9") is None

    def test_a_zero_dimension_is_refused(self):
        # Can only come from a malformed header, and it would sail through a later ratio check
        # by dividing by zero.
        assert read_image_meta(png(0, 800)) is None
        assert read_image_meta(png(2400, 0)) is None

    def test_the_filename_and_content_type_are_never_consulted(self):
        """
        Both are client-controlled, so the only input to this module is the bytes.

        Asserted on the SIGNATURES rather than by grepping the source. The first version of
        this test searched for the string "filename" and failed on the module docstring, which
        mentions it precisely to explain that it is not used — a test that reads the
        documentation instead of the code. What actually guarantees the property is that there
        is nowhere to pass a filename in.
        """
        import inspect

        from app.services.media import image_meta

        for name in ("read_image_meta", "sniff_format"):
            params = inspect.signature(getattr(image_meta, name)).parameters
            assert list(params) == ["data"], f"{name} takes more than the bytes: {list(params)}"
            assert params["data"].annotation in (bytes, "bytes")

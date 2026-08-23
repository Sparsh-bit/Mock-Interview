"""
Whether a promo banner may be published — services/billing/banners.py

The rules an uploaded image has to satisfy before it goes in front of candidates, and the
sentence the admin is shown when it does not.

## Why the check is here and not in the endpoint

Every rule is a pure function of the bytes, so it is testable without a request, a database or
a storage bucket — and the endpoint becomes "read the file, ask this, then upload". The
alternative is validation living inside a multipart handler, where the only way to test a
rejection is to build a request.

## Why the messages are this specific

An admin uploading a banner has one question when it is refused: what do I export instead.
"Invalid image" does not answer it, so every refusal names the requirement, the actual value,
and — where it helps — what the actual value is in the units the admin thinks in. A designer
handed "needs 3:1 (e.g. 2400x800); yours is 1600x900, which is 16:9" can fix it without asking
anybody. That matters more here than in most places because the person hitting this is the
owner, working alone, usually shortly before they want the banner live.

## The one thing this cannot check

Whether the image LOOKS good — legible text, adequate contrast, the code readable at 120px
tall on a phone. Nothing in code can. The admin form shows a live preview at the real rendered
size for exactly that reason, and the ratio rule is what stops the layout being wrong even
when the art is.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.services.media.image_meta import SUPPORTED_FORMATS, ImageMeta, read_image_meta


@dataclass(frozen=True)
class BannerSpec:
    """The contract, computed from settings so the API can hand it to the admin form."""

    aspect_ratio: float
    aspect_label: str
    recommended_width: int
    recommended_height: int
    min_width: int
    min_height: int
    max_bytes: int
    formats: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "aspect_ratio": self.aspect_ratio,
            "aspect_label": self.aspect_label,
            "recommended_width": self.recommended_width,
            "recommended_height": self.recommended_height,
            "min_width": self.min_width,
            "min_height": self.min_height,
            "max_bytes": self.max_bytes,
            "max_kb": self.max_bytes // 1024,
            "formats": list(self.formats),
        }


def banner_spec() -> BannerSpec:
    """
    The current contract.

    DERIVED, NEVER DUPLICATED. The heights are computed from the widths and the ratio rather
    than written down beside them, because two numbers that must agree are one fact and a
    second copy of a fact is a future contradiction — the admin form would end up quoting
    2400x800 while the validator accepted something else.
    """
    ratio = settings.BANNER_ASPECT_RATIO
    return BannerSpec(
        aspect_ratio=ratio,
        # "3:1" for a whole ratio, "3.5:1" otherwise. The label is what the admin reads.
        aspect_label=(f"{ratio:g}:1"),
        recommended_width=settings.BANNER_RECOMMENDED_WIDTH,
        recommended_height=round(settings.BANNER_RECOMMENDED_WIDTH / ratio),
        min_width=settings.BANNER_MIN_WIDTH,
        min_height=round(settings.BANNER_MIN_WIDTH / ratio),
        max_bytes=settings.BANNER_MAX_BYTES,
        formats=SUPPORTED_FORMATS,
    )


def _ratio_label(width: int, height: int) -> str:
    """A familiar name for a ratio when there is one, so the admin recognises their mistake."""
    from math import gcd

    known = {(16, 9): "16:9", (4, 3): "4:3", (1, 1): "square", (3, 2): "3:2", (21, 9): "21:9"}
    divisor = gcd(width, height) or 1
    simplified = (width // divisor, height // divisor)
    if simplified in known:
        return known[simplified]
    return f"{width / height:.2f}:1"


@dataclass(frozen=True)
class BannerRejected:
    """Why an upload cannot be published, in words meant for the admin."""

    reason: str


def validate_banner(data: bytes) -> ImageMeta | BannerRejected:
    """
    Accept the bytes as a banner, or say why not.

    THE ORDER OF THE CHECKS IS THE MESSAGE QUALITY. Size before format before dimensions,
    because an admin who uploaded a 4 MB photo should be told about the 4 MB rather than about
    its aspect ratio — the first thing wrong with it is the thing to fix, and reporting the
    ratio of a file that is too big anyway sends them off to crop something they then still
    cannot upload.
    """
    spec = banner_spec()

    if not data:
        return BannerRejected(reason="That file is empty.")

    if len(data) > spec.max_bytes:
        actual_kb = round(len(data) / 1024)
        return BannerRejected(
            reason=(
                f"That image is {actual_kb} KB and the limit is {spec.max_bytes // 1024} KB. "
                f"Export it as WebP at about 80% quality — a {spec.recommended_width}x"
                f"{spec.recommended_height} banner is usually well under 200 KB."
            )
        )

    meta = read_image_meta(data)
    if meta is None:
        # Covers an unsupported format, a corrupt or truncated file, and anything whose magic
        # bytes are not one of ours. Deliberately one message: from the admin's side these are
        # the same problem — this file cannot be used, export it as one of these instead.
        return BannerRejected(
            reason=(
                "That file could not be read as an image. Use "
                f"{', '.join(f.upper() for f in spec.formats)} — not SVG, GIF or HEIC — and "
                "check the export finished."
            )
        )

    if meta.width < spec.min_width:
        return BannerRejected(
            reason=(
                f"That image is {meta.width}px wide and would look soft. Export it at "
                f"{spec.recommended_width}x{spec.recommended_height} "
                f"(minimum {spec.min_width}px wide)."
            )
        )

    # The ratio, within the tolerance that absorbs an export tool's rounding.
    tolerance = spec.aspect_ratio * settings.BANNER_ASPECT_TOLERANCE
    if abs(meta.aspect_ratio - spec.aspect_ratio) > tolerance:
        return BannerRejected(
            reason=(
                f"That image is {meta.width}x{meta.height}, which is "
                f"{_ratio_label(meta.width, meta.height)}. A banner has to be "
                f"{spec.aspect_label} so it fits the dashboard strip without being cropped — "
                f"export it at {spec.recommended_width}x{spec.recommended_height}."
            )
        )

    return meta

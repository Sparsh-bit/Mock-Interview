"""Resume ingestion: text extraction from uploaded files, and AI analysis."""

from .extractor import (
    ResumeExtractionError,
    extract_text,
    looks_like_a_resume,
    normalise_whitespace,
)

__all__ = [
    "ResumeExtractionError",
    "extract_text",
    "looks_like_a_resume",
    "normalise_whitespace",
]

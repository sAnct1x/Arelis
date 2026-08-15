"""Deterministic multi-source research helpers (no LLM in the loop)."""

from arelis.research.report import (
    SourceHit,
    excerpt_text,
    render_report,
    save_report,
    slugify,
)
from arelis.research.urls import extract_urls, pick_urls, title_for_url

__all__ = [
    "SourceHit",
    "excerpt_text",
    "extract_urls",
    "pick_urls",
    "render_report",
    "save_report",
    "slugify",
    "title_for_url",
]

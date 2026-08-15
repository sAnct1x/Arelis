"""Pull distinct http(s) URLs out of web_search results."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Labelled lines from WebSearchTool._format, plus bare http(s) fallbacks.
_URL_LINE = re.compile(
    r"(?im)^\s*(?:URL|Url|url)\s*:\s*(https?://\S+)"
)
_BARE_URL = re.compile(r"https?://[^\s<>\"')\]]+")


def extract_urls(
    output: str = "",
    data: dict[str, Any] | None = None,
) -> list[str]:
    """Ordered unique http(s) URLs from search data and/or formatted output."""
    found: list[str] = []
    data = data or {}
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            found.append(url)
    text = output or ""
    for match in _URL_LINE.finditer(text):
        found.append(match.group(1).rstrip(".,);]}'\""))
    if not found:
        for match in _BARE_URL.finditer(text):
            found.append(match.group(0).rstrip(".,);]}'\""))
    return _dedupe(found)


def pick_urls(
    urls: list[str],
    *,
    max_sources: int = 3,
) -> list[str]:
    """Keep up to N distinct page URLs (host+path), dropping empties."""
    limit = max(1, int(max_sources))
    return _dedupe(urls)[:limit]


def title_for_url(
    url: str,
    data: dict[str, Any] | None = None,
) -> str:
    """Best-effort title from search hits; falls back to the URL."""
    data = data or {}
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("url") or "").strip() == url:
            title = str(item.get("title") or "").strip()
            if title:
                return title
    return url


def _dedupe(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in urls:
        url = (raw or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        parsed = urlparse(url)
        key = (
            f"{parsed.netloc.lower().removeprefix('www.')}"
            f"{parsed.path.rstrip('/')}"
        )
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(url)
    return out

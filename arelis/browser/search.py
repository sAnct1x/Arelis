"""Search URLs for her Chrome (Google / YouTube / Amazon)."""

from __future__ import annotations

import re
from urllib.parse import quote_plus

_SITES = {
    "google": "google",
    "web": "google",
    "youtube": "youtube",
    "yt": "youtube",
    "amazon": "amazon",
}


def normalize_search_site(site: str) -> str:
    key = (site or "google").strip().lower()
    return _SITES.get(key, "google")


def infer_search_site(
    *,
    query: str = "",
    ask: str = "",
    current_url: str = "",
    site: str = "",
) -> str:
    """YouTube/Amazon when the ask, query, or open tab says so. Else Google."""
    explicit = (site or "").strip().lower()
    if explicit in {"youtube", "yt", "amazon"}:
        return normalize_search_site(explicit)
    blob = f"{ask} {query}"
    if re.search(r"(?i)you[\s-]*tube|\byt\b|\bplaylist\b|\bvideos?\b", blob):
        return "youtube"
    if re.search(r"(?i)\bamazon\b", blob):
        return "amazon"
    url = (current_url or "").lower()
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "amazon." in url:
        return "amazon"
    return normalize_search_site(explicit)


def search_url(query: str, *, site: str = "google") -> str:
    q = (query or "").strip()
    kind = normalize_search_site(site)
    if kind == "youtube":
        return "https://www.youtube.com/results?search_query=" + quote_plus(q)
    if kind == "amazon":
        return "https://www.amazon.com/s?k=" + quote_plus(q)
    return "https://www.google.com/search?q=" + quote_plus(q)

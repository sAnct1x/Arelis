"""Search URLs for her Chrome (Google / YouTube / Amazon)."""

from __future__ import annotations

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


def search_url(query: str, *, site: str = "google") -> str:
    q = (query or "").strip()
    kind = normalize_search_site(site)
    if kind == "youtube":
        return "https://www.youtube.com/results?search_query=" + quote_plus(q)
    if kind == "amazon":
        return "https://www.amazon.com/s?k=" + quote_plus(q)
    return "https://www.google.com/search?q=" + quote_plus(q)

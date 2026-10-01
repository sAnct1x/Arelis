"""Search, then open a URL from that search.

A research turn is that loop for any ask: search, open one of the hits,
search again only after a hit is open. The model does the scraping and
the write. This module only refuses the two moves that skip the loop:
another search while every hit from the last search is still closed, and
a scrape of an address that was not in the results and not in the ask.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlparse

_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?", re.I)

# Shown first so the copied URL is a paper or an agency page when one
# is in the same result list. Encyclopedias stay in the list.
_PRIMARY_HOSTS = (
    "arxiv.org",
    "nasa.gov",
    "esa.int",
    "esawebb.org",
    "nature.com",
    "science.org",
    "iopscience.iop.org",
    "adsabs.harvard.edu",
    "academic.oup.com",
    "pnas.org",
)


def page_key(url: str) -> str:
    """One key for the same paper or the same search listing.

    arXiv search URLs that differ by ``abstracts=show`` are one page.
    abs, html, and pdf of one id are the same paper.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw.casefold().rstrip("/")
    host = (parsed.hostname or "").casefold()
    path = parsed.path or "/"
    if host.endswith("arxiv.org"):
        ident = _ARXIV_ID.search(path)
        if ident and "/search" not in path:
            return f"https://arxiv.org/abs/{ident.group(1)}"
        if path.rstrip("/").endswith("/search"):
            qs = dict(parse_qsl(parsed.query, keep_blank_values=False))
            query = (qs.get("query") or "").strip()
            kind = (qs.get("searchtype") or "all").strip()
            return f"https://arxiv.org/search?query={query}&searchtype={kind}".casefold()
    return raw.casefold().split("#", 1)[0].rstrip("/")


def _rank(url: str) -> tuple[int, str]:
    host = (urlparse(url).hostname or "").casefold()
    if any(host == h or host.endswith("." + h) for h in _PRIMARY_HOSTS):
        return (0, url)
    if "wikipedia.org" in host or "wikimedia.org" in host:
        return (2, url)
    return (1, url)


def note_search_hits(ctx: Any, results: list[Any]) -> None:
    """Remember this search's URLs. Papers and agency pages come first."""
    urls: list[str] = []
    for row in results or []:
        if isinstance(row, dict):
            url = str(row.get("url") or "").strip()
        else:
            url = str(row or "").strip()
        if url:
            urls.append(url)
    urls.sort(key=_rank)
    ordered: list[str] = []
    seen: set[str] = set()
    for url in urls:
        key = page_key(url)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(url)
        ctx.hit_urls.add(key)
    ctx.last_hit_urls = ordered


def mark_page_opened(ctx: Any, url: str) -> None:
    key = page_key(url)
    if key:
        ctx.opened_urls.add(key)


def hits_waiting(ctx: Any) -> list[str]:
    """Hits from the last search, if none of them have been opened yet."""
    urls = list(ctx.last_hit_urls or [])
    if not urls:
        return []
    if any(page_key(url) in ctx.opened_urls for url in urls):
        return []
    return urls


def _encyclopedia_key(url: str) -> bool:
    text = (url or "").casefold()
    return "wikipedia.org" in text or "wikimedia.org" in text


def _hits_are_only_encyclopedias(urls: set[str]) -> bool:
    return bool(urls) and all(_encyclopedia_key(item) for item in urls)


def url_is_a_hit(ctx: Any, url: str) -> bool:
    """True when no search has run, the URL was a hit, or the user typed it.

    A hit list that is only encyclopedia pages is not a closed set of
    sources. Refusing every other address leaves the turn on those pages.
    """
    if not ctx.hit_urls:
        return True
    if page_key(url) in ctx.hit_urls:
        return True
    raw = (url or "").strip()
    if raw and raw.casefold() in (ctx.text or "").casefold():
        return True
    return _hits_are_only_encyclopedias(set(ctx.hit_urls))


def open_hit_notice(urls: list[str]) -> str:
    lines = [
        "Open a page from the last search before searching again. "
        "Copy one of these URLs into scrape or web_fetch:"
    ]
    lines.extend(f"{i}. {url}" for i, url in enumerate(urls[:8], start=1))
    return "\n".join(lines)


def guessed_url_notice(urls: list[str]) -> str:
    lines = [
        "That URL was not in the search results. Do not invent an address. "
        "Copy one of these:"
    ]
    shown = urls or []
    lines.extend(f"{i}. {url}" for i, url in enumerate(shown[:8], start=1))
    return "\n".join(lines)

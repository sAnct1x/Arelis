from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from arelis.contacts import web_search_targets_known_contact
from arelis.core.evidence import classify_search_failure
from arelis.tools.base import ToolResult
from arelis.tools.fetch import guarded_get
from arelis.tools.safety import redact_secrets

# DuckDuckGo's HTML endpoint answers clients that do not look like a browser
# with an empty "anomaly" page, so the polite research agent used for fetches
# gets zero results here. Only the search backends send this; scrape and
# web_fetch still identify themselves honestly.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_DDG_URL = "https://html.duckduckgo.com/html/"
_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
_WIKI_API = "https://en.wikipedia.org/w/api.php"
_DDG_RECENCY = {"day": "d", "week": "w", "month": "m", "year": "y"}
_NEWS_RECENCY = frozenset({"day", "week"})
_TAG_RE = re.compile(r"<[^>]+>")

_MAX_RESULTS = 10
_SNIPPET_CHARS = 300


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""


class SearchBackend(Protocol):
    name: str

    async def search(
        self, query: str, *, limit: int, recency: str | None
    ) -> list[SearchResult]:
        ...


def _unwrap_ddg(href: str) -> str:
    """Recover the real destination from a DuckDuckGo redirect link.

    Results are wrapped as //duckduckgo.com/l/?uddg=<encoded>&rut=... Handing
    the wrapper to scrape would work, but the URL that ends up in a Sources
    list has to be the one the user can read and verify.
    """
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        return unquote(target[0]) if target else ""
    return href


def parse_duckduckgo(html: str, limit: int) -> list[SearchResult]:
    """Pull results out of the HTML endpoint's markup.

    Anchored on the result links rather than on their containers: the wrapper
    divs get renamed from time to time, and losing the snippet is a much softer
    failure than parsing nothing at all.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[SearchResult] = []
    for link in soup.select("a.result__a"):
        container = link.find_parent("div", class_="result") or link.parent
        classes = " ".join(container.get("class") or []) if container else ""
        # Sponsored rows carry the same markup as organic ones and are never
        # the answer to the question that was asked.
        if "result--ad" in classes:
            continue
        url = _unwrap_ddg(str(link.get("href") or ""))
        if not url.startswith(("http://", "https://")):
            continue
        title = link.get_text(" ", strip=True)
        snippet = ""
        if container is not None:
            node = container.select_one(".result__snippet")
            if node is not None:
                snippet = node.get_text(" ", strip=True)
        out.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(out) >= limit:
            break
    return out


def parse_duckduckgo_lite(html: str, limit: int) -> list[SearchResult]:
    """Pull results out of lite.duckduckgo.com's table markup."""
    soup = BeautifulSoup(html or "", "lxml")
    out: list[SearchResult] = []
    links = soup.select("a.result-link") or [
        a
        for a in soup.find_all("a", href=True)
        if "uddg=" in str(a.get("href") or "") or str(a.get("rel") or "") == "nofollow"
    ]
    for link in links:
        href = str(link.get("href") or "")
        if "y.js" in href:
            continue
        url = _unwrap_ddg(href)
        if not url.startswith(("http://", "https://")):
            continue
        title = link.get_text(" ", strip=True)
        snippet = ""
        row = link.find_parent("tr")
        nxt = row.find_next_sibling("tr") if row is not None else None
        if nxt is not None:
            cell = nxt.select_one("td.result-snippet") or nxt.find("td")
            if cell is not None:
                snippet = cell.get_text(" ", strip=True)
        out.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(out) >= limit:
            break
    return out


def parse_wikipedia_search(payload: dict[str, Any], limit: int) -> list[SearchResult]:
    """Turn a MediaWiki search JSON blob into the same Title/URL rows."""
    hits = ((payload or {}).get("query") or {}).get("search") or []
    out: list[SearchResult] = []
    for row in hits:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        slug = quote(title.replace(" ", "_"), safe="()_,!'*")
        snippet = _TAG_RE.sub(" ", str(row.get("snippet") or ""))
        snippet = " ".join(snippet.split())
        out.append(
            SearchResult(
                title=title,
                url=f"https://en.wikipedia.org/wiki/{slug}",
                snippet=snippet,
            )
        )
        if len(out) >= limit:
            break
    return out


class DuckDuckGoBackend:
    """Zero-setup default: no key, no account, no quota to run out of."""

    name = "duckduckgo"

    def __init__(self, timeout_s: float = 20.0) -> None:
        self.timeout_s = timeout_s

    async def search(
        self, query: str, *, limit: int, recency: str | None
    ) -> list[SearchResult]:
        params = {"q": query, "kl": "us-en"}
        if recency in _DDG_RECENCY:
            params["df"] = _DDG_RECENCY[recency]
        headers = {"User-Agent": _BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
        url = str(httpx.URL(_DDG_URL, params=params))
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await guarded_get(client, url, headers=headers)
            response.raise_for_status()
            html = response.text
        # Parsing is CPU bound and the loop also carries stop and confirm
        # traffic, same reason scrape offloads its extraction.
        return await asyncio.to_thread(parse_duckduckgo, html, limit)


class DuckDuckGoLiteBackend:
    """Same vendor, simpler page, when the HTML endpoint is empty or an anomaly."""

    name = "duckduckgo_lite"

    def __init__(self, timeout_s: float = 20.0) -> None:
        self.timeout_s = timeout_s

    async def search(
        self, query: str, *, limit: int, recency: str | None
    ) -> list[SearchResult]:
        params = {"q": query}
        if recency in _DDG_RECENCY:
            params["df"] = _DDG_RECENCY[recency]
        headers = {"User-Agent": _BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
        url = str(httpx.URL(_DDG_LITE_URL, params=params))
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await guarded_get(client, url, headers=headers)
            response.raise_for_status()
            html = response.text
        return await asyncio.to_thread(parse_duckduckgo_lite, html, limit)


class WikipediaBackend:
    """Encyclopedia fallback. Not news — skipped for recency=day/week."""

    name = "wikipedia"

    def __init__(self, timeout_s: float = 20.0) -> None:
        self.timeout_s = timeout_s

    def skip_for_recency(self, recency: str | None) -> bool:
        return recency in _NEWS_RECENCY

    async def search(
        self, query: str, *, limit: int, recency: str | None
    ) -> list[SearchResult]:
        if self.skip_for_recency(recency):
            return []
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(limit),
            "format": "json",
            "utf8": "1",
        }
        headers = {
            "User-Agent": _BROWSER_UA,
            "Accept": "application/json",
        }
        url = str(httpx.URL(_WIKI_API, params=params))
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await guarded_get(client, url, headers=headers)
            response.raise_for_status()
            payload = json.loads(response.text)
        return parse_wikipedia_search(payload, limit)


class WebSearchTool:
    """Find pages worth reading.

    Without this the model can only reach URLs it already knows, which is why
    anything current -- news, prices, opening hours, what happened last week --
    used to end in a guessed address and an empty page.
    """

    name = "web_search"
    description = (
        "Search the web and get back ranked results with titles, URLs, and "
        "snippets. Use this first for anything current, local, or specific "
        "that you do not already know a URL for."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for, phrased as a search query",
            },
            "max_results": {
                "type": "integer",
                "description": "How many results to return (default 6, max 10)",
            },
            "recency": {
                "type": "string",
                "enum": ["day", "week", "month", "year"],
                "description": (
                    "Only return results published this recently. "
                    "Use it for news and current events."
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        backends: list[SearchBackend],
        *,
        max_results: int = 6,
    ) -> None:
        self.backends = backends
        self.max_results = max_results

    async def run(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(
                ok=False,
                output="[fail:other] Missing query",
                data={"fail_class": "fail:other"},
            )
        hit = web_search_targets_known_contact(query)
        if hit is not None:
            return ToolResult(
                ok=False,
                output=(
                    f"[fail:other] {hit.display_name} is already in the contacts "
                    f"book (alias `{hit.alias}`). Use the contacts tool or "
                    "send_sms. Do not search the public web for them."
                ),
                data={
                    "fail_class": "fail:other",
                    "contact_alias": hit.alias,
                },
            )
        limit = _clamp(kwargs.get("max_results"), self.max_results)
        recency = kwargs.get("recency")
        recency = str(recency).lower() if recency else None

        results: list[SearchResult] = []
        errors: list[str] = []
        for backend in self.backends:
            skip = getattr(backend, "skip_for_recency", None)
            if callable(skip) and skip(recency):
                continue
            try:
                results = await backend.search(query, limit=limit, recency=recency)
            except Exception as exc:
                # Includes BlockedUrlError. One backend failing is a reason to
                # try the next, never a reason to end the turn.
                errors.append(f"{backend.name}: {exc}")
                continue
            if results:
                break
            errors.append(f"{backend.name}: no results")

        results = _dedupe(results)[:limit]
        if not results:
            # Rate limiting looks exactly like a query nobody has written about,
            # so say both and give the model somewhere to go next. Tag is for
            # lesson mining / replan (same shape as scrape [fail:…]).
            tag = classify_search_failure("", errors)
            detail = f" ({'; '.join(errors)})" if errors else ""
            hint = (
                "The engine may be rate limiting. "
                if tag == "fail:rate_limit"
                else ""
            )
            if tag == "fail:empty" and any("no results" in e for e in errors):
                # Empty organic hits often are rate-limit shaped on DDG HTML.
                hint = "The engine may be rate limiting. "
            return ToolResult(
                ok=False,
                output=(
                    f"[{tag}] web_search found nothing for {query!r}{detail}. "
                    f"{hint}Try a shorter or differently worded query, or "
                    "scrape a known site directly."
                ),
                data={
                    "query": query,
                    "results": [],
                    "fail_class": tag,
                    "backend_errors": errors,
                },
            )

        return ToolResult(
            ok=True,
            output=_format(results),
            data={
                "query": query,
                "results": [
                    {"title": r.title, "url": r.url, "snippet": r.snippet}
                    for r in results
                ],
            },
        )


def build_search_tool(cfg: dict[str, Any], *, timeout_s: float = 20.0) -> WebSearchTool:
    timeout = float(cfg.get("timeout_s", timeout_s))
    # Fixed order, no keys, no container. DuckDuckGo HTML first; Lite when that
    # page is empty or the anomaly stub; Wikipedia only when both miss, and
    # never for recency=day/week (that is news, not an encyclopedia stub).
    return WebSearchTool(
        [
            DuckDuckGoBackend(timeout_s=timeout),
            DuckDuckGoLiteBackend(timeout_s=timeout),
            WikipediaBackend(timeout_s=timeout),
        ],
        max_results=int(cfg.get("max_results", 6)),
    )


def _clamp(raw: Any, default: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(1, min(_MAX_RESULTS, value))


def _dedupe(results: list[SearchResult]) -> list[SearchResult]:
    """One entry per page.

    Metasearch merges engines that disagree about trailing slashes and http
    versus https, and near-duplicate rows waste the small context these
    results are being read in.
    """
    seen: set[str] = set()
    out: list[SearchResult] = []
    for item in results:
        parsed = urlparse(item.url)
        key = f"{parsed.netloc.lower().removeprefix('www.')}{parsed.path.rstrip('/')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _format(results: list[SearchResult]) -> str:
    lines: list[str] = []
    for i, item in enumerate(results, start=1):
        snippet = redact_secrets(item.snippet)[:_SNIPPET_CHARS]
        lines.append(f"{i}. Title: {item.title or item.url}")
        # Label is load-bearing: qwen2.5:7b has answered with the title string
        # as if it were the href, then asked the user for "the URL".
        lines.append(f"   URL: {item.url}")
        if snippet:
            lines.append(f"   Snippet: {snippet}")
    lines.append("")
    lines.append(
        "Snippets are previews. Scrape the most relevant result before answering. "
        "Call scrape (HTML) or web_fetch (API/JSON) with the URL: value copied "
        "exactly. Never pass the Title line as url - titles are not URLs."
    )
    return "\n".join(lines)

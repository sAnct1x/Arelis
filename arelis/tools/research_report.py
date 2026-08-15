"""Deterministic multi-source research: search → scrape → markdown artifact."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from arelis.paths import user_data_dir
from arelis.research import (
    SourceHit,
    excerpt_text,
    extract_urls,
    pick_urls,
    render_report,
    save_report,
    title_for_url,
)
from arelis.tools.base import ToolResult

_RECENCY = frozenset({"day", "week", "month", "year"})

ToolRunner = Callable[..., Awaitable[ToolResult]]


class _Runnable(Protocol):
    async def run(self, **kwargs: Any) -> ToolResult: ...


def _as_runner(tool: _Runnable | ToolRunner | None) -> ToolRunner | None:
    if tool is None:
        return None
    if hasattr(tool, "run"):
        return tool.run  # type: ignore[return-value]
    return tool  # type: ignore[return-value]


class ResearchReportTool:
    name = "research_report"
    description = (
        "Run a multi-source research pass: web_search, scrape several distinct "
        "result URLs, and write a fixed markdown report (Question / Findings / "
        "Uncertainties / Sources) under outputs/research. Use for deep dives, "
        "investigations, thorough reports, and research-role asks. Do not use "
        "for weather, SMS, email, or a single known URL (scrape that directly)."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Research question or search query",
            },
            "max_sources": {
                "type": "integer",
                "description": "How many distinct URLs to scrape (default from config)",
            },
            "recency": {
                "type": "string",
                "enum": ["day", "week", "month", "year"],
                "description": "Prefer recent results (news / current events)",
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        search: _Runnable | ToolRunner,
        scrape: _Runnable | ToolRunner,
        *,
        fetch: _Runnable | ToolRunner | None = None,
        max_sources: int = 3,
        max_chars_per_source: int = 1200,
        output_dir: str | Path = "outputs/research",
    ) -> None:
        self._search = _as_runner(search)
        self._scrape = _as_runner(scrape)
        self._fetch = _as_runner(fetch)
        if self._search is None or self._scrape is None:
            raise ValueError("research_report requires search and scrape runners")
        self.max_sources = max(1, int(max_sources))
        self.max_chars_per_source = max(200, int(max_chars_per_source))
        out = Path(output_dir)
        self.output_dir = out if out.is_absolute() else user_data_dir() / out

    async def run(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, output="Missing query")

        max_sources = self.max_sources
        raw_max = kwargs.get("max_sources")
        if raw_max is not None:
            try:
                max_sources = max(1, min(10, int(raw_max)))
            except (TypeError, ValueError):
                max_sources = self.max_sources

        recency = kwargs.get("recency")
        recency_s = str(recency).lower() if recency else None
        if recency_s and recency_s not in _RECENCY:
            recency_s = None

        search_args: dict[str, Any] = {
            "query": query,
            "max_results": max(max_sources, 6),
        }
        if recency_s:
            search_args["recency"] = recency_s

        assert self._search is not None
        search_result = await self._search(**search_args)
        if not search_result.ok:
            return ToolResult(
                ok=False,
                output=search_result.output or "web_search failed",
                data={"query": query, "sources": [], "ok_count": 0},
            )

        urls = pick_urls(
            extract_urls(search_result.output, search_result.data),
            max_sources=max_sources,
        )
        if not urls:
            return ToolResult(
                ok=False,
                output="web_search returned no usable http(s) URLs to scrape.",
                data={"query": query, "sources": [], "ok_count": 0},
            )

        hits: list[SourceHit] = []
        failed: list[str] = []
        assert self._scrape is not None
        for url in urls:
            scrape_result = await self._scrape(
                url=url,
                max_chars=self.max_chars_per_source,
            )
            if scrape_result.ok:
                title = str(
                    (scrape_result.data or {}).get("title")
                    or title_for_url(url, search_result.data)
                ).strip() or url
                final_url = str(
                    (scrape_result.data or {}).get("url") or url
                ).strip() or url
                hits.append(
                    SourceHit(
                        title=title,
                        url=final_url,
                        excerpt=excerpt_text(
                            scrape_result.output,
                            max_chars=min(600, self.max_chars_per_source),
                        ),
                    )
                )
                continue

            # Non-HTML / API-shaped pages: optional web_fetch fallback.
            used_fetch = False
            if self._fetch is not None and _looks_non_html(scrape_result.output):
                fetch_result = await self._fetch(
                    url=url,
                    max_chars=self.max_chars_per_source,
                )
                used_fetch = True
                if fetch_result.ok:
                    title = title_for_url(url, search_result.data)
                    hits.append(
                        SourceHit(
                            title=title,
                            url=str(
                                (fetch_result.data or {}).get("url") or url
                            ).strip()
                            or url,
                            excerpt=excerpt_text(
                                fetch_result.output,
                                max_chars=min(600, self.max_chars_per_source),
                            ),
                        )
                    )
                    continue

            reason = (scrape_result.output or "scrape failed").splitlines()[0][:160]
            if used_fetch:
                reason = f"{reason} (fetch fallback also failed)"
            failed.append(f"{url} — {reason}")

        markdown = render_report(query, sources=hits, failed=failed)
        path = save_report(markdown, query=query, output_dir=self.output_dir)
        ok_count = len(hits)
        sources_data = [{"title": h.title, "url": h.url} for h in hits]
        ok = ok_count >= 1
        summary = (
            f"Research report written to {path} "
            f"({ok_count} source{'s' if ok_count != 1 else ''} scraped)."
        )
        if not ok:
            summary = (
                f"No pages scraped successfully. Report stub at {path}. "
                + (failed[0] if failed else "")
            )
        return ToolResult(
            ok=ok,
            output=f"{summary}\n\n{markdown}",
            data={
                "sources": sources_data,
                "path": str(path),
                "ok_count": ok_count,
                "query": query,
            },
        )


def _looks_non_html(output: str) -> bool:
    text = (output or "").lower()
    return (
        "fail:non_html" in text
        or "looks like json" in text
        or "not an article" in text
        or "non-html" in text
    )

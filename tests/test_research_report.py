"""Deterministic research_report pipeline (mocked search/scrape)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from arelis.core.claims import detect_exactness_need
from arelis.core.evidence import EvidenceLedger
from arelis.core.preflight import detect_intents
from arelis.core.skills import select_skill_ids
from arelis.research import SourceHit, extract_urls, pick_urls, render_report
from arelis.tools.base import ToolResult
from arelis.tools.research_report import ResearchReportTool


class _FakeSearch:
    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        return self.result


class _FakeScrape:
    def __init__(self, by_url: dict[str, ToolResult]) -> None:
        self.by_url = by_url
        self.calls: list[str] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        url = str(kwargs.get("url") or "")
        self.calls.append(url)
        return self.by_url.get(
            url,
            ToolResult(ok=False, output="missing fixture"),
        )


def _search_ok() -> ToolResult:
    return ToolResult(
        ok=True,
        output=(
            "1. Title: Alpha Story\n"
            "   URL: https://news.example/alpha\n"
            "   Snippet: preview a\n"
            "2. Title: Beta Story\n"
            "   URL: https://news.example/beta\n"
            "   Snippet: preview b\n"
            "3. Title: Gamma Story\n"
            "   URL: https://news.example/gamma\n"
            "   Snippet: preview c\n"
        ),
        data={
            "query": "perseids",
            "results": [
                {
                    "title": "Alpha Story",
                    "url": "https://news.example/alpha",
                    "snippet": "preview a",
                },
                {
                    "title": "Beta Story",
                    "url": "https://news.example/beta",
                    "snippet": "preview b",
                },
                {
                    "title": "Gamma Story",
                    "url": "https://news.example/gamma",
                    "snippet": "preview c",
                },
            ],
        },
    )


def test_extract_and_pick_urls_from_search_shape() -> None:
    result = _search_ok()
    urls = extract_urls(result.output, result.data)
    assert urls[:3] == [
        "https://news.example/alpha",
        "https://news.example/beta",
        "https://news.example/gamma",
    ]
    assert pick_urls(urls, max_sources=2) == urls[:2]
    # Dedupe www / trailing slash
    assert pick_urls(
        [
            "https://news.example/alpha",
            "https://www.news.example/alpha/",
            "https://news.example/beta",
        ],
        max_sources=3,
    ) == ["https://news.example/alpha", "https://news.example/beta"]


def test_render_report_shape_sources_only_ok() -> None:
    md = render_report(
        "What about the Perseids?",
        sources=[
            SourceHit(
                title="Alpha Story",
                url="https://news.example/alpha",
                excerpt="The shower peaks after midnight.",
            )
        ],
        failed=["https://news.example/beta — 403"],
    )
    assert "## Question" in md
    assert "## Findings" in md
    assert "## Uncertainties" in md
    assert "## Sources" in md
    assert "What about the Perseids?" in md
    assert "[Alpha Story](https://news.example/alpha)" in md
    assert "news.example/beta" not in md.split("## Sources", 1)[1]


@pytest.mark.asyncio
async def test_research_report_writes_file_and_ok_sources(
    tmp_path: Path,
) -> None:
    search = _FakeSearch(_search_ok())
    scrape = _FakeScrape(
        {
            "https://news.example/alpha": ToolResult(
                ok=True,
                output=(
                    "Title: Alpha Story\n\n"
                    "The Perseid meteor shower peaks after midnight local time."
                ),
                data={
                    "url": "https://news.example/alpha",
                    "title": "Alpha Story",
                },
            ),
            "https://news.example/beta": ToolResult(
                ok=False,
                output="[fail:http_403] Forbidden",
                data={"url": "https://news.example/beta"},
            ),
            "https://news.example/gamma": ToolResult(
                ok=True,
                output=(
                    "Title: Gamma Story\n\n"
                    "Observers reported dozens of meteors per hour."
                ),
                data={
                    "url": "https://news.example/gamma",
                    "title": "Gamma Story",
                },
            ),
        }
    )
    tool = ResearchReportTool(
        search,
        scrape,
        max_sources=3,
        max_chars_per_source=800,
        output_dir=tmp_path,
    )
    result = await tool.run(query="Perseid meteor shower peaks")
    assert result.ok
    assert result.data["ok_count"] == 2
    assert result.data["query"] == "Perseid meteor shower peaks"
    sources = result.data["sources"]
    assert {s["url"] for s in sources} == {
        "https://news.example/alpha",
        "https://news.example/gamma",
    }
    assert all("beta" not in s["url"] for s in sources)
    path = Path(result.data["path"])
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "## Question" in body
    assert "## Findings" in body
    assert "## Sources" in body
    assert "https://news.example/alpha" in body
    assert "https://news.example/gamma" in body
    # Failed scrape must not appear under Sources.
    sources_section = body.split("## Sources", 1)[1]
    assert "beta" not in sources_section
    assert search.calls and search.calls[0]["query"] == "Perseid meteor shower peaks"
    assert scrape.calls == [
        "https://news.example/alpha",
        "https://news.example/beta",
        "https://news.example/gamma",
    ]


@pytest.mark.asyncio
async def test_research_report_fails_when_no_scrape_ok(tmp_path: Path) -> None:
    search = _FakeSearch(_search_ok())
    scrape = _FakeScrape(
        {
            "https://news.example/alpha": ToolResult(
                ok=False, output="fail", data={"url": "https://news.example/alpha"}
            ),
            "https://news.example/beta": ToolResult(
                ok=False, output="fail", data={"url": "https://news.example/beta"}
            ),
            "https://news.example/gamma": ToolResult(
                ok=False, output="fail", data={"url": "https://news.example/gamma"}
            ),
        }
    )
    tool = ResearchReportTool(search, scrape, max_sources=2, output_dir=tmp_path)
    result = await tool.run(query="thin ask")
    assert not result.ok
    assert result.data["ok_count"] == 0
    assert result.data["sources"] == []
    assert Path(result.data["path"]).exists()


def test_evidence_research_report_adds_web_warrants() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "research_report",
        ok=True,
        output="report",
        data={
            "query": "perseids",
            "sources": [
                {"title": "A", "url": "https://news.example/a"},
                {"title": "B", "url": "https://news.example/b"},
            ],
            "ok_count": 2,
        },
        args={"query": "perseids"},
    )
    assert ledger.has_ok("web_search")
    assert ledger.has_ok("web")
    assert set(ledger.ok_web_sources()) == {
        "https://news.example/a",
        "https://news.example/b",
    }


def test_deep_dive_claims_and_preflight_and_skill() -> None:
    need = detect_exactness_need("Please investigate this thoroughly and write a report")
    assert need.needs_web_evidence
    hints = detect_intents("Can you deep dive into the Perseids?")
    assert any(h.kind == "research" for h in hints)
    ids = select_skill_ids(
        "I need a multi-source research report on tidal energy",
        available_tools={"research_report", "web_search", "scrape"},
    )
    assert "research" in ids
    # Fallthrough when research_report missing but web tools exist.
    ids_fb = select_skill_ids(
        "deep dive on the topic",
        available_tools={"web_search", "scrape"},
    )
    assert "research" in ids_fb

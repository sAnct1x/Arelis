from __future__ import annotations

import httpx
import pytest

from arelis.core.agent_loop import TOOL_POLICY
from arelis.tools.search import (
    DuckDuckGoBackend,
    SearchResult,
    WebSearchTool,
    WikipediaBackend,
    build_search_tool,
    parse_duckduckgo,
    parse_duckduckgo_lite,
    parse_wikipedia_search,
)


def _ddg_html() -> str:
    """A trimmed copy of what html.duckduckgo.com actually returns.

    Includes a sponsored row, because ads share the organic markup and the
    only thing separating them is one class.
    """
    return """<!DOCTYPE html>
<html><body>
<div class="result results_links result--ad">
  <h2 class="result__title">
    <a class="result__a" href="//duckduckgo.com/y.js?ad=1">Buy A Telescope Today</a>
  </h2>
  <a class="result__snippet">Lowest prices on optics.</a>
</div>
<div class="result results_links results_links_deep web-result">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a class="result__a"
         href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fperseids&amp;rut=9f">
         Perseid meteor shower peaks tonight</a>
    </h2>
    <a class="result__snippet">The shower peaks after midnight local time.</a>
  </div>
</div>
<div class="result results_links results_links_deep web-result">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a class="result__a" href="https://plain.example.com/direct">A direct link</a>
    </h2>
  </div>
</div>
</body></html>"""


def test_parses_results_and_unwraps_the_redirect() -> None:
    results = parse_duckduckgo(_ddg_html(), limit=10)

    urls = [r.url for r in results]
    assert "https://example.org/perseids" in urls
    assert "https://plain.example.com/direct" in urls
    assert results[0].title == "Perseid meteor shower peaks tonight"
    assert results[0].snippet == "The shower peaks after midnight local time."


def test_sponsored_rows_are_dropped() -> None:
    results = parse_duckduckgo(_ddg_html(), limit=10)
    assert all("telescope" not in r.title.lower() for r in results)
    assert all("y.js" not in r.url for r in results)


def test_a_result_without_a_snippet_is_still_returned() -> None:
    """Losing the preview text is much softer than losing the URL."""
    results = parse_duckduckgo(_ddg_html(), limit=10)
    direct = [r for r in results if r.url == "https://plain.example.com/direct"]
    assert direct and direct[0].snippet == ""


def test_limit_is_respected() -> None:
    assert len(parse_duckduckgo(_ddg_html(), limit=1)) == 1


def _lite_html() -> str:
    return """<!DOCTYPE html>
<html><body>
<table>
<tr>
  <td>
    <a class="result-link" rel="nofollow"
       href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fperseids&amp;rut=9f">
       Perseid meteor shower peaks tonight</a>
  </td>
</tr>
<tr>
  <td class="result-snippet">The shower peaks after midnight local time.</td>
</tr>
<tr>
  <td>
    <a class="result-link" href="//duckduckgo.com/y.js?ad=1">Buy a telescope</a>
  </td>
</tr>
</table>
</body></html>"""


def test_parses_lite_results_and_unwraps_the_redirect() -> None:
    results = parse_duckduckgo_lite(_lite_html(), limit=10)
    assert [r.url for r in results] == ["https://example.org/perseids"]
    assert results[0].title.strip() == "Perseid meteor shower peaks tonight"
    assert "midnight" in results[0].snippet


def test_parses_wikipedia_search_json() -> None:
    payload = {
        "query": {
            "search": [
                {
                    "title": "Perseids",
                    "snippet": "The <span class='searchmatch'>Perseids</span> are a meteor shower.",
                }
            ]
        }
    }
    results = parse_wikipedia_search(payload, limit=5)
    assert results[0].title == "Perseids"
    assert results[0].url == "https://en.wikipedia.org/wiki/Perseids"
    assert "<span" not in results[0].snippet
    assert "meteor shower" in results[0].snippet


class _Fake:
    def __init__(self, name: str, results=None, error: Exception | None = None) -> None:
        self.name = name
        self.results = results or []
        self.error = error
        self.calls: list[tuple[str, int, str | None]] = []

    async def search(self, query, *, limit, recency):
        self.calls.append((query, limit, recency))
        if self.error is not None:
            raise self.error
        return self.results


@pytest.mark.asyncio
async def test_returns_titles_urls_and_snippets() -> None:
    backend = _Fake(
        "fake",
        [SearchResult("Perseids tonight", "https://example.org/p", "After midnight.")],
    )
    result = await WebSearchTool([backend]).run(query="meteor shower tonight")

    assert result.ok
    assert "Perseids tonight" in result.output
    assert "https://example.org/p" in result.output
    assert "After midnight." in result.output
    assert result.data["results"][0]["url"] == "https://example.org/p"


@pytest.mark.asyncio
async def test_output_tells_a_small_model_not_to_stop_at_the_snippet() -> None:
    backend = _Fake("fake", [SearchResult("T", "https://example.org/p", "preview")])
    result = await WebSearchTool([backend]).run(query="x")
    assert "Scrape the most relevant result" in result.output


@pytest.mark.asyncio
async def test_a_dead_backend_falls_through_to_the_next_one() -> None:
    down = _Fake("primary", error=httpx.ConnectError("connection refused"))
    up = _Fake("duckduckgo", [SearchResult("T", "https://example.org/p")])

    result = await WebSearchTool([down, up]).run(query="anything")

    assert result.ok
    assert up.calls, "fallback backend was never reached"


@pytest.mark.asyncio
async def test_an_empty_backend_falls_through_too() -> None:
    empty = _Fake("primary", [])
    up = _Fake("duckduckgo", [SearchResult("T", "https://example.org/p")])

    result = await WebSearchTool([empty, up]).run(query="anything")

    assert result.ok
    assert up.calls


@pytest.mark.asyncio
async def test_finding_nothing_names_rate_limiting_as_a_cause() -> None:
    result = await WebSearchTool([_Fake("duckduckgo", [])]).run(query="zzz")

    assert not result.ok
    assert "[fail:empty]" in result.output
    assert result.data.get("fail_class") == "fail:empty"
    assert "rate limiting" in result.output
    assert result.data["results"] == []


@pytest.mark.asyncio
async def test_connect_errors_tag_fail_connect() -> None:
    down = _Fake("primary", error=httpx.ConnectError("connection refused"))
    empty = _Fake("duckduckgo", [])
    result = await WebSearchTool([down, empty]).run(query="zzz")
    assert not result.ok
    assert "[fail:connect]" in result.output
    assert result.data.get("fail_class") == "fail:connect"


@pytest.mark.asyncio
async def test_near_duplicate_urls_collapse() -> None:
    backend = _Fake(
        "fake",
        [
            SearchResult("A", "https://www.example.org/story/"),
            SearchResult("A again", "https://example.org/story"),
            SearchResult("B", "https://example.org/other"),
        ],
    )
    result = await WebSearchTool([backend]).run(query="x")
    assert len(result.data["results"]) == 2


@pytest.mark.asyncio
async def test_max_results_is_clamped_not_trusted() -> None:
    backend = _Fake("fake", [])
    await WebSearchTool([backend]).run(query="x", max_results=500)
    await WebSearchTool([backend]).run(query="y", max_results="nonsense")
    await WebSearchTool([backend]).run(query="z", max_results=0)

    limits = [limit for _, limit, _ in backend.calls]
    assert limits == [10, 6, 1]


@pytest.mark.asyncio
async def test_missing_query_is_a_clean_failure() -> None:
    result = await WebSearchTool([_Fake("fake")]).run()
    assert not result.ok
    assert "query" in result.output.lower()


@pytest.mark.asyncio
async def test_recency_reaches_duckduckgo_as_a_time_filter(monkeypatch) -> None:
    """News is the case where an undated result is worse than no result."""
    seen: dict[str, str] = {}

    async def fake_get(client, url, *, headers=None, block_private=True):
        seen["url"] = url
        seen["ua"] = (headers or {}).get("User-Agent", "")
        return httpx.Response(200, text=_ddg_html(), request=httpx.Request("GET", url))

    monkeypatch.setattr("arelis.tools.search.guarded_get", fake_get)
    results = await DuckDuckGoBackend().search("perseids", limit=5, recency="day")

    assert results
    assert "df=d" in seen["url"]
    assert "q=perseids" in seen["url"]
    # The polite research agent gets served an empty anomaly page here.
    assert "Mozilla" in seen["ua"]


def test_build_search_tool_uses_html_then_lite_then_wikipedia() -> None:
    plain = build_search_tool({})
    assert [b.name for b in plain.backends] == [
        "duckduckgo",
        "duckduckgo_lite",
        "wikipedia",
    ]

    # Legacy backend keys are ignored — order is fixed, no container.
    legacy = build_search_tool(
        {"backend": "searxng", "searxng_url": "http://127.0.0.1:8080"}
    )
    assert [b.name for b in legacy.backends] == [
        "duckduckgo",
        "duckduckgo_lite",
        "wikipedia",
    ]


@pytest.mark.asyncio
async def test_empty_html_falls_through_to_lite() -> None:
    html = _Fake("duckduckgo", [])
    lite = _Fake("duckduckgo_lite", [SearchResult("T", "https://example.org/p")])
    wiki = _Fake("wikipedia", [SearchResult("W", "https://en.wikipedia.org/wiki/T")])
    result = await WebSearchTool([html, lite, wiki]).run(query="anything")
    assert result.ok
    assert lite.calls
    assert not wiki.calls
    assert result.data["results"][0]["url"] == "https://example.org/p"


@pytest.mark.asyncio
async def test_empty_html_and_lite_fall_through_to_wikipedia() -> None:
    html = _Fake("duckduckgo", [])
    lite = _Fake("duckduckgo_lite", [])
    wiki = _Fake("wikipedia", [SearchResult("W", "https://en.wikipedia.org/wiki/T")])
    result = await WebSearchTool([html, lite, wiki]).run(query="perseids")
    assert result.ok
    assert wiki.calls
    assert result.data["results"][0]["url"] == "https://en.wikipedia.org/wiki/T"


@pytest.mark.asyncio
async def test_news_recency_skips_wikipedia() -> None:
    html = _Fake("duckduckgo", [])
    lite = _Fake("duckduckgo_lite", [])
    wiki = WikipediaBackend()
    result = await WebSearchTool([html, lite, wiki]).run(
        query="breaking", recency="day"
    )
    assert not result.ok
    assert "wikipedia" not in " ".join(result.data.get("backend_errors") or [])


def test_wikipedia_backend_skips_day_and_week_recency() -> None:
    wiki = WikipediaBackend()
    assert wiki.skip_for_recency("day")
    assert wiki.skip_for_recency("week")
    assert not wiki.skip_for_recency("month")
    assert not wiki.skip_for_recency(None)


def test_the_tool_is_registered_and_can_be_switched_off(tmp_path) -> None:
    from arelis.tools import build_tool_registry
    from arelis.workspace import WorkspaceRoots

    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    registry = build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert "web_search" in registry.names()

    off = build_tool_registry(
        {"tools": {"search": {"enabled": False}}, "agent": {}}, workspace
    )
    assert "web_search" not in off.names()


def test_policy_sends_current_questions_through_search_first() -> None:
    assert "web_search first" in TOOL_POLICY
    assert "never guess a url" in TOOL_POLICY.lower()
    assert "snippet alone" in TOOL_POLICY
    assert "never pass the title as url" in TOOL_POLICY.lower()
    assert "would you like me to proceed" in TOOL_POLICY.lower()


def test_search_format_labels_url_separately_from_title() -> None:
    from arelis.tools.search import SearchResult, _format

    text = _format(
        [
            SearchResult(
                title="The Latest Scary-Sounding AI Milestone",
                url="https://www.wsj.com/tech/ai/example",
                snippet="preview text",
            )
        ]
    )
    assert "Title: The Latest Scary-Sounding AI Milestone" in text
    assert "URL: https://www.wsj.com/tech/ai/example" in text
    assert "Never pass the Title line as url" in text

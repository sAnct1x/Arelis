"""Search result parsing. Fixture markup, not a live model turn."""

import asyncio

from arelis.tools.search import (
    SearchResult,
    WebSearchTool,
    merge_citations,
    parse_duckduckgo,
    parse_duckduckgo_lite,
    parse_wiki_citations,
    rank_matching_citations,
)

_QUERY = (
    "JWST K2-18 b atmosphere methane carbon dioxide water ammonia DMS DMDS Madhusudhan"
)

# Shortened from the encyclopedia page's cite templates. The ids and titles
# are the ones a fallback search has to surface. A parser that only keeps
# the article URL fails this.
_WIKITEXT = """
{{cite journal |last1=Madhusudhan |first1=Nikku |title=Carbon-bearing Molecules in a Possible Hycean Atmosphere |journal=The Astrophysical Journal Letters |arxiv=2309.05566 |doi=10.3847/2041-8213/acf577}}
{{cite journal |title=New Constraints on DMS and DMDS in the Atmosphere of K2-18 b from JWST MIRI |arxiv=2504.12267v1 |doi=10.3847/2041-8213/adc1c8}}
{{cite web |title=Planet K2-18 b |url=https://exoplanet.eu/catalog/k2_18_b--3953/}}
{{cite journal |title=A study of stellar spots on M dwarfs |arxiv=1502.04715}}
"""


def test_a_challenge_page_is_not_a_hit_list() -> None:
    html = (
        "<html><title>DuckDuckGo</title>"
        "<p>Unfortunately, bots use DuckDuckGo too.</p></html>"
    )
    assert parse_duckduckgo(html, 5) == []
    assert parse_duckduckgo_lite(html, 5) == []


def test_matching_citations_keep_the_papers_and_drop_the_rest() -> None:
    ranked = rank_matching_citations(
        parse_wiki_citations(_WIKITEXT),
        _QUERY,
        article="K2-18b",
        limit=6,
    )
    urls = [item.url for item in ranked]
    assert urls[0] == "https://arxiv.org/abs/2504.12267"
    assert "https://arxiv.org/abs/2309.05566" in urls
    assert not any("1502.04715" in url for url in urls)
    assert not any("exoplanet.eu" in url for url in urls)
    assert ranked[0].snippet == "Reference cited on K2-18b"


def test_one_shared_word_is_not_enough() -> None:
    citations = parse_wiki_citations(
        "{{cite web |title=Asyncio tutorial for Python |url=https://example.com/asyncio}}\n"
        "{{cite web |title=Baking bread at home |url=https://example.com/bread}}"
    )
    ranked = rank_matching_citations(citations, "python asyncio tutorial", limit=4)
    assert [item.url for item in ranked] == ["https://example.com/asyncio"]


def test_citations_fill_ahead_of_the_article() -> None:
    cited = [SearchResult("Paper", "https://arxiv.org/abs/2309.05566")]
    pages = [SearchResult("K2-18b", "https://en.wikipedia.org/wiki/K2-18b")]
    merged = merge_citations(cited, pages, 6)
    assert merged[0].url == "https://arxiv.org/abs/2309.05566"
    assert merged[-1].url.startswith("https://en.wikipedia.org/")


def test_a_full_citation_list_does_not_keep_the_article() -> None:
    cited = [
        SearchResult(f"Paper {i}", f"https://example.com/p{i}") for i in range(6)
    ]
    pages = [SearchResult("Article", "https://en.wikipedia.org/wiki/Article")]
    merged = merge_citations(cited, pages, 6)
    assert len(merged) == 6
    assert all("wikipedia.org" not in item.url for item in merged)


class _Backend:
    def __init__(self, name: str, rows: list[SearchResult]) -> None:
        self.name = name
        self.rows = rows
        self.calls = 0

    async def search(self, query: str, *, limit: int, recency: str | None):
        self.calls += 1
        return list(self.rows)


def test_a_real_hit_list_stops_before_the_encyclopedia() -> None:
    first = _Backend(
        "duckduckgo",
        [SearchResult("Paper", "https://arxiv.org/abs/2309.05566", "abstract")],
    )
    wiki = _Backend(
        "wikipedia",
        [SearchResult("K2-18b", "https://en.wikipedia.org/wiki/K2-18b")],
    )
    tool = WebSearchTool([first, wiki], max_results=6)
    result = asyncio.run(tool.run(query="jwst atmosphere methane"))
    assert result.ok
    assert "https://arxiv.org/abs/2309.05566" in result.output
    assert wiki.calls == 0


def test_an_empty_engine_falls_through() -> None:
    first = _Backend("duckduckgo", [])
    wiki = _Backend(
        "wikipedia",
        [SearchResult("K2-18b", "https://en.wikipedia.org/wiki/K2-18b")],
    )
    tool = WebSearchTool([first, wiki], max_results=6)
    result = asyncio.run(tool.run(query="jwst atmosphere methane"))
    assert result.ok
    assert wiki.calls == 1
    assert "https://en.wikipedia.org/wiki/K2-18b" in result.output

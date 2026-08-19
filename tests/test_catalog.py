"""Catalog tool — arXiv / Horizons with no key, APOD / ADS only after a pasted key."""

from __future__ import annotations

import httpx
import pytest

from arelis.science.keys import ScienceKeys, load_science_keys
from arelis.tools import build_tool_registry
from arelis.tools.catalog import CatalogTool
from arelis.workspace import WorkspaceRoots

_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1234.5678v1</id>
    <title>A Fixture Paper on Waves</title>
    <published>2024-01-15T00:00:00Z</published>
    <author><name>A. Example</name></author>
    <summary>An abstract that is not instructions.</summary>
    <link title="pdf" href="http://export.arxiv.org/pdf/1234.5678v1" type="application/pdf"/>
  </entry>
</feed>
"""


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "project", "path": str(root)}]}}
    )


@pytest.mark.asyncio
async def test_arxiv_parses_atom_and_acknowledges_arxiv() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "export.arxiv.org" in str(request.url)
        return httpx.Response(200, text=_ATOM)

    tool = CatalogTool(client=_client(handler))
    result = await tool.run(action="arxiv", query="gravitational waves")
    assert result.ok, result.output
    assert "arXiv" in result.output
    assert "not an arXiv" in result.output.lower() or "not an arxiv" in result.output.lower()
    assert "Fixture Paper" in result.output
    assert result.data["n"] == 1


@pytest.mark.asyncio
async def test_horizons_never_sends_email() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"result": "range 1.52 au"})

    tool = CatalogTool(client=_client(handler))
    result = await tool.run(action="horizons", target="Mars", date="2026-08-19")
    assert result.ok, result.output
    assert seen
    assert "EMAIL" not in seen[0].upper()
    assert "ssd.jpl.nasa.gov" in result.output
    assert "1.52" in result.output


@pytest.mark.asyncio
async def test_apod_without_key_is_honest() -> None:
    tool = CatalogTool(
        client=_client(lambda _r: httpx.Response(500)),
        keys=ScienceKeys(),
    )
    result = await tool.run(action="apod")
    assert not result.ok
    assert result.data["fail_class"] == "fail:config"
    assert "nasa.api_key" in result.output
    assert "DEMO_KEY" in result.output


@pytest.mark.asyncio
async def test_apod_refuses_demo_key_and_does_not_call_nasa() -> None:
    called = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json={"title": "nope"})

    tool = CatalogTool(
        client=_client(handler),
        keys=ScienceKeys(nasa_api_key="DEMO_KEY"),
    )
    result = await tool.run(action="apod")
    assert not result.ok
    assert called["n"] == 0
    assert "DEMO_KEY" in result.output


@pytest.mark.asyncio
async def test_apod_with_key_returns_caption() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.nasa.gov" in str(request.url)
        assert "DEMO_KEY" not in str(request.url)
        return httpx.Response(
            200,
            json={
                "title": "Crab Nebula",
                "date": "2026-08-19",
                "url": "https://example.com/apod.jpg",
                "media_type": "image",
                "explanation": "A fixture caption.",
            },
        )

    tool = CatalogTool(
        client=_client(handler),
        keys=ScienceKeys(nasa_api_key="testkey_fixture"),
    )
    result = await tool.run(action="apod")
    assert result.ok, result.output
    assert "Crab Nebula" in result.output
    assert "api.nasa.gov" in result.output


@pytest.mark.asyncio
async def test_ads_without_token_is_honest() -> None:
    tool = CatalogTool(client=_client(lambda _r: httpx.Response(500)), keys=ScienceKeys())
    result = await tool.run(action="ads", query="exoplanet")
    assert not result.ok
    assert "ads.token" in result.output


@pytest.mark.asyncio
async def test_ads_with_token_lists_bibcodes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer test_token_fixture"
        return httpx.Response(
            200,
            json={
                "response": {
                    "docs": [
                        {
                            "bibcode": "2020ApJ...1000....1E",
                            "title": ["Fixture ADS Paper"],
                            "author": ["Example, A."],
                            "year": "2020",
                            "abstract": "A fixture abstract.",
                        }
                    ]
                }
            },
        )

    tool = CatalogTool(
        client=_client(handler),
        keys=ScienceKeys(ads_token="test_token_fixture"),
    )
    result = await tool.run(action="ads", query="exoplanet")
    assert result.ok, result.output
    assert "2020ApJ" in result.output
    assert "Fixture ADS Paper" in result.output


@pytest.mark.asyncio
async def test_rejects_expression_query() -> None:
    tool = CatalogTool(client=_client(lambda _r: httpx.Response(200, text=_ATOM)))
    result = await tool.run(action="arxiv", query="__import__('os')")
    assert not result.ok
    assert "plain search" in result.output.lower()


def test_catalog_is_on_for_jobs(workspace) -> None:
    config = {"tools": {}, "agent": {}}
    jobs = build_tool_registry(config, workspace, allow_send=False)
    assert jobs.get("catalog") is not None
    attended = build_tool_registry(config, workspace, allow_send=True)
    assert attended.get("catalog") is not None
    assert not attended.needs_confirm("catalog", {"action": "arxiv", "query": "waves"})


def test_load_science_keys_from_file(tmp_path) -> None:
    path = tmp_path / "secrets.yaml"
    path.write_text(
        "nasa:\n  api_key: testkey_fixture\n"
        "ads:\n  token: test_token_fixture\n",
        encoding="utf-8",
    )
    keys = load_science_keys(path)
    assert keys.nasa_ready
    assert keys.ads_ready


def test_demo_key_in_file_is_not_ready(tmp_path) -> None:
    path = tmp_path / "secrets.yaml"
    path.write_text("nasa:\n  api_key: DEMO_KEY\n", encoding="utf-8")
    keys = load_science_keys(path)
    assert keys.nasa_is_demo
    assert not keys.nasa_ready

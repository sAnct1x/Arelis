"""ScrapeTool: article extraction, AMP fallback, URL guards."""

from __future__ import annotations

import httpx
import pytest

from arelis.tools.scrape import ScrapeTool


def _patch_fetch(
    monkeypatch,
    pages: dict[str, str],
    *,
    content_types: dict[str, str] | None = None,
):
    content_types = content_types or {}

    async def fake_get(client, request_url, *, headers=None, block_private=True):
        html = pages.get(str(request_url))
        if html is None:
            # Allow trailing-slash / amp path lookups
            for key, value in pages.items():
                if str(request_url).rstrip("/") == key.rstrip("/"):
                    html = value
                    request_url = key
                    break
        if html is None:
            raise httpx.HTTPError(f"missing fixture for {request_url}")
        req = httpx.Request("GET", str(request_url))
        ctype = content_types.get(str(request_url), "text/html; charset=utf-8")
        return httpx.Response(
            200,
            text=html,
            request=req,
            headers={"content-type": ctype},
        )

    monkeypatch.setattr("arelis.tools.scrape.guarded_get", fake_get)


@pytest.mark.asyncio
async def test_scrape_returns_title_and_readable_text(monkeypatch) -> None:
    html = """<!DOCTYPE html>
<html><head><title>Lab Notes</title></head>
<body><article><p>Aligned the interferometer mirrors today with clear fringe contrast on the camera.</p>
<p>Next we lock the piezo gain for the overnight run.</p></article>
<script>evil()</script></body></html>
"""
    _patch_fetch(monkeypatch, {"https://example.com/article": html})
    result = await ScrapeTool("test-agent", block_private_urls=False).run(
        url="https://example.com/article"
    )
    assert result.ok
    assert "Lab Notes" in result.output or "interferometer" in result.output
    assert "interferometer" in result.output
    assert "evil()" not in result.output
    assert result.data["url"] == "https://example.com/article"
    assert result.data.get("strategy")


@pytest.mark.asyncio
async def test_scrape_refuses_a_page_with_almost_no_readable_text(monkeypatch) -> None:
    html = "<html><body><div id='app'></div></body></html>"
    _patch_fetch(monkeypatch, {"https://example.com/spa": html})
    result = await ScrapeTool("test-agent", block_private_urls=False).run(
        url="https://example.com/spa"
    )
    assert not result.ok
    assert (
        "JavaScript" in result.output
        or "readable" in result.output.lower()
        or "JS" in result.output
    )


@pytest.mark.asyncio
async def test_scrape_retries_amp_when_main_is_shell(monkeypatch) -> None:
    shell = """
    <html><head>
      <link rel="amphtml" href="https://example.com/story/amp"/>
      <title>Shell</title>
    </head><body><div id="app"></div></body></html>
    """
    amp = """
    <html><head><title>Real story</title></head>
    <body><article>
      <p>The laboratory published sixteen AI-designed viral genomes that replicate in bacteria under controlled conditions.</p>
      <p>Independent labs are attempting to reproduce the result before any policy response.</p>
    </article></body></html>
    """
    _patch_fetch(
        monkeypatch,
        {
            "https://example.com/story": shell,
            "https://example.com/story/amp": amp,
        },
    )
    result = await ScrapeTool("test-agent", block_private_urls=False).run(
        url="https://example.com/story"
    )
    assert result.ok
    assert "sixteen AI-designed" in result.output
    assert result.data["url"] == "https://example.com/story/amp"
    assert "https://example.com/story" in result.data["tried"]


@pytest.mark.asyncio
async def test_scrape_honours_max_chars(monkeypatch) -> None:
    body = "word " * 400
    html = f"<html><body><article><p>{body}</p></article></body></html>"
    _patch_fetch(monkeypatch, {"https://example.com/long": html})
    result = await ScrapeTool("test-agent", block_private_urls=False).run(
        url="https://example.com/long", max_chars=40
    )
    assert result.ok
    assert "truncated to 40 chars" in result.output


@pytest.mark.asyncio
async def test_scrape_surfaces_blocked_urls(monkeypatch) -> None:
    from arelis.tools.fetch import BlockedUrlError

    async def blocked(client, request_url, *, headers=None, block_private=True):
        raise BlockedUrlError("blocked private URL")

    monkeypatch.setattr("arelis.tools.scrape.guarded_get", blocked)
    result = await ScrapeTool("test-agent", block_private_urls=True).run(
        url="http://127.0.0.1/secret"
    )
    assert not result.ok
    assert "blocked" in result.output.lower()


@pytest.mark.asyncio
async def test_scrape_rejects_page_title_as_url() -> None:
    result = await ScrapeTool("test-agent").run(
        url="The Latest Scary-Sounding AI Milestone: A Brand-New Virus"
    )
    assert not result.ok
    assert "Not an http(s) URL" in result.output


@pytest.mark.asyncio
async def test_scrape_points_json_at_web_fetch(monkeypatch) -> None:
    _patch_fetch(
        monkeypatch,
        {"https://example.com/api": '{"ok": true, "temp": 72}'},
        content_types={"https://example.com/api": "application/json"},
    )
    result = await ScrapeTool("test-agent", block_private_urls=False).run(
        url="https://example.com/api"
    )
    assert not result.ok
    assert "web_fetch" in result.output.lower()


@pytest.mark.asyncio
async def test_scrape_accepts_plain_text(monkeypatch) -> None:
    body = (
        "Field log: fringe contrast improved after remounting the U100A pair. "
        "Piezo gain locked at 0.42 for the overnight run."
    )
    _patch_fetch(
        monkeypatch,
        {"https://example.com/notes.txt": body},
        content_types={"https://example.com/notes.txt": "text/plain"},
    )
    result = await ScrapeTool("test-agent", block_private_urls=False).run(
        url="https://example.com/notes.txt"
    )
    assert result.ok
    assert "fringe contrast" in result.output
    assert result.data.get("strategy") == "plain-text"

from __future__ import annotations

import httpx
import pytest

from arelis.core.agent_loop import TOOL_POLICY
from arelis.tools.html_text import extract_text, looks_like_css, looks_like_html
from arelis.tools.web import WebFetchTool


def _html_with_font_css() -> str:
    return """<!DOCTYPE html>
<html>
<head>
  <title>Tonight's Forecast</title>
  <style>
    @font-face {
      font-family: 'Roboto';
      font-style: normal;
      font-weight: 400;
      src: url(https://fonts.gstatic.com/s/roboto/v30/x.woff2) format('woff2');
    }
    body { font-family: Roboto, sans-serif; }
  </style>
</head>
<body>
  <p>High 72F with clear skies tonight in Springfield, Illinois.</p>
</body>
</html>
"""


def _patch_fetch(monkeypatch, *, text: str, content_type: str, url: str = "https://example.com/x"):
    async def fake_get(client, request_url, *, headers=None, block_private=True):
        req = httpx.Request("GET", url)
        return httpx.Response(
            200,
            text=text,
            headers={"content-type": content_type},
            request=req,
        )

    monkeypatch.setattr("arelis.tools.web.guarded_get", fake_get)


@pytest.mark.asyncio
async def test_web_fetch_strips_inline_font_css_from_html(monkeypatch) -> None:
    _patch_fetch(
        monkeypatch,
        text=_html_with_font_css(),
        content_type="text/html; charset=utf-8",
    )
    result = await WebFetchTool("test", block_private_urls=False).run(
        url="https://example.com/weather"
    )
    assert result.ok
    assert "72F" in result.output
    assert "Springfield" in result.output
    assert "@font-face" not in result.output
    assert "Roboto" not in result.output


@pytest.mark.asyncio
async def test_web_fetch_rejects_stylesheet_body(monkeypatch) -> None:
    css = """
@font-face {
  font-family: 'Roboto';
  src: url(https://fonts.gstatic.com/s/roboto/v30/x.woff2) format('woff2');
}
body { margin: 0; }
"""
    _patch_fetch(monkeypatch, text=css, content_type="text/css")
    result = await WebFetchTool("test", block_private_urls=False).run(
        url="https://example.com/styles.css"
    )
    assert not result.ok
    assert "CSS" in result.output
    assert "@font-face" not in result.output


@pytest.mark.asyncio
async def test_web_fetch_returns_json_raw(monkeypatch) -> None:
    payload = '{"temp_f": 72, "conditions": "clear"}'
    _patch_fetch(monkeypatch, text=payload, content_type="application/json")
    result = await WebFetchTool("test", block_private_urls=False).run(
        url="https://example.com/api/weather"
    )
    assert result.ok
    assert result.output == payload


@pytest.mark.asyncio
async def test_web_fetch_thin_html_shell_fails(monkeypatch) -> None:
    shell = """<!DOCTYPE html><html><head><title>App</title>
<style>@font-face{font-family:'Roboto';src:url(x)}</style>
</head><body><div id="root"></div></body></html>"""
    _patch_fetch(monkeypatch, text=shell, content_type="text/html")
    result = await WebFetchTool("test", block_private_urls=False).run(
        url="https://example.com/spa"
    )
    assert not result.ok
    assert "JavaScript" in result.output


def test_extract_text_drops_style_blocks() -> None:
    title, text = extract_text(_html_with_font_css())
    assert title == "Tonight's Forecast"
    assert "72F" in text
    assert "@font-face" not in text


def test_content_sniffs() -> None:
    assert looks_like_html("<!DOCTYPE html><html></html>", "application/octet-stream")
    assert looks_like_css("@font-face { font-family: X; }", "text/plain")
    assert not looks_like_css(_html_with_font_css(), "text/html")


def test_tool_policy_prefers_scrape_for_pages() -> None:
    assert "Prefer scrape" in TOOL_POLICY
    assert "web_fetch" in TOOL_POLICY.lower()
    assert "apis" in TOOL_POLICY.lower()


@pytest.mark.asyncio
async def test_web_fetch_rejects_page_title_as_url() -> None:
    tool = WebFetchTool(user_agent="test")
    result = await tool.run(url="The Latest Scary-Sounding AI Milestone: A Brand-New Virus")
    assert not result.ok
    assert "Not an http(s) URL" in result.output
    assert "Titles are not URLs" in result.output

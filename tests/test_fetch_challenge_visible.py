"""Visible-text challenge detection: scripts do not pad a wall into an article.

No network. Monkeypatch guarded_get / guarded_request. Nothing here solves a wall.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.evidence import looks_like_challenge_page
from arelis.tools import build_tool_registry
from arelis.tools.scrape import ScrapeTool
from arelis.tools.web import WebFetchTool
from tests._wall_fixtures import BIG_JS, WALL_FIXTURES
from tests.test_fetch_challenge import _LONG_ARTICLE, _install_scrape, _install_web

_CF_URL = "https://example.test/gated"
_WORDING = "Just a moment. Checking your browser. Verify you are human."

_SHORT_DOCS = "SHORT docs page, reCAPTCHA integration (~600 chars)"
_SHORT_BLOG = "short blog post about captchas (~700 chars)"
_XFAIL_SHORT_CAPTCHA_TALK = frozenset({_SHORT_DOCS, _SHORT_BLOG})


def _visible_len(html: str) -> int:
    from arelis.core.evidence import _visible_text

    return len(_visible_text(html))


def _wall_html(target_visible: int, *, script: str = "") -> str:
    seed = _WORDING + " "
    extra = f"<script>{script}</script>" if script else ""
    pad = "x" * (target_visible + 80)
    html = (
        f"<html><head><title>Gate</title>{extra}</head>"
        f"<body><p>{seed}{pad}</p></body></html>"
    )
    vis_n = _visible_len(html)
    over = vis_n - target_visible
    assert over >= 0
    pad = pad[:-over] if over else pad
    html = (
        f"<html><head><title>Gate</title>{extra}</head>"
        f"<body><p>{seed}{pad}</p></body></html>"
    )
    assert _visible_len(html) == target_visible
    return html


def test_1999_visible_chars_is_a_challenge_2000_is_not() -> None:
    thin = _wall_html(1999)
    thick = _wall_html(2000)
    assert looks_like_challenge_page(thin, 200) is True
    assert looks_like_challenge_page(thick, 200) is False


def test_inline_script_does_not_change_the_1999_2000_boundary() -> None:
    thin = _wall_html(1999, script=BIG_JS)
    thick = _wall_html(2000, script=BIG_JS)
    assert looks_like_challenge_page(thin, 200) is True
    assert looks_like_challenge_page(thick, 200) is False


def test_cloudflare_200_with_inline_js_is_a_challenge() -> None:
    html = (
        "<html><head><title>Just a moment...</title>"
        f"<script>{BIG_JS}</script></head><body>"
        "<p>Checking your browser. Verify you are human.</p>"
        "</body></html>"
    )
    assert looks_like_challenge_page(html, 200) is True


def test_hcaptcha_200_with_inline_js_is_a_challenge() -> None:
    html = (
        "<html><head><title>Security check</title>"
        f"<script>{BIG_JS}</script></head><body>"
        "<h1>Please verify you are human</h1>"
        '<div class="h-captcha"></div>'
        "</body></html>"
    )
    assert looks_like_challenge_page(html, 200) is True


@pytest.mark.asyncio
async def test_web_fetch_cloudflare_200_with_inline_js_is_one_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<html><head><title>Just a moment...</title>"
        f"<script>{BIG_JS}</script></head><body>"
        "<p>Checking your browser. Verify you are human.</p>"
        "</body></html>"
    )
    hits = _install_web(monkeypatch, html, status=200)
    result = await WebFetchTool("arelis-test/1.0", offer_browser=True).run(url=_CF_URL)
    assert result.ok is False
    assert result.data.get("fail_class") == "fail:challenge"
    assert "[fail:challenge]" in result.output
    assert hits == [_CF_URL]


@pytest.mark.asyncio
async def test_web_fetch_hcaptcha_200_with_inline_js_is_one_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<html><head><title>Security check</title>"
        f"<script>{BIG_JS}</script></head><body>"
        "<h1>Please verify you are human</h1>"
        '<div class="h-captcha"></div>'
        "</body></html>"
    )
    hits = _install_web(monkeypatch, html, status=200)
    result = await WebFetchTool("arelis-test/1.0").run(url=_CF_URL)
    assert result.ok is False
    assert result.data.get("fail_class") == "fail:challenge"
    assert hits == [_CF_URL]


@pytest.mark.asyncio
async def test_scrape_403_with_inline_js_stops_without_sibling_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<html><head><title>Just a moment...</title>"
        f"<script>{BIG_JS}</script></head><body>"
        "<h1>Attention Required</h1>"
        "<p>Checking your browser. Verify you are human.</p>"
        "</body></html>"
    )
    hits = _install_scrape(monkeypatch, html, status=403)
    result = await ScrapeTool("arelis-test/1.0", offer_browser=True).run(url=_CF_URL)
    assert result.ok is False
    assert result.data.get("fail_class") == "fail:challenge"
    assert "[fail:challenge]" in result.output
    assert hits == [_CF_URL]


def test_markup_only_hcaptcha_class_on_a_contact_form_is_not_a_challenge() -> None:
    html = """
    <html><body>
      <h1>Contact</h1>
      <form>
        <p>Send a note and we will reply.</p>
        <input name="email" />
        <div class="h-captcha" data-sitekey="00000000-0000-0000-0000-000000000000"></div>
      </form>
    </body></html>
    """
    assert looks_like_challenge_page(html, 200) is False


def test_markup_only_captcha_box_class_is_not_a_challenge() -> None:
    html = """
    <html><body>
      <p>Leave a comment below.</p>
      <div class="captcha-box"></div>
    </body></html>
    """
    assert looks_like_challenge_page(html, 200) is False


def test_long_article_about_captchas_stays_clear() -> None:
    assert looks_like_challenge_page(_LONG_ARTICLE, 200) is False


def test_web_fetch_and_scrape_offer_browser_follows_attended() -> None:
    config: dict[str, Any] = {"tools": {}, "agent": {}, "workspace": {"roots": ["."]}}
    jobs = build_tool_registry(config, allow_send=False, attended=False)
    present = build_tool_registry(config, allow_send=False, attended=True)
    for name in ("web_fetch", "scrape"):
        quiet = jobs.get(name)
        live = present.get(name)
        assert isinstance(quiet, (WebFetchTool, ScrapeTool))
        assert isinstance(live, (WebFetchTool, ScrapeTool))
        assert quiet.offer_browser is False
        assert live.offer_browser is True


def _fixture_params() -> list[Any]:
    rows: list[Any] = []
    for name, is_wall, status, body in WALL_FIXTURES:
        marks = ()
        if name in _XFAIL_SHORT_CAPTCHA_TALK:
            marks = (
                pytest.mark.xfail(
                    strict=True,
                    reason="short page that discusses captchas; documented limit",
                ),
            )
        rows.append(
            pytest.param(name, is_wall, status, body, id=name, marks=marks)
        )
    return rows


@pytest.mark.parametrize("name,is_wall,status,body", _fixture_params())
def test_labelled_wall_fixtures(
    name: str, is_wall: bool, status: int, body: str
) -> None:
    del name
    assert looks_like_challenge_page(body, status) is is_wall

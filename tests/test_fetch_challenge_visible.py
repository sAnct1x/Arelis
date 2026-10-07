"""Visible-text challenge detection: scripts do not pad a wall into an article.

No network. Monkeypatch guarded_get / guarded_request. Nothing here solves a wall.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

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
    return [
        pytest.param(name, is_wall, status, body, id=name)
        for name, is_wall, status, body in WALL_FIXTURES
    ]


def _fixture_body(name: str) -> str:
    for label, _is_wall, _status, body in WALL_FIXTURES:
        if label == name:
            return body
    raise AssertionError("labelled page is missing")


@pytest.mark.parametrize("name,is_wall,status,body", _fixture_params())
def test_labelled_wall_fixtures(
    name: str, is_wall: bool, status: int, body: str
) -> None:
    del name
    assert looks_like_challenge_page(body, status) is is_wall


def test_short_gate_inside_main_is_still_a_wall() -> None:
    html = "<html><body><main><p>Please verify you are human.</p></main></body></html>"
    assert looks_like_challenge_page(html, 200) is True


@pytest.mark.parametrize(
    "html",
    (
        "<main><h1>One more step</h1><p>Please complete the security check to access example.com. Verify you are human to continue.</p></main>",
        "<main><h1>Access check</h1><p>Please verify you are human. This helps us keep the site safe for everyone who visits it each day.</p></main>",
    ),
)
def test_a_gate_explanation_inside_main_is_still_a_wall(html: str) -> None:
    assert looks_like_challenge_page(html, 200) is True


def test_style_and_comment_blocks_do_not_pad_a_gate() -> None:
    gate = "<html><body><p>Verify you are human.</p></body></html>"
    style = (
        "<html><body><style>" + ("z" * 5000) + "</style><p>Verify you are human.</p></body></html>"
    )
    comment = "<html><body><!--" + ("z" * 5000) + "--><p>Verify you are human.</p></body></html>"
    assert looks_like_challenge_page(gate, 200) is True
    assert looks_like_challenge_page(style, 200) is True
    assert looks_like_challenge_page(comment, 200) is True
    assert _visible_len(style) == _visible_len(gate)
    assert _visible_len(comment) == _visible_len(gate)


def test_unterminated_script_does_not_hide_a_gate_behind_padding() -> None:
    html = "<html><body><p>Verify you are human.</p><script>" + ("var secret = 1;" * 400)
    assert looks_like_challenge_page(html, 200) is True
    assert _visible_len(html) < 2000


def test_hostile_unclosed_script_tags_finish_quickly() -> None:
    import time

    page = "<p>Verify you are human.</p>" + ("<script " * 25_000)
    assert len(page) > 200_000
    assert ">" not in page.split("</p>", 1)[-1]
    started = time.perf_counter()
    is_wall = looks_like_challenge_page(page, 200)
    elapsed = time.perf_counter() - started
    assert is_wall is False
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_web_fetch_reads_a_short_blog_about_captchas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _fixture_body(_SHORT_BLOG)
    url = "https://example.test/blog"
    hits = _install_web(monkeypatch, body, status=200)
    result = await WebFetchTool("arelis-test/1.0", offer_browser=True).run(url=url)
    assert result.data.get("fail_class") != "fail:challenge"
    assert "human check" not in result.output.lower()
    assert "crosswalks" in result.output
    assert hits == [url]


@pytest.mark.asyncio
async def test_scrape_reads_a_short_captcha_docs_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _fixture_body(_SHORT_DOCS)
    url = "https://example.test/docs"
    hits = _install_scrape(monkeypatch, body, status=200)
    result = await ScrapeTool("arelis-test/1.0", offer_browser=True).run(url=url)
    assert result.ok is True
    assert result.data.get("fail_class") != "fail:challenge"
    assert "human check" not in result.output.lower()
    assert "grecaptcha.execute" in result.output
    assert hits == [url]


@pytest.mark.asyncio
async def test_scrape_long_403_wall_makes_exactly_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _fixture_body("LONG 403 interstitial: captcha wording + 6KB of real-looking page chrome")
    assert _visible_len(body) > 2000
    hits = _install_scrape(monkeypatch, body, status=403)
    result = await ScrapeTool("arelis-test/1.0", offer_browser=True).run(url=_CF_URL)
    assert result.ok is False
    assert result.data.get("fail_class") == "fail:challenge"
    assert hits == [_CF_URL]


@pytest.mark.asyncio
async def test_scrape_skips_a_long_403_wall_on_a_follow_up_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = (
        "<html><head><title>Story</title></head>"
        "<body><div id='root'></div><p>Loading</p></body></html>"
    )
    pad = "The harbor log records a calm tide and a late ferry. " * 50
    wall = (
        "<html><body><article><h1>Blocked</h1>"
        "<p>Complete the captcha to continue. Verify you are human.</p>"
        f"<p>{pad}</p></article></body></html>"
    )
    assert _visible_len(wall) > 2000
    hits: list[str] = []
    import arelis.tools.scrape as scrape
    from tests.test_fetch_challenge import _Response

    async def _fake_get(*args: Any, **kwargs: Any) -> _Response:
        url = str(args[1] if len(args) > 1 else kwargs.get("url") or "")
        hits.append(url)
        parsed = urlparse(url)
        twin = f"{parsed.path}?{parsed.query}"
        if "amp" in twin.lower():
            return _Response(wall, status=403, url=url)
        return _Response(shell, status=200, url=url)

    monkeypatch.setattr(scrape, "guarded_get", _fake_get)
    result = await ScrapeTool("arelis-test/1.0", offer_browser=True).run(
        url="https://example.test/story"
    )
    assert len(hits) > 1
    assert result.ok is False
    assert "harbor log" not in result.output

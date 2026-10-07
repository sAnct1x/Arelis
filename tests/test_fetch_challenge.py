"""scrape / web_fetch stop on a captcha or login wall and hand it to her.

No network. The challenge HTML is a stub. A short real page from the
thin-page tests must not trip this. Nothing here solves a wall.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from arelis.core.evidence import classify_fetch_failure
from arelis.core.turn_dispatch import dispatch_calls
from arelis.tools.scrape import ScrapeTool
from arelis.tools.web import WebFetchTool
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch
from tests.test_round_scratch import _augment
from tests.test_web_fetch_thin import _SHORT_PAGE

ROOT = Path(__file__).resolve().parents[1]
_CHALLENGE_URL = "https://example.test/gated"
_CHALLENGE_HTML = """
<html><head><title>Just a moment...</title></head>
<body>
  <h1>Attention Required</h1>
  <p>Checking your browser before you access example.test.</p>
  <div id="cf-browser-verification">Verify you are human. Cloudflare 403 Forbidden.</div>
</body></html>
"""
_COOKIE_ONLY = """
<html><body>
  <p>Please enable cookies to continue reading this article.</p>
</body></html>
"""
_NORMAL_PAGE = (
    "<html><head><title>Tides</title></head><body><p>The spring tide "
    "arrives at 06:14 tomorrow, about an hour later than today.</p>"
    "</body></html>"
)
_HAND_OFF_FILES = (
    ROOT / "arelis" / "core" / "evidence.py",
    ROOT / "arelis" / "tools" / "scrape.py",
    ROOT / "arelis" / "tools" / "web.py",
    ROOT / "arelis" / "core" / "failure_copy.py",
    ROOT / "arelis" / "core" / "turn_goal.py",
)
_FORBIDDEN_IMPORTS = frozenset(
    {
        "captcha",
        "2captcha",
        "twocaptcha",
        "anticaptcha",
        "capsolver",
        "deathbycaptcha",
        "pytesseract",
        "easyocr",
        "paddleocr",
        "tesseract",
    }
)


class _Response:
    def __init__(
        self,
        body: str,
        *,
        ctype: str = "text/html",
        status: int = 200,
        url: str = _CHALLENGE_URL,
    ) -> None:
        self.status_code = status
        self.text = body
        self.url = url
        self.headers = {"content-type": ctype}

    def raise_for_status(self) -> None:
        if self.status_code < 400:
            return
        import httpx

        request = httpx.Request("GET", str(self.url))
        raise httpx.HTTPStatusError(
            f"Client error {self.status_code}",
            request=request,
            response=self,  # type: ignore[arg-type]
        )


def _install_web(monkeypatch: pytest.MonkeyPatch, body: str, *, status: int = 200) -> list[str]:
    hits: list[str] = []
    import arelis.tools.web as web

    async def _fake_request(*args: Any, **kwargs: Any) -> _Response:
        url = str(args[2] if len(args) > 2 else kwargs.get("url") or "")
        hits.append(url)
        return _Response(body, status=status, url=url)

    monkeypatch.setattr(web, "guarded_request", _fake_request)
    return hits


def _install_scrape(monkeypatch: pytest.MonkeyPatch, body: str, *, status: int = 200) -> list[str]:
    hits: list[str] = []
    import arelis.tools.scrape as scrape

    async def _fake_get(*args: Any, **kwargs: Any) -> _Response:
        url = str(args[1] if len(args) > 1 else kwargs.get("url") or "")
        hits.append(url)
        return _Response(body, status=status, url=url)

    monkeypatch.setattr(scrape, "guarded_get", _fake_get)
    return hits


def test_cloudflare_403_copy_is_a_challenge_not_a_bare_403() -> None:
    blob = "HTTP 403 Forbidden. Just a moment. Checking your browser. Verify you are human."
    assert classify_fetch_failure(blob) == "fail:challenge"


def test_a_bare_403_is_still_http_403() -> None:
    assert classify_fetch_failure("HTTP 403 Forbidden") == "fail:http_403"


def test_cookie_banner_copy_is_not_a_human_check() -> None:
    assert classify_fetch_failure("Please enable cookies to continue.") != "fail:challenge"


@pytest.mark.asyncio
async def test_web_fetch_challenge_offers_chrome_and_does_not_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hits = _install_web(monkeypatch, _CHALLENGE_HTML, status=403)
    tool = WebFetchTool("arelis-test/1.0", offer_browser=True)
    result = await tool.run(url=_CHALLENGE_URL)
    assert result.ok is False
    assert result.data.get("fail_class") == "fail:challenge"
    assert "[fail:challenge]" in result.output
    assert "human check" in result.output.lower()
    assert "Chrome" in result.output
    assert f"browser(action=open, url={_CHALLENGE_URL})" in result.output
    assert hits == [_CHALLENGE_URL]


@pytest.mark.asyncio
async def test_web_fetch_unattended_skips_without_an_offer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hits = _install_web(monkeypatch, _CHALLENGE_HTML, status=403)
    tool = WebFetchTool("arelis-test/1.0", offer_browser=False)
    result = await tool.run(url=_CHALLENGE_URL)
    assert result.ok is False
    assert result.data.get("fail_class") == "fail:challenge"
    assert "human check" in result.output.lower()
    assert "skipped" in result.output.lower()
    assert "Chrome" not in result.output
    assert "browser(action=open" not in result.output
    assert hits == [_CHALLENGE_URL]


@pytest.mark.asyncio
async def test_scrape_challenge_offers_chrome_and_does_not_follow_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hits = _install_scrape(monkeypatch, _CHALLENGE_HTML, status=403)
    tool = ScrapeTool("arelis-test/1.0", offer_browser=True)
    result = await tool.run(url=_CHALLENGE_URL)
    assert result.ok is False
    assert result.data.get("fail_class") == "fail:challenge"
    assert "[fail:challenge]" in result.output
    assert "human check" in result.output.lower()
    assert "Chrome" in result.output
    assert f"browser(action=open, url={_CHALLENGE_URL})" in result.output
    assert hits == [_CHALLENGE_URL]


@pytest.mark.asyncio
async def test_scrape_unattended_skips_without_an_offer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_scrape(monkeypatch, _CHALLENGE_HTML, status=403)
    tool = ScrapeTool("arelis-test/1.0", offer_browser=False)
    result = await tool.run(url=_CHALLENGE_URL)
    assert result.ok is False
    assert "skipped" in result.output.lower()
    assert "Chrome" not in result.output


@pytest.mark.asyncio
async def test_a_short_page_is_not_a_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_web(monkeypatch, _SHORT_PAGE, status=200)
    result = await WebFetchTool("arelis-test/1.0").run(url="https://example.test/page")
    assert "fail:challenge" not in result.output
    assert "human check" not in result.output.lower()
    assert "The spring tide arrives at 06:14." in result.output


@pytest.mark.asyncio
async def test_a_normal_page_is_not_a_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_web(monkeypatch, _NORMAL_PAGE, status=200)
    result = await WebFetchTool("arelis-test/1.0").run(url="https://example.test/page")
    assert result.ok is True
    assert "fail:challenge" not in result.output
    assert "Tides" in result.output


@pytest.mark.asyncio
async def test_cookie_html_is_not_offered_as_a_human_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_web(monkeypatch, _COOKIE_ONLY, status=200)
    result = await WebFetchTool("arelis-test/1.0", offer_browser=True).run(url=_CHALLENGE_URL)
    assert result.data.get("fail_class") != "fail:challenge"
    assert "Chrome" not in result.output


@pytest.mark.asyncio
async def test_a_challenge_failure_widens_browser_and_skips_the_same_url() -> None:
    loop = _augment(_FakeLoop())
    seen: list[str] = []

    async def _challenge(name: str, **kwargs: Any) -> Any:
        seen.append(str(kwargs.get("url") or ""))
        return SimpleNamespace(
            ok=False,
            output=(
                "[fail:challenge] The site wants a human check (captcha or "
                f"sign-in). Offer to open it in her Chrome with "
                f"browser(action=open, url={_CHALLENGE_URL})."
            ),
            data={"fail_class": "fail:challenge", "url": _CHALLENGE_URL},
        )

    loop.tools.call = _challenge
    ctx = _ctx()
    ctx.tool_names = {"scrape"}
    r = _scratch(
        calls=[
            ("scrape", {"url": _CHALLENGE_URL}),
            ("scrape", {"url": _CHALLENGE_URL}),
        ],
        content="",
        streamed="",
        tool_names=ctx.tool_names,
        available={"scrape"},
        visible={"scrape"},
        available_all={"scrape", "browser"},
    )

    assert await dispatch_calls(loop, ctx, r, 1) is False
    assert seen == [_CHALLENGE_URL]
    assert "browser" in r.visible
    assert "browser" in r.tool_names


def test_hand_off_modules_do_not_import_a_solver_or_ocr() -> None:
    found: list[str] = []
    for path in _HAND_OFF_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                key = name.lower()
                if key in _FORBIDDEN_IMPORTS or "captcha" in key:
                    found.append(f"{path.name}:{name}")
    assert found == []


_LONG_ARTICLE = (
    "<html><body><h1>How sites tell people from bots</h1>"
    + "<p>A captcha asks you to prove you are human. Just a moment, the site says "
    "while it checks. Access denied pages are another sign.</p>" * 60 + "</body></html>"
)


@pytest.mark.asyncio
async def test_a_long_article_about_captchas_is_not_a_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_web(monkeypatch, _LONG_ARTICLE, status=200)
    result = await WebFetchTool("arelis-test/1.0", offer_browser=True).run(
        url="https://example.test/article"
    )
    assert result.data.get("fail_class") != "fail:challenge"
    assert "Chrome" not in result.output


def test_wall_wording_needs_an_error_status_or_a_thin_page() -> None:
    from arelis.core.evidence import looks_like_challenge_page

    assert looks_like_challenge_page(_CHALLENGE_HTML) is True
    assert looks_like_challenge_page(_LONG_ARTICLE, 200) is False
    assert looks_like_challenge_page(_LONG_ARTICLE, 403) is True

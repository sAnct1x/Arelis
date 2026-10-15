"""scrape / web_fetch stop on a captcha or login wall and hand it to her.

No network. The challenge HTML is a stub. A short real page from the
thin-page tests must not trip this. Nothing here solves a wall.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from arelis.core.turn_dispatch import dispatch_calls
from arelis.tools.scrape import ScrapeTool
from arelis.tools.web import WebFetchTool
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch
from tests.test_round_scratch import _augment

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


_LONG_ARTICLE = (
    "<html><body><h1>How sites tell people from bots</h1>"
    + "<p>A captcha asks you to prove you are human. Just a moment, the site says "
    "while it checks. Access denied pages are another sign.</p>" * 60 + "</body></html>"
)



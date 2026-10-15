"""Wait-for URL / text / heading — poll the tab, no CSS, no networkidle."""

from __future__ import annotations

import asyncio

from arelis.browser.session import BrowserSession
from arelis.browser.wait_for import url_needle_hit


def test_url_needle_matches_path_and_host() -> None:
    assert url_needle_hit("https://x.com/home", "/home")
    assert url_needle_hit("https://x.com/home", "https://x.com/home")
    assert url_needle_hit("https://x.com/home", "x.com/home")
    assert not url_needle_hit("https://x.com/home", "/login")


def test_wait_url_hits_when_already_there() -> None:
    session = BrowserSession.fake()

    async def _run() -> None:
        await session.ensure("chrome")
        await session.open_url("https://x.com/home")
        result = await session.wait(0.2, url="/home")
        assert result.ok
        assert result.data.get("hit") is True
        assert "Wait hit" in result.output
        assert "/home" in str(result.data.get("url") or "")

    asyncio.run(_run())


def test_wait_text_timeout_stays_ok() -> None:
    session = BrowserSession.fake()

    async def _run() -> None:
        await session.ensure("chrome")
        await session.open_url("https://x.com/home")
        result = await session.wait(0.2, text="this string is not on the page")
        assert result.ok
        assert result.data.get("hit") is False
        assert "timeout" in result.output.lower()

    asyncio.run(_run())


def test_wait_heading_hits_title() -> None:
    session = BrowserSession.fake()

    async def _run() -> None:
        await session.ensure("chrome")
        await session.open_url("https://x.com/home")
        session._driver.heading = "Home"  # type: ignore[attr-defined]
        result = await session.wait(0.2, heading="Home")
        assert result.ok
        assert result.data.get("hit") is True

    asyncio.run(_run())



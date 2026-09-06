"""Wait-for URL / text / heading — poll the tab, no CSS, no networkidle."""

from __future__ import annotations

import asyncio

from arelis.browser.session import BrowserSession
from arelis.browser.wait_for import page_needles_hit, url_needle_hit
from arelis.tools.browser_tool import BrowserTool


def test_url_needle_matches_path_and_host() -> None:
    assert url_needle_hit("https://x.com/home", "/home")
    assert url_needle_hit("https://x.com/home", "https://x.com/home")
    assert url_needle_hit("https://x.com/home", "x.com/home")
    assert not url_needle_hit("https://x.com/home", "/login")


def test_page_needles_need_every_given_field() -> None:
    assert page_needles_hit(
        landed_url="https://x.com/home",
        title="Home",
        heading="Home",
        page_text="For you",
        want_url="/home",
    )
    assert not page_needles_hit(
        landed_url="https://x.com/home",
        title="Home",
        heading="Home",
        page_text="For you",
        want_url="/home",
        want_text="Sign in",
    )


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


def test_wait_url_applies_spa_bounce_then_hits() -> None:
    session = BrowserSession.fake()
    session._driver.pending_wait_url = "https://x.com/home"  # type: ignore[attr-defined]

    async def _run() -> None:
        await session.ensure("chrome")
        await session.open_url("https://example.com")
        session._driver.url = "https://x.com/i/flow/login"  # type: ignore[attr-defined]
        assert "login" in session._driver.url  # type: ignore[attr-defined]
        result = await session.wait(2, url="/home")
        assert result.ok
        assert result.data.get("hit") is True
        assert result.data.get("url") == "https://x.com/home"

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


def test_tool_wait_for_url_appends_snapshot() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://x.com/home")
        result = await tool.run(action="wait", url="/home")
        assert result.ok
        assert "Wait hit" in result.output
        assert "elements:" in result.output.lower() or "[e1]" in result.output
        assert result.data.get("snapshot") is True

    asyncio.run(_run())


def test_sleep_wait_skips_snapshot() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://x.com/home")
        result = await tool.run(action="wait", seconds=0.2)
        assert result.ok
        assert result.output.startswith("Waited")
        assert result.data.get("snapshot") is None

    asyncio.run(_run())

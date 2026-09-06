"""Live tab watch — arm in the background, Stop cancels, notify on hit."""

from __future__ import annotations

import asyncio

from arelis.browser import live
from arelis.browser.hold import format_drive_status, set_paused
from arelis.browser.session import BrowserSession
from arelis.tools.browser_tool import BrowserTool


def setup_function() -> None:
    set_paused(False)
    live.mark_watching(False)
    live.set_hit_sink(None)
    live.bind_session(None)


def teardown_function() -> None:
    live.cancel()
    live.set_hit_sink(None)
    live.bind_session(None)
    set_paused(False)


def test_drive_status_is_watching() -> None:
    assert format_drive_status("watch", {"url": "/home"}) == "Watching"


def test_watch_hits_url_already_there() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://x.com/home")
        result = await tool.run(action="watch", url="/home")
        assert result.ok
        assert result.data.get("hit") is True
        assert result.data.get("watch_hit") is True
        assert result.data.get("watching") is not True
        assert "Watch hit" in result.output
        assert live.is_watching() is False

    asyncio.run(_run())


def test_watch_arms_then_hits(monkeypatch) -> None:
    monkeypatch.setattr("arelis.browser.wait_for.WATCH_POLL_S", 0.05)
    session = BrowserSession.fake()
    hits: list[dict] = []
    live.set_hit_sink(hits.append)

    async def _run() -> None:
        await session.ensure("chrome")
        await session.open_url("https://example.com")
        result = await session.watch(url="/home")
        assert result.ok
        assert result.data.get("watching") is True
        assert result.data.get("hit") is False
        assert live.is_watching() is True
        assert "Watching for" in result.output
        session._driver.url = "https://x.com/home"  # type: ignore[attr-defined]
        session._driver.title = "Home"  # type: ignore[attr-defined]
        done = await session.await_watch(timeout_s=2.0)
        assert done is not None
        assert done.data.get("hit") is True
        assert done.data.get("watch_hit") is True
        assert live.is_watching() is False
        assert hits
        assert hits[0].get("watch_hit") is True

    asyncio.run(_run())


def test_watch_stop_cancels_after_arm() -> None:
    session = BrowserSession.fake()

    async def _run() -> None:
        await session.ensure("chrome")
        await session.open_url("https://example.com")
        result = await session.watch(text="this string is not on the page")
        assert result.ok
        assert result.data.get("watching") is True
        assert live.is_watching() is True
        session.cancel_watch()
        done = await session.await_watch(timeout_s=2.0)
        assert done is not None
        assert done.data.get("cancelled") is True
        assert done.data.get("hit") is False
        assert live.is_watching() is False

    asyncio.run(_run())


def test_live_cancel_stops_bound_watch() -> None:
    session = BrowserSession.fake()

    async def _run() -> None:
        await session.ensure("chrome")
        await session.open_url("https://example.com")
        result = await session.watch(url="/later")
        assert result.data.get("watching") is True
        live.cancel()
        done = await session.await_watch(timeout_s=2.0)
        assert done is not None
        assert done.data.get("cancelled") is True
        assert live.is_watching() is False

    asyncio.run(_run())


def test_watch_on_checkout_is_not_a_pay_wall() -> None:
    session = BrowserSession.fake()

    async def _run() -> None:
        await session.ensure("chrome")
        await session.open_url("https://shop.example/checkout")
        result = await session.watch(text="order confirmed")
        assert result.ok
        assert result.data.get("watching") is True
        assert result.data.get("wall") != "pay"
        session.cancel_watch()

    asyncio.run(_run())


def test_watch_needs_a_needle() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://example.com")
        result = await tool.run(action="watch")
        assert not result.ok
        assert "url, text, or heading" in result.output

    asyncio.run(_run())

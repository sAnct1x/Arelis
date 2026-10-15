"""Browser walls, your-turn pauses, operator mouse, and click timeout."""

from __future__ import annotations

import asyncio

from arelis.browser.session import BrowserSession


def test_x_login_redirect_to_home_is_not_a_wall() -> None:
    from arelis.browser.hold import is_paused, set_paused

    session = BrowserSession.fake()
    session._driver.redirects["https://x.com/login"] = "https://x.com/home"  # type: ignore[attr-defined]
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            opened = await session.open_url("https://x.com/login")
            assert opened.ok
            assert opened.data.get("url") == "https://x.com/home"
            assert opened.data.get("wall") is None
            assert "Already signed in" in opened.output
            assert not is_paused()

        asyncio.run(_run())
    finally:
        set_paused(False)


def test_mouse_does_not_steal_her_window() -> None:
    """Her Chrome stays hers during a drive. Stop / Pause is the strip."""
    from arelis.browser.hold import set_paused

    session = BrowserSession.fake()
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            session._driver.user_took_over = True  # type: ignore[attr-defined]
            result = await session.click("e1")
            assert result.ok
            assert result.data.get("wall") != "hands"
            assert "e1" in getattr(session._driver, "clicked", [])

        asyncio.run(_run())
    finally:
        set_paused(False)


def test_click_timeout_is_not_cdp_death() -> None:
    from arelis.browser.actions import _is_cdp_dead

    assert not _is_cdp_dead(TimeoutError("Timeout 10000ms exceeded."))
    assert not _is_cdp_dead(RuntimeError("element is not stable"))
    assert _is_cdp_dead(RuntimeError("Target closed"))
    assert _is_cdp_dead(RuntimeError("Browser has been closed"))


def test_your_turn_refuses_pay_click() -> None:
    from arelis.browser.hold import set_paused

    session = BrowserSession.fake()
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            result = await session.click("e5")
            assert not result.ok
            assert result.data.get("code") == "YOUR_TURN"
            assert result.data.get("wall") == "pay"
            assert "e5" not in getattr(session._driver, "clicked", [])

        asyncio.run(_run())
    finally:
        set_paused(False)



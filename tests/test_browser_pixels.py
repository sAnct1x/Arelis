"""Pointer actions on snapshot refs; x,y gated on screenshot+vision."""

from __future__ import annotations

import asyncio

from arelis.browser.pixels import parse_xy, xy_refused
from arelis.browser.session import BrowserSession
from arelis.tools.browser_tool import BrowserTool


def test_parse_xy() -> None:
    assert parse_xy({}) == (None, None)
    assert parse_xy({"x": 10, "y": 20}) == (10.0, 20.0)
    assert parse_xy({"x": "8", "y": "4"}) == (8.0, 4.0)


def test_hover_and_dblclick_on_ref() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://example.com")
        hovered = await tool.run(action="hover", ref="e1")
        assert hovered.ok
        assert "e1" in session._driver.hovered  # type: ignore[attr-defined]
        assert "e1" in session._driver.glowed  # type: ignore[attr-defined]
        doubled = await tool.run(action="dblclick", ref="e6")
        assert doubled.ok
        assert "e6" in session._driver.dblclicked  # type: ignore[attr-defined]
        right = await tool.run(action="right_click", ref="e1")
        assert right.ok
        dragged = await tool.run(action="drag", ref="e1", to="e6")
        assert dragged.ok
        assert ("e1", "e6") in session._driver.dragged  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_xy_refused_until_pixel_ok() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://example.com")
        refused = await tool.run(action="hover", x=40, y=80)
        assert not refused.ok
        assert refused.data.get("code") == "PIXEL_GATE"
        assert xy_refused() in refused.output
        tool.pixel_ok = True
        ok = await tool.run(action="hover", x=40, y=80)
        assert ok.ok
        assert "xy:40,80" in session._driver.hovered  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_dblclick_pay_wall() -> None:
    from arelis.browser.hold import set_paused

    session = BrowserSession.fake()
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            result = await session.dblclick("e5")
            assert not result.ok
            assert result.data.get("wall") == "pay"

        asyncio.run(_run())
    finally:
        set_paused(False)

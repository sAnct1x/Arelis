"""Tabs as places — list index|title|url, select by title substring."""

from __future__ import annotations

import asyncio

from arelis.browser.places import format_tab_list, parse_tab_select, pick_tab
from arelis.browser.session import BrowserSession
from arelis.tools.browser_tool import BrowserTool


def test_parse_tab_select_splits_index_and_title() -> None:
    assert parse_tab_select(None) == (None, "")
    assert parse_tab_select(2) == (2, "")
    assert parse_tab_select("0") == (0, "")
    assert parse_tab_select("Gmail") == (None, "Gmail")
    assert parse_tab_select("  Inbox  ") == (None, "Inbox")


def test_format_tab_list_is_index_title_url() -> None:
    text = format_tab_list(
        [
            {"index": 0, "title": "Home / X", "url": "https://x.com/home"},
            {"index": 1, "title": "Inbox", "url": "https://mail.google.com"},
        ],
        active=1,
    )
    assert "0|Home / X|https://x.com/home" in text
    assert "1|Inbox|https://mail.google.com *" in text


def test_pick_tab_title_is_substring_not_url() -> None:
    rows = [
        {"index": 0, "title": "Home / X", "url": "https://x.com/home"},
        {"index": 1, "title": "Inbox - Gmail", "url": "https://mail.google.com"},
    ]
    assert pick_tab(rows, title="gmail") == (1, "")
    assert pick_tab(rows, index=0) == (0, "")
    idx, err = pick_tab(rows, title="https://mail")
    assert idx is None
    assert "No tab matching" in err


def test_tabs_list_and_select_by_title() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://x.com/home")
        session._driver.title = "Home / X"  # type: ignore[attr-defined]
        session._driver._sync_active_tab()  # type: ignore[attr-defined]
        opened = await tool.run(
            action="tabs", tab="new", url="https://mail.google.com"
        )
        assert opened.ok
        session._driver.title = "Inbox - Gmail"  # type: ignore[attr-defined]
        session._driver._sync_active_tab()  # type: ignore[attr-defined]
        listed = await tool.run(action="tabs")
        assert listed.ok
        assert "0|Home / X|https://x.com/home" in listed.output
        assert "1|Inbox - Gmail|https://mail.google.com" in listed.output
        switched = await tool.run(action="tabs", select="Home")
        assert switched.ok
        assert switched.data.get("active") == 0
        assert "https://x.com/home" in str(switched.data.get("url") or "")
        by_index = await tool.run(action="tabs", select="1")
        assert by_index.ok
        assert by_index.data.get("active") == 1

    asyncio.run(_run())


def test_tabs_refuse_close_by_title() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://x.com/home")
        session._driver.title = "Home / X"  # type: ignore[attr-defined]
        session._driver._sync_active_tab()  # type: ignore[attr-defined]
        await tool.run(action="tabs", tab="new", url="https://mail.google.com")
        session._driver.title = "Inbox - Gmail"  # type: ignore[attr-defined]
        session._driver._sync_active_tab()  # type: ignore[attr-defined]
        refused = await tool.run(action="tabs", tab="close", select="Gmail")
        assert not refused.ok
        assert refused.data.get("code") == "CLOSE_BY_TITLE"
        assert "close-by-title" in refused.output.lower()
        still = await tool.run(action="tabs")
        assert "Inbox - Gmail" in still.output
        assert "Home / X" in still.output

    asyncio.run(_run())


def test_tabs_ambiguous_title() -> None:
    session = BrowserSession.fake()

    async def _run() -> None:
        await session.ensure("chrome")
        await session.open_url("https://mail.google.com")
        session._driver.title = "Inbox - Gmail"  # type: ignore[attr-defined]
        session._driver._sync_active_tab()  # type: ignore[attr-defined]
        await session.tabs(op="new", url="https://mail.google.com/u/1")
        session._driver.title = "Work - Gmail"  # type: ignore[attr-defined]
        session._driver._sync_active_tab()  # type: ignore[attr-defined]
        result = await session.tabs(select="Gmail")
        assert not result.ok
        assert "Ambiguous" in result.output

    asyncio.run(_run())

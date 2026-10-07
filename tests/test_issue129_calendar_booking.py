"""Calendar and booking misfires from the checklist.

The ask strings are the ones a person actually typed. Nothing in them names
a tool. Dates are pinned to a Wednesday so next Friday is a real day.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

from arelis.browser.reserve import normalize_date, reserve_url
from arelis.browser.session import BrowserSession
from arelis.core.failure_copy import chat_followup_from_tool
from arelis.tools.agenda import AgendaTool
from arelis.tools.base import ToolResult
from arelis.tools.browser_tool import BrowserTool
from arelis.tools.policy import describe_call

_PLACE = "The Maple Room"


def _next_friday(today: date | None = None) -> str:
    """The upcoming Friday, or a week out when today is already Friday."""
    now = today or date.today()
    ahead = (4 - now.weekday()) % 7
    if ahead == 0:
        ahead = 7
    return (now + timedelta(days=ahead)).isoformat()


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


async def test_no_calendar_today_has_no_path(tmp_path) -> None:
    missing = tmp_path / "absent.ics"
    tool = AgendaTool({"tools": {"briefing": {"calendar_path": str(missing)}}})
    result = await tool.run(action="today")
    assert result.ok
    follow = chat_followup_from_tool(
        "agenda",
        result.output,
        ask="what's on my calendar today?",
    )
    for line in (result.output, follow):
        assert "Nothing on your calendar today." in line
        assert "Connect a calendar in the calendar tile to see events." in line
        assert "calendar.ics" not in line
        assert str(missing) not in line
        assert "\\" not in line
        assert ":\\" not in line
    assert result.data.get("missing") is True


def test_next_friday_at_seven_is_on_the_card_and_in_the_link() -> None:
    url = reserve_url(
        _PLACE,
        site="opentable",
        party=2,
        date="next Friday",
        time="7pm",
    )
    card = describe_call(
        "browser",
        {
            "action": "reserve",
            "place": _PLACE,
            "site": "opentable",
            "party": 2,
            "date": "next Friday",
            "time": "7pm",
        },
    )
    friday = _next_friday()
    stamp = _query(url).get("dateTime", [""])[0]
    assert stamp.startswith(f"{friday}T19:00")
    assert f"Date: {friday}" in card
    assert "Time: 19:00" in card
    assert "Opens OpenTable." in card
    assert "or Resy" not in card
    assert friday in card


def test_next_friday_from_a_wednesday_is_the_ninth() -> None:
    assert normalize_date("next Friday", today=date(2026, 10, 7)) == "2026-10-09"


def test_a_date_that_cannot_be_read_asks_instead_of_dropping_it() -> None:
    url = reserve_url(_PLACE, date="sometime", time="7pm")
    card = describe_call(
        "browser",
        {
            "action": "reserve",
            "place": _PLACE,
            "date": "sometime",
            "time": "7pm",
        },
    )
    assert "dateTime" not in _query(url)
    assert "I need a real date" in card
    assert "Date: sometime" not in card
    assert "Time: 19:00" in card


def test_the_card_names_the_site_that_will_open() -> None:
    card = describe_call(
        "browser",
        {"action": "reserve", "place": _PLACE, "site": "resy", "party": 2},
    )
    assert "Opens Resy." in card
    assert "OpenTable" not in card
    assert "or Resy" not in card


def test_a_group_over_twenty_says_the_cap() -> None:
    note = "Online booking takes up to 20. For a bigger group, call the restaurant."
    url = reserve_url(_PLACE, site="opentable", party=30)
    card = describe_call(
        "browser",
        {"action": "reserve", "place": _PLACE, "site": "opentable", "party": 30},
    )
    assert _query(url)["covers"] == ["20"]
    assert "Party: 20" in card
    assert note in card


def test_a_group_of_four_does_not_mention_the_cap() -> None:
    card = describe_call(
        "browser",
        {"action": "reserve", "place": _PLACE, "party": 4},
    )
    assert "Party: 4" in card
    assert "takes up to 20" not in card


def test_the_opened_link_keeps_next_friday_and_seven() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)
    captured: dict[str, str] = {}

    async def _stub_open(
        action: str,
        target: str,
        *,
        browser: str,
        private: bool,
        already_ensured: bool = False,
        prefix: str = "",
    ) -> ToolResult:
        del action, browser, private, already_ensured, prefix
        captured["url"] = target
        return ToolResult(ok=True, output=f"Opened {target}", data={"url": target})

    tool._open_or_navigate = _stub_open  # type: ignore[method-assign]

    result = asyncio.run(
        tool.run(
            action="reserve",
            place=_PLACE,
            date="next Friday",
            time="7pm",
            party=2,
        )
    )
    assert result.ok, result.output
    friday = _next_friday()
    stamp = _query(captured["url"]).get("dateTime", [""])[0]
    assert stamp.startswith(f"{friday}T19:00")
    assert result.data.get("date") == friday
    assert result.data.get("time") == "19:00"

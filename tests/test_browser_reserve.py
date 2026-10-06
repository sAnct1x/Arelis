"""normalize_party / resolve_party / reserve_url party size, confirm card, tool call."""

from __future__ import annotations

import asyncio

import pytest

from arelis.browser.reserve import (
    normalize_date,
    normalize_party,
    normalize_reserve_site,
    normalize_time,
    reserve_url,
    resolve_party,
)
from arelis.browser.session import BrowserSession
from arelis.tools.base import ToolResult
from arelis.tools.browser_tool import BrowserTool
from arelis.tools.policy import describe_call


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 1),
        ("0", 1),
        (0.0, 1),
        (None, 2),
        ("", 2),
        ("  ", 2),
        ("abc", 2),
        (1, 1),
        (3, 3),
        ("party of 4", 4),
        (20, 20),
        (21, 20),
        (99, 20),
    ],
)
def test_normalize_party_table(raw: object, expected: int) -> None:
    assert normalize_party(raw) == expected


def test_normalize_party_zero_int_matches_zero_string() -> None:
    assert normalize_party(0) == normalize_party("0") == 1


def test_reserve_url_party_zero_opentable() -> None:
    url = reserve_url("Some Place", site="opentable", party=0)
    assert "covers=1" in url


def test_reserve_url_party_zero_resy() -> None:
    url = reserve_url("Some Place", site="resy", party=0)
    assert "seats=1" in url


def test_reserve_url_party_zero_google() -> None:
    url = reserve_url("Some Place", site="google", party=0)
    assert "party+of+1" in url


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        ((0, 5), 1),
        ((None, 5), 5),
        (("", None), 2),
        (("", 5), 5),
        ((None, None), 2),
        ((3, None), 3),
        (("0", 4), 1),
    ],
)
def test_resolve_party(candidates: tuple[object, ...], expected: int) -> None:
    assert resolve_party(*candidates) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("opentable", "opentable"),
        ("ot", "opentable"),
        ("resy", "resy"),
        ("google", "google"),
        ("maps", "google"),
        ("", "opentable"),
        ("unknown", "opentable"),
    ],
)
def test_normalize_reserve_site_table(raw: str, expected: str) -> None:
    assert normalize_reserve_site(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-05", "2026-10-05"),
        ("10/5/2026", "2026-10-05"),
        ("10-5-2026", "2026-10-05"),
        ("", None),
        ("not-a-date", None),
    ],
)
def test_normalize_date_table(raw: str, expected: str | None) -> None:
    assert normalize_date(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("19:00", "19:00"),
        ("7pm", "19:00"),
        ("7:30 PM", "19:30"),
        ("", None),
        ("lunch", None),
    ],
)
def test_normalize_time_table(raw: str, expected: str | None) -> None:
    assert normalize_time(raw) == expected


def test_reserve_url_date_time_opentable() -> None:
    url = reserve_url(
        "Carbone",
        site="opentable",
        party=2,
        date="2026-10-05",
        time="19:00",
    )
    assert "opentable.com" in url
    assert "term=Carbone" in url
    assert "covers=2" in url
    assert "dateTime=2026-10-05T19%3A00" in url or "dateTime=2026-10-05T19:00" in url


@pytest.mark.parametrize(
    ("args", "party_line"),
    [
        ({"party": 0}, "Party: 1"),
        ({}, "Party: 2"),
        ({"party": "", "covers": 5}, "Party: 5"),
        ({"party": 0, "covers": 5}, "Party: 1"),
        ({"party": 4}, "Party: 4"),
        ({"party": 99}, "Party: 20"),
    ],
)
def test_reserve_confirm_card_shows_resolved_party(
    args: dict[str, object], party_line: str
) -> None:
    payload = {"action": "reserve", "place": "Carbone", **args}
    text = describe_call("browser", payload)
    lines = text.splitlines()
    assert "Place: Carbone" in lines
    assert [line for line in lines if line.startswith("Party:")] == [party_line]


def _run_reserve(**kwargs: object) -> ToolResult:
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

    async def _run() -> ToolResult:
        return await tool.run(action="reserve", place="Carbone", site="opentable", **kwargs)

    result = asyncio.run(_run())
    assert result.ok
    assert "url" in captured
    assert result.data.get("reserve_url") == captured["url"]
    return result


def test_browser_reserve_party_zero_opens_covers_one() -> None:
    result = _run_reserve(party=0)
    url = str(result.data.get("reserve_url") or "")
    assert "covers=1" in url
    assert "party=1" in (result.output or "")
    assert result.data.get("party") == 1


def test_browser_reserve_party_zero_covers_five_still_one() -> None:
    result = _run_reserve(party=0, covers=5)
    url = str(result.data.get("reserve_url") or "")
    assert "covers=1" in url
    assert result.data.get("party") == 1


def test_browser_reserve_blank_party_uses_covers() -> None:
    result = _run_reserve(party="", covers=5)
    url = str(result.data.get("reserve_url") or "")
    assert "covers=5" in url
    assert result.data.get("party") == 5


def test_browser_reserve_nothing_given_defaults_two() -> None:
    result = _run_reserve()
    url = str(result.data.get("reserve_url") or "")
    assert "covers=2" in url
    assert result.data.get("party") == 2

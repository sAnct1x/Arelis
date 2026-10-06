"""normalize_party / resolve_party / reserve_url party size, confirm card, tool call."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import parse_qs, urlsplit

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


def _query_int(url: str, key: str) -> int:
    """The exact value of one query parameter, so 1 never matches 10 to 19."""
    values = parse_qs(urlsplit(url).query).get(key, [])
    assert len(values) == 1, (key, url)
    return int(values[0])


def _card_party(text: str) -> int:
    """The number on the card's single Party line."""
    hits = [line for line in text.splitlines() if line.startswith("Party:")]
    assert len(hits) == 1, text
    return int(hits[0].removeprefix("Party:").strip())


def _filled_party(output: str) -> int:
    """The party=N the reply says it filled in, matched as a whole number."""
    hits = re.findall(r"(?<![\w])party=(\d+)(?!\d)", output or "")
    assert len(hits) == 1, output
    return int(hits[0])


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
    assert _query_int(url, "covers") == 1


def test_reserve_url_party_zero_resy() -> None:
    url = reserve_url("Some Place", site="resy", party=0)
    assert _query_int(url, "seats") == 1


def test_reserve_url_party_zero_google() -> None:
    url = reserve_url("Some Place", site="google", party=0)
    query = parse_qs(urlsplit(url).query)["q"][0]
    assert query.endswith("party of 1")


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
    assert _query_int(url, "covers") == 2
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


def _run_reserve(site: str = "opentable", **kwargs: object) -> ToolResult:
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
        return await tool.run(action="reserve", place="Carbone", site=site, **kwargs)

    result = asyncio.run(_run())
    assert result.ok
    assert "url" in captured
    assert result.data.get("reserve_url") == captured["url"]
    return result


def test_browser_reserve_party_zero_opens_covers_one() -> None:
    result = _run_reserve(party=0)
    url = str(result.data.get("reserve_url") or "")
    assert _query_int(url, "covers") == 1
    assert _filled_party(result.output) == 1
    assert result.data.get("party") == 1


def test_browser_reserve_party_zero_covers_five_still_one() -> None:
    result = _run_reserve(party=0, covers=5)
    url = str(result.data.get("reserve_url") or "")
    assert _query_int(url, "covers") == 1
    assert result.data.get("party") == 1


def test_browser_reserve_blank_party_uses_covers() -> None:
    result = _run_reserve(party="", covers=5)
    url = str(result.data.get("reserve_url") or "")
    assert _query_int(url, "covers") == 5
    assert result.data.get("party") == 5


def test_browser_reserve_nothing_given_defaults_two() -> None:
    result = _run_reserve()
    url = str(result.data.get("reserve_url") or "")
    assert _query_int(url, "covers") == 2
    assert result.data.get("party") == 2


# The 28 edge inputs from the PR #128 review: the card and the link must agree.
_PARITY_CASES: list[tuple[dict[str, object], int]] = [
    ({"party": 0}, 1),
    ({"party": "0"}, 1),
    ({"party": None}, 2),
    ({"party": ""}, 2),
    ({"party": "   "}, 2),
    ({"party": -3}, 3),
    ({"party": 1}, 1),
    ({"party": 20}, 20),
    ({"party": 21}, 20),
    ({"party": 50}, 20),
    ({"party": 100}, 20),
    ({"party": "3 people"}, 3),
    ({"party": 2.5}, 2),
    ({"party": "2.5"}, 2),
    ({"party": 0.5}, 1),
    ({"party": "twelve"}, 2),
    ({"party": "abc"}, 2),
    ({"party": True}, 2),
    ({"party": "1e3"}, 1),
    ({"party": "-"}, 2),
    ({}, 2),
    ({"party": "", "covers": 5}, 5),
    ({"party": None, "covers": 5}, 5),
    ({"covers": 0}, 1),
    ({"party": "", "covers": 0}, 1),
    ({"party": 4, "covers": 6}, 4),
    ({"party": 0, "covers": 5}, 1),
    ({"covers": 50}, 20),
]


@pytest.mark.parametrize(("site", "key"), [("opentable", "covers"), ("resy", "seats")])
@pytest.mark.parametrize(("args", "expected"), _PARITY_CASES)
def test_card_and_booking_link_agree_on_party_size(
    site: str, key: str, args: dict[str, object], expected: int
) -> None:
    card = describe_call("browser", {"action": "reserve", "place": "Carbone", "site": site, **args})
    result = _run_reserve(site=site, **args)
    link = _query_int(str(result.data.get("reserve_url") or ""), key)
    assert _card_party(card) == link == expected

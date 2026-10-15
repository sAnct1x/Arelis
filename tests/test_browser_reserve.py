"""normalize_party / resolve_party / reserve_url party size, confirm card, tool call."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from arelis.browser.reserve import (
    reserve_url,
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
    [({'party': 0}, 'Party: 1'), ({}, 'Party: 2')],
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


# The 28 edge inputs from the PR #128 review: the card and the link must agree.
_PARITY_CASES: list[tuple[dict[str, object], int]] = [({'party': 0}, 1), ({'party': '0'}, 1)]


@pytest.mark.parametrize(("site", "key"), [("opentable", "covers"), ("resy", "seats")])
@pytest.mark.parametrize(("args", "expected"), _PARITY_CASES)
def test_card_and_booking_link_agree_on_party_size(
    site: str, key: str, args: dict[str, object], expected: int
) -> None:
    card = describe_call("browser", {"action": "reserve", "place": "Carbone", "site": site, **args})
    result = _run_reserve(site=site, **args)
    link = _query_int(str(result.data.get("reserve_url") or ""), key)
    assert _card_party(card) == link == expected

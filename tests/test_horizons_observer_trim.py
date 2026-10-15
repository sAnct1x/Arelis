"""Dated Horizons observer table: RA/Dec columns, rows only, no raw page."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest

from arelis.tools.catalog import CatalogTool

_HEADER = (
    " Date__(UT)__HR:MN     R.A._____(ICRF)_____DEC"
    "            delta      deldot    S-O-T /r    S-T-O"
)
_RA_DEC = "08 15 08.50 +20 51 15.6"
_ROW = f" 2026-Oct-01 00:00     {_RA_DEC}  1.523456  0.120  40.1 /T  12.3"
_PREAMBLE_MARK = "GEOPHYSICAL DATA (updated 2024-Aug-15): Mean radius, km = 3389.92"
_FOOTER_MARK = "4800 Oak Grove Drive, Jet Propulsion Laboratory, Pasadena, CA 91109 USA"
_NOTE = (
    "Ephemeris notes are reference material from the Horizons file. "
    "Calendar dates prior to 1582-Oct-15 are in the Julian calendar. "
)
_FOOT_NOTE = "Solar System Dynamics Group, Horizons On-Line Ephemeris System. "


def _pad(text: str, size: int, note: str) -> str:
    body = text
    while len(body) < size:
        body += note
    return body[:size]


def _observer_blob(
    *,
    preamble_chars: int = 2300,
    rows: list[str] | None = None,
    soe: bool = True,
) -> str:
    stars = "*" * 96
    data = rows if rows is not None else [_ROW]
    parts = [
        _pad(_PREAMBLE_MARK + "\n", preamble_chars, _NOTE),
        stars,
        _HEADER,
        stars,
    ]
    if soe:
        parts.append("$$SOE")
        parts.extend(data)
        parts.append("$$EOE")
    else:
        parts.append("Revised: April 12, 2021. No rows were written for this pass.")
    parts.append(_pad(_FOOTER_MARK + "\n", 5000, _FOOT_NOTE))
    return "\n".join(parts)


def _rows(count: int) -> list[str]:
    return [f" 2026-Oct-01 00:00     {_RA_DEC}  1.5  ROW{index:03d}" for index in range(count)]


def _tool(handler) -> CatalogTool:
    return CatalogTool(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    )


def _quantities(url: str) -> str:
    query = parse_qs(urlparse(unquote(url)).query)
    got = query.get("QUANTITIES") or []
    assert got, url
    return got[0]


@pytest.mark.asyncio
async def test_dated_observer_returns_ra_dec_rows_without_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"result": _observer_blob()})

    result = await _tool(handler).run(
        action="horizons", target="Mars", date="2026-10-01", table="observer"
    )
    assert result.ok, result.output
    assert "R.A._____(ICRF)_____DEC" in result.output
    assert _RA_DEC in result.output
    assert _PREAMBLE_MARK not in result.output
    assert _FOOTER_MARK not in result.output
    assert "$$SOE" not in result.output
    assert "$$EOE" not in result.output
    assert "*" * 8 not in result.output
    assert "[truncated]" not in result.output
    assert result.data["action"] == "horizons"
    assert result.data["table"] == "observer"
    assert result.data["target"] == "499"
    assert result.data["date"] == "2026-10-01"


@pytest.mark.asyncio
async def test_long_preamble_still_returns_the_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"result": _observer_blob(preamble_chars=5000)})

    result = await _tool(handler).run(action="horizons", target="Mars", date="2026-10-01")
    assert result.ok, result.output
    assert _RA_DEC in result.output
    assert "R.A._____(ICRF)_____DEC" in result.output
    assert _PREAMBLE_MARK not in result.output


@pytest.mark.asyncio
async def test_row_cap_keeps_first_48_and_says_how_many_remain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"result": _observer_blob(rows=_rows(100))})

    result = await _tool(handler).run(action="horizons", target="Mars", date="2026-10-01")
    assert result.ok, result.output
    shown = [line for line in result.output.splitlines() if "ROW" in line]
    assert len(shown) == 48
    assert "ROW000" in shown[0]
    assert "ROW047" in shown[-1]
    assert "ROW048" not in result.output
    assert "(52 more rows not shown)" in result.output
    assert "[truncated]" not in result.output


@pytest.mark.asyncio
async def test_missing_soe_is_not_a_table() -> None:
    raw_line = "Revised: April 12, 2021. No rows were written for this pass."

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"result": _observer_blob(soe=False)})

    result = await _tool(handler).run(
        action="horizons", target="Mars", date="2026-10-01", table="observer"
    )
    assert result.ok is False
    assert result.output == ("Horizons sent back no table rows for Mars on 2026-10-01.")
    assert raw_line not in result.output
    assert _PREAMBLE_MARK not in result.output
    assert _FOOTER_MARK not in result.output
    assert "$$SOE" not in result.output
    assert "observer table" not in result.output
    assert result.data["fail_class"] == "fail:parse"
    assert result.data["action"] == "horizons"
    assert result.data["target"] == "499"
    assert result.data["date"] == "2026-10-01"

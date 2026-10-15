"""Horizons Moon distance: name map, query fallback, now/extrema summary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, unquote_plus
from zoneinfo import ZoneInfo

import httpx
import pytest

from arelis.tools.catalog import CatalogTool

_AU_KM = 149_597_870.7

# Hourly rows: now mid-range, later max, then min. delta in AU.
_NOW = datetime(2026, 10, 5, 23, 17, tzinfo=UTC)
_NOW_AU = 0.002498
_FAR_AU = 0.002705  # ~404,681 km
_NEAR_AU = 0.002436  # ~364,386 km
_NY = ZoneInfo("America/New_York")

_OBSERVER_BLOB = f"""
*******************************************************************************
Target body name: Moon (301)
*******************************************************************************
$$SOE
 2026-Oct-05 22:17     {(_NOW_AU - 0.000001):.9f}  -0.0100000000000000
 2026-Oct-05 23:17     {_NOW_AU:.9f}  -0.0100000000000000
 2026-Oct-16 22:00     {(_FAR_AU - 0.000001):.9f}   0.0001000000000000
 2026-Oct-16 23:00     {_FAR_AU:.9f}   0.0001000000000000
 2026-Oct-17 00:00     {(_FAR_AU - 0.000001):.9f}   0.0001000000000000
 2026-Oct-28 17:00     {(_NEAR_AU + 0.000001):.9f}   0.0002000000000000
 2026-Oct-28 18:00     {_NEAR_AU:.9f}   0.0002000000000000
 2026-Oct-28 19:00     {(_NEAR_AU + 0.000001):.9f}   0.0002000000000000
$$EOE
*******************************************************************************
"""

_AMBIGUOUS_BLOB = """
Multiple major-bodies match string "MOON*"
  ID#      Name
    3  Earth-Moon Barycenter
  301  Moon
"""


def _tool(handler) -> CatalogTool:
    return CatalogTool(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    )


def _observer_blob(rows: list[tuple[datetime, float]]) -> str:
    lines = ["$$SOE"]
    for stamp, au in rows:
        lines.append(f" {stamp:%Y-%b-%d %H:%M}     {au:.9f}  0.01")
    lines.append("$$EOE")
    return "\n".join(lines)


def _hourly_from_now_minus_1h(values: list[float]) -> str:
    start = _NOW - timedelta(hours=1)
    rows = [(start + timedelta(hours=i), au) for i, au in enumerate(values)]
    return _observer_blob(rows)


def _tool_blob(blob: str, seen: list[str]) -> CatalogTool:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(unquote_plus(str(request.url)))
        return httpx.Response(200, json={"result": blob})

    return _tool(handler)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    import arelis.tools.catalog as catalog

    monkeypatch.setattr(catalog, "_utc_now", lambda: _NOW)
    monkeypatch.setattr(catalog, "_local_zone", lambda: _NY)


@pytest.mark.asyncio
async def test_moon_distance_now_and_next_extremes_in_local_time() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(unquote(str(request.url)))
        return httpx.Response(200, json={"result": _OBSERVER_BLOB})

    result = await _tool(handler).run(action="horizons", target="Moon")
    assert result.ok, result.output
    assert seen
    url = seen[0]
    assert "START_TIME=" in url
    assert "2026-10-05" in url
    assert "22:17" in url
    assert "00:00" not in url.split("START_TIME=")[1][:20]
    assert "QUANTITIES" in url.upper()
    assert "20" in url.upper().split("QUANTITIES=")[1][:20]

    now_km = round(_NOW_AU * _AU_KM)
    far_km = round(_FAR_AU * _AU_KM)
    near_km = round(_NEAR_AU * _AU_KM)
    out = result.output
    assert str(now_km) in out or f"{now_km:,}" in out
    # Far: 2026-10-16 23:00 UTC -> 7:00 PM Eastern on Oct 16
    assert "Oct 16" in out
    assert "7:00 PM" in out or "7 PM" in out
    # Near: 2026-Oct-28 18:00 UTC -> 2:00 PM Eastern on Oct 28
    assert "Oct 28" in out
    assert "2:00 PM" in out or "2 PM" in out
    assert "Eastern" in out
    assert str(far_km) in out or f"{far_km:,}" in out
    assert str(near_km) in out or f"{near_km:,}" in out
    assert "Target body name" not in out
    assert "The Moon" in out or "the Moon" in out
    assert "from Earth right now" in out


@pytest.mark.asyncio
async def test_distance_sentence_with_a_date_still_uses_the_now_summary() -> None:
    """A stuffed date and a sentence must not leave the no-date Mars summary."""
    values = [1.63 - 0.001 * i for i in range(12)]
    seen: list[str] = []
    result = await _tool_blob(_hourly_from_now_minus_1h(values), seen).run(
        action="horizons",
        query="Mars closest Nov 4",
        date="2026-11-04",
    )
    assert result.ok, result.output
    assert result.data.get("mode") == "now"
    url = seen[0]
    assert "STEP_SIZE=1h" in url
    assert "COMMAND='499'" in url
    assert "no closest or farthest" in result.output
    assert "Nov" not in result.output
    assert "335" not in result.output
    assert "2026-11-04" not in result.output


@pytest.mark.asyncio
async def test_no_turning_point_in_window_does_not_invent_one() -> None:
    values = [1.63 - 0.001 * i for i in range(12)]
    seen: list[str] = []
    result = await _tool_blob(_hourly_from_now_minus_1h(values), seen).run(
        action="horizons", target="Mars"
    )
    assert result.ok, result.output
    out = result.output
    assert "Mars" in out
    assert "30 days" in out
    last = (_NOW + timedelta(hours=10)).astimezone(_NY)
    first = _NOW.astimezone(_NY)
    last_clock = last.strftime("%I:%M %p").lstrip("0")
    first_clock = first.strftime("%I:%M %p").lstrip("0")
    assert f"{last:%b} {last.day}" not in out or last_clock not in out
    assert "closest on" not in out
    assert "farthest on" not in out
    assert first_clock not in out


@pytest.mark.asyncio
async def test_just_past_a_deep_perigee_names_the_next_perigee_not_the_next_hour() -> None:
    # now-1h: deep perigee; now: rising; apogee later; shallower perigee after that.
    values = [
        0.002382,
        0.002390,
        0.002500,
        0.002600,
        0.002680,
        0.002705,
        0.002680,
        0.002550,
        0.002460,
        0.002440,
        0.002460,
        0.002480,
    ]
    seen: list[str] = []
    result = await _tool_blob(_hourly_from_now_minus_1h(values), seen).run(
        action="horizons", target="Moon"
    )
    assert result.ok, result.output
    out = result.output
    expect = (_NOW + timedelta(hours=8)).astimezone(_NY)
    assert expect.strftime("%b") in out
    assert str(expect.day) in out
    assert expect.strftime("%I:%M %p").lstrip("0") in out
    now_local = _NOW.astimezone(_NY)
    next_hour = (_NOW + timedelta(hours=1)).astimezone(_NY)
    assert now_local.strftime("%I:%M %p").lstrip("0") not in out
    assert next_hour.strftime("%I:%M %p").lstrip("0") not in out


@pytest.mark.asyncio
async def test_summary_has_no_model_facing_text() -> None:
    seen: list[str] = []
    result = await _tool_blob(_OBSERVER_BLOB, seen).run(action="horizons", target="Moon")
    assert result.ok, result.output
    out = result.output
    assert "ssd.jpl.nasa.gov" not in out
    assert "Not a measurement" not in out
    assert "Horizons" not in out
    assert "301" not in out
    assert result.data.get("source") == "JPL Horizons"



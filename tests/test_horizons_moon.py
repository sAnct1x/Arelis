"""Horizons Moon distance: name map, query fallback, now/extrema summary."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import unquote
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

_OBSERVER_BLOB = f"""
*******************************************************************************
Target body name: Moon (301)
*******************************************************************************
$$SOE
 2026-Oct-05 23:17     {_NOW_AU:.9f}  -0.0100000000000000
 2026-Oct-16 23:00     {_FAR_AU:.9f}   0.0001000000000000
 2026-Oct-28 18:00     {_NEAR_AU:.9f}   0.0002000000000000
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,expected",
    [
        ("Moon", "301"),
        ("moon", "301"),
        ("the Moon", "301"),
        ("Luna", "301"),
        ("Sun", "10"),
    ],
)
async def test_moon_name_maps_to_301(name: str, expected: str) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(unquote(str(request.url)))
        return httpx.Response(200, json={"result": _OBSERVER_BLOB})

    result = await _tool(handler).run(action="horizons", target=name, date="2026-10-05")
    assert result.ok, result.output
    assert seen
    assert f"COMMAND='{expected}'" in seen[0]


@pytest.mark.asyncio
async def test_body_in_query_is_used_when_target_blank() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(unquote(str(request.url)))
        return httpx.Response(200, json={"result": _OBSERVER_BLOB})

    result = await _tool(handler).run(action="horizons", query="Moon")
    assert len(seen) == 1
    assert "COMMAND='301'" in seen[0]
    assert result.ok, result.output


@pytest.mark.asyncio
async def test_ambiguous_name_list_is_not_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"result": _AMBIGUOUS_BLOB})

    result = await _tool(handler).run(action="horizons", target="Moon")
    assert result.ok is False
    assert result.data.get("fail_class") == "fail:name"
    assert "301" in result.output


@pytest.mark.asyncio
async def test_moon_distance_now_and_next_extremes_in_local_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import arelis.tools.catalog as catalog

    monkeypatch.setattr(catalog, "_utc_now", lambda: _NOW)
    monkeypatch.setattr(catalog, "_local_zone", lambda: ZoneInfo("America/New_York"))

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
    assert "23:17" in url
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
    # Near: 2026-10-28 18:00 UTC -> 2:00 PM Eastern on Oct 28
    assert "Oct 28" in out
    assert "2:00 PM" in out or "2 PM" in out
    assert "Eastern" in out
    assert str(far_km) in out or f"{far_km:,}" in out
    assert str(near_km) in out or f"{near_km:,}" in out
    assert "Target body name" not in out


@pytest.mark.asyncio
async def test_http_400_surfaces_horizons_message() -> None:
    message = (
        "invalid value specified for query parameter 'REF_PLANE' "
        "(ECLIPJ2000): expected: ECLIPTIC, FRAME, BODY EQUATOR"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(400, json={"code": "400", "message": message})

    result = await _tool(handler).run(
        action="horizons", target="399", date="2000-01-01", table="vectors"
    )
    assert result.ok is False
    assert message in result.output


@pytest.mark.asyncio
async def test_next_closest_is_a_later_pass_when_now_is_the_closest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asked right at a closest pass, the answer must name the next one, not now."""
    import arelis.tools.catalog as catalog

    monkeypatch.setattr(catalog, "_utc_now", lambda: _NOW)
    monkeypatch.setattr(catalog, "_local_zone", lambda: ZoneInfo("America/New_York"))
    blob = """
$$SOE
 2026-Oct-05 23:17     0.002430000  0.01
 2026-Oct-06 23:00     0.002440000  0.01
 2026-Oct-16 23:00     0.002705000  0.01
 2026-Oct-30 18:00     0.002436000  0.01
 2026-Oct-31 18:00     0.002450000  0.01
$$EOE
"""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"result": blob})

    result = await _tool(handler).run(action="horizons", target="Moon")
    assert result.ok, result.output
    closest = result.output.split("Next closest:")[1].split("Next farthest:")[0]
    assert "Oct 30" in closest
    assert "Oct 5" not in closest

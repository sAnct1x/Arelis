"""Local rise, set, and altitude, and a two-number target is not an asteroid.

The human questions are things like "when does the moon come up tonight?"
and "is the moon visible tonight?". The calls below are the lookup those
questions need. Reference times are from pyephem 4.2.1 in a throwaway
environment, not from this module: Exampleville coordinates 39.7817 N,
89.6501 W (the pair in tests/test_layout_a.py), 2026-10-08 18:00 UTC.
Sun, planets, and stars: pressure 0, horizon -0:50, center of the body.
Moon: pressure 1010, horizon 0, upper limb.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import unquote

import httpx
import pytest

from arelis.tools.catalog import CatalogTool

# Exampleville, the synthetic place other tests use. Central time in October.
_LAT = 39.7817
_LON = -89.6501
_WHEN = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)

# Rise and set are UTC. Altitude and azimuth stay on their own lines so a
# pair of decimals is not read as a place.
_MOON = ("2026-10-09T10:58:28Z", "2026-10-08T22:24:55Z")
_MOON_ALT = 44.2531
_MOON_AZ = 217.8796
_JUPITER = ("2026-10-09T07:24:54Z", "2026-10-08T21:19:16Z")
_JUPITER_ALT = 36.9184
_JUPITER_AZ = 258.3748
_VEGA = ("2026-10-09T14:27:45Z", "2026-10-09T08:20:22Z")
_VEGA_ALT = 29.1570
_VEGA_AZ = 62.0033
_SUN = ("2026-10-09T12:02:51Z", "2026-10-08T23:29:41Z")
_SUN_ALT = 44.0123
_SUN_AZ = 184.8174


class _Place:
    def __init__(self, *, lat=_LAT, lon=_LON, timezone="America/Chicago", blank=False):
        self.latitude = None if blank else lat
        self.longitude = None if blank else lon
        self.timezone = "" if blank else timezone
        self.utc_offset = ""

    def snapshot(self):
        return self


def _tool(place: _Place | None, seen: list[str] | None = None) -> CatalogTool:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(unquote(str(request.url)))
        return httpx.Response(
            200,
            json={"result": "Target body name: 301 Bavaria\n elongation 147"},
        )

    kwargs: dict = {
        "client": httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0),
    }
    if place is not None:
        kwargs["location"] = place
    return CatalogTool(**kwargs)


@pytest.fixture
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    import arelis.tools.sky_local as sky

    monkeypatch.setattr(sky, "utc_now", lambda: _WHEN)


def _minutes(got: str | None, want: str) -> float:
    assert got, "missing time"
    left = datetime.strptime(got, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    right = datetime.strptime(want, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return abs((left - right).total_seconds()) / 60.0


async def _local(target: str, place: _Place | None = None) -> object:
    return await _tool(place if place is not None else _Place()).run(
        action="horizons", table="local", target=target
    )


@pytest.mark.asyncio
async def test_two_numbers_are_not_the_moon(_fixed_clock) -> None:
    """'is the moon visible tonight?' once produced target 301 147."""
    seen: list[str] = []
    result = await _tool(None, seen).run(action="horizons", target="301 147")
    assert seen == []
    assert result.ok is False
    text = result.output.casefold()
    assert "bavaria" not in text
    assert "asteroid" not in text
    assert "147" not in text


@pytest.mark.asyncio
async def test_a_number_led_name_is_not_sent(_fixed_clock) -> None:
    seen: list[str] = []
    result = await _tool(None, seen).run(action="horizons", target="301 Bavaria")
    assert seen == []
    assert result.ok is False
    assert "bavaria" not in result.output.casefold()


@pytest.mark.asyncio
async def test_moon_with_extra_numbers_stays_the_moon(_fixed_clock) -> None:
    seen: list[str] = []
    result = await _tool(_Place(), seen).run(
        action="horizons", table="local", target="Moon 301 147"
    )
    assert seen == []
    assert result.ok, result.output
    assert result.data["body"] == "Moon"
    assert "asteroid" not in result.output.casefold()
    assert "bavaria" not in result.output.casefold()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target,rise,set_,alt,az",
    [
        ("Moon", *_MOON, _MOON_ALT, _MOON_AZ),
        ("Jupiter", *_JUPITER, _JUPITER_ALT, _JUPITER_AZ),
        ("Vega", *_VEGA, _VEGA_ALT, _VEGA_AZ),
        ("Sun", *_SUN, _SUN_ALT, _SUN_AZ),
    ],
)
async def test_rise_set_and_height_match_the_almanac(
    _fixed_clock, target, rise, set_, alt, az
) -> None:
    result = await _local(target)
    assert result.ok, result.output
    assert _minutes(result.data["rise"], rise) <= 2
    assert _minutes(result.data["set"], set_) <= 2
    assert abs(result.data["alt_deg"] - alt) <= 0.5
    assert abs(result.data["az_deg"] - az) <= 1.0
    assert "asteroid" not in result.output.casefold()
    low = result.output.casefold()
    if result.data["up"]:
        assert "degrees up" in low
    else:
        assert "below the horizon" in low
    assert "rises at" in low
    assert "sets at" in low


@pytest.mark.asyncio
async def test_polaris_does_not_set(_fixed_clock) -> None:
    result = await _local("Polaris")
    assert result.ok, result.output
    assert result.data["state"] == "never_sets"
    assert result.data["up"] is True
    assert result.data["rise"] is None
    assert result.data["set"] is None
    assert "does not set" in result.output.casefold()
    assert abs(result.data["alt_deg"] - 39.2359) <= 0.5


@pytest.mark.asyncio
async def test_the_sun_does_not_set_in_the_arctic_summer(_fixed_clock) -> None:
    place = _Place(lat=80.0, lon=0.0, timezone="UTC")
    import arelis.tools.sky_local as sky

    sky.utc_now = lambda: datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
    result = await _local("Sun", place)
    assert result.ok, result.output
    assert result.data["state"] == "never_sets"
    assert "does not set" in result.output.casefold()


@pytest.mark.asyncio
async def test_no_saved_place_asks_plainly(_fixed_clock) -> None:
    result = await _local("Moon", _Place(blank=True))
    assert result.ok is False
    low = result.output.casefold()
    assert "no location" in low
    assert "set" in low
    assert "39." not in result.output
    assert "profile" not in low
    assert "yaml" not in low


@pytest.mark.asyncio
async def test_a_single_planet_id_is_still_a_distance_call() -> None:
    """499 alone is Mars. A second number is what made 301 an asteroid."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(unquote(str(request.url)))
        return httpx.Response(
            200,
            json={
                "result": (
                    "$$SOE\n"
                    " 2026-Oct-08 17:00     1.500000000   0.01\n"
                    " 2026-Oct-08 18:00     1.500000000   0.01\n"
                    " 2026-Oct-08 19:00     1.510000000   0.01\n"
                    "$$EOE\n"
                )
            },
        )

    tool = CatalogTool(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    )
    result = await tool.run(action="horizons", target="499")
    assert seen
    assert "COMMAND='499'" in seen[0]
    assert result.ok, result.output

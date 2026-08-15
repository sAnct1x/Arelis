"""Location: a chain of sources merged into one answer.

Nothing here touches the network. The IP layer is exercised through its parsing
rather than through a request, because what actually varies between services is
the shape of the JSON, and that is the part worth pinning.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arelis.location import (
    LocationResolver,
    UserLocation,
    build_location,
    merge_locations,
)
from arelis.location.providers import (
    IPGeolocationProvider,
    ManualProfileProvider,
    SystemProvider,
)

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _profile(tmp_path: Path, body: str) -> ManualProfileProvider:
    path = tmp_path / "profile.yaml"
    path.write_text(body, encoding="utf-8")
    return ManualProfileProvider(path)


class _FixedProvider:
    def __init__(self, name: str, precedence: int, **fields) -> None:
        self.name = name
        self.precedence = precedence
        self._fields = fields

    def resolve(self) -> UserLocation:
        found = UserLocation(**self._fields)
        for key, value in self._fields.items():
            if value not in ("", None):
                found.sources[key] = self.name
        return found


# --------------------------------------------------------------------------
# The profile: what the user wrote wins
# --------------------------------------------------------------------------


def test_the_profile_is_read_from_a_location_section(tmp_path) -> None:
    provider = _profile(
        tmp_path,
        "location:\n  city: Springfield\n  state: Illinois\n  zip: '62701'\n"
        "  lat: 39.7817\n  lon: -89.6501\n  timezone: America/Chicago\n",
    )
    found = provider.resolve()
    assert found is not None
    assert found.city == "Springfield"
    # state and zip are accepted as synonyms; nobody calls it a postal code.
    assert found.region == "Illinois"
    assert found.postal_code == "62701"
    assert found.latitude == pytest.approx(39.7817)
    assert found.longitude == pytest.approx(-89.6501)
    assert found.timezone == "America/Chicago"
    assert found.sources["city"] == "profile"


def test_a_profile_without_the_section_header_still_works(tmp_path) -> None:
    """Half the point of the file is that it can be edited without reading a
    manual, and the outer key is the easiest thing to leave off."""
    provider = _profile(tmp_path, "city: Reykjavik\ncountry: IS\n")
    found = provider.resolve()
    assert found is not None
    assert found.city == "Reykjavik"


def test_a_missing_profile_is_not_an_error(tmp_path) -> None:
    assert ManualProfileProvider(tmp_path / "nope.yaml").resolve() is None


def test_a_broken_profile_does_not_take_the_turn_down(tmp_path) -> None:
    provider = _profile(tmp_path, "location: [this is not a mapping\n")
    assert provider.resolve() is None


def test_editing_the_profile_takes_effect_without_a_restart(tmp_path) -> None:
    provider = _profile(tmp_path, "location:\n  city: Springfield\n")
    assert provider.resolve().city == "Springfield"
    provider.path.write_text("location:\n  city: Boston\n", encoding="utf-8")
    assert provider.resolve().city == "Boston"


# --------------------------------------------------------------------------
# The merge: field by field, not source by source
# --------------------------------------------------------------------------


def test_the_profile_outranks_an_automatic_guess() -> None:
    merged = merge_locations(
        [
            ("profile", _FixedProvider("profile", 100, city="Springfield").resolve()),
            ("ip", _FixedProvider("ip", 40, city="Ashburn").resolve()),
        ]
    )
    assert merged.city == "Springfield"
    assert merged.sources["city"] == "profile"


def test_a_partly_filled_profile_still_collects_the_rest() -> None:
    """Naming only a city must not cost the timezone the operating system knows
    or the coordinates a lookup found. That is why the merge is per field."""
    merged = merge_locations(
        [
            ("profile", _FixedProvider("profile", 100, city="Springfield").resolve()),
            (
                "ip",
                _FixedProvider(
                    "ip", 40, city="San Francisco", latitude=37.7749, longitude=-122.4194
                ).resolve(),
            ),
            ("system", _FixedProvider("system", 20, utc_offset="UTC-05:00").resolve()),
        ]
    )
    assert merged.city == "Springfield"
    assert merged.latitude == pytest.approx(37.7749)
    assert merged.utc_offset == "UTC-05:00"
    assert merged.sources == {
        "city": "profile",
        "latitude": "ip",
        "longitude": "ip",
        "utc_offset": "system",
    }


# --------------------------------------------------------------------------
# What the model is told
# --------------------------------------------------------------------------


def test_nothing_known_means_no_line_at_all() -> None:
    assert UserLocation().prompt_line() is None
    assert UserLocation(utc_offset="UTC-05:00").prompt_line() is None


def test_the_prompt_line_carries_the_place_and_the_coordinates() -> None:
    line = UserLocation(
        city="Springfield",
        region="Illinois",
        country="US",
        postal_code="62701",
        latitude=39.7817,
        longitude=-89.6501,
        timezone="America/Chicago",
    ).prompt_line()
    assert line is not None
    # The postal code rides with the region, the way an address is written.
    assert "Springfield, Illinois 62701, US" in line
    assert "39.7817" in line and "-89.6501" in line
    assert "America/Chicago" in line
    # One sentence of facts and one of instruction. It is paid for every turn.
    assert len(line) < 320


def test_a_postal_code_alone_is_enough_to_be_useful() -> None:
    assert UserLocation(postal_code="62701").known()
    assert UserLocation(latitude=39.78, longitude=-89.65).known()


def test_describe_says_where_each_field_came_from() -> None:
    found = UserLocation(city="Springfield", sources={"city": "profile"})
    assert "city: Springfield  (from profile)" in found.describe()


def test_describe_with_nothing_known_says_how_to_fix_it() -> None:
    text = UserLocation().describe()
    assert "data/profile.yaml" in text


# --------------------------------------------------------------------------
# The IP layer: opt-in, and tolerant of whichever service is configured
# --------------------------------------------------------------------------


def test_the_network_layer_is_off_unless_it_is_switched_on(tmp_path) -> None:
    """Silently asking a third party where this machine is, on every start, is
    not something a local-first assistant should decide for the user."""
    resolver = build_location({"location": {"profile_path": str(tmp_path / "p.yaml")}})
    assert not resolver.network_enabled()
    assert not resolver.stale()


def test_the_network_layer_is_built_when_asked(tmp_path) -> None:
    resolver = build_location(
        {
            "location": {
                "profile_path": str(tmp_path / "p.yaml"),
                "network": {"enabled": True, "cache_hours": 6},
            }
        }
    )
    assert resolver.network_enabled()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "city": "Springfield",
            "region": "Illinois",
            "postal": "62701",
            "latitude": 39.7817,
            "longitude": -89.6501,
            "timezone": "America/Chicago",
        },
        # ipinfo.io packs the pair into one "loc" string.
        {
            "city": "Springfield",
            "region": "Illinois",
            "postal": "62701",
            "loc": "39.7817,-89.6501",
            "timezone": "America/Chicago",
        },
    ],
)
@pytest.mark.asyncio
async def test_the_common_response_shapes_are_all_understood(monkeypatch, payload) -> None:
    """location.network.url is meant to be swappable, and the services do not
    agree on field names."""
    provider = IPGeolocationProvider()
    _patch_httpx(monkeypatch, payload)
    found = await provider.resolve()
    assert found is not None
    assert found.city == "Springfield"
    assert found.postal_code == "62701"
    assert found.latitude == pytest.approx(39.7817)
    assert found.longitude == pytest.approx(-89.6501)
    assert found.sources["city"] == "ip"


@pytest.mark.asyncio
async def test_a_refused_lookup_is_not_treated_as_an_answer(monkeypatch) -> None:
    _patch_httpx(monkeypatch, {"error": True, "reason": "RateLimited"})
    assert await IPGeolocationProvider().resolve() is None


def _patch_httpx(monkeypatch, payload: dict) -> None:
    import httpx

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payload

    class _Client:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> None:
            return None

        async def get(self, url, **kwargs) -> _Response:
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


# --------------------------------------------------------------------------
# The resolver: cached across restarts, never blocking a turn
# --------------------------------------------------------------------------


def test_a_cached_lookup_survives_a_restart(tmp_path) -> None:
    """Otherwise carrying a laptop between cities costs a request per launch."""
    cache = tmp_path / "location_cache.json"
    cache.write_text(
        json.dumps(
            {
                "resolved_at": 9e12,  # far future, so it reads as fresh
                "location": {"city": "Lisbon", "sources": {"city": "ip"}},
            }
        ),
        encoding="utf-8",
    )
    resolver = LocationResolver(
        [ManualProfileProvider(tmp_path / "absent.yaml")],
        IPGeolocationProvider(),
        cache_path=cache,
    )
    assert resolver.snapshot().city == "Lisbon"
    assert not resolver.stale()


def test_a_corrupt_cache_is_ignored_rather_than_fatal(tmp_path) -> None:
    cache = tmp_path / "location_cache.json"
    cache.write_text("{not json", encoding="utf-8")
    resolver = LocationResolver(
        [ManualProfileProvider(tmp_path / "absent.yaml")],
        IPGeolocationProvider(),
        cache_path=cache,
    )
    assert resolver.stale()


@pytest.mark.asyncio
async def test_refresh_does_nothing_when_there_is_no_network_layer(tmp_path) -> None:
    resolver = LocationResolver([_profile(tmp_path, "location:\n  city: Oslo\n")])
    found = await resolver.refresh(force=True)
    assert found.city == "Oslo"


def test_the_system_layer_always_knows_the_offset() -> None:
    """The one thing a machine genuinely knows about where it is without asking
    anybody: how far its clock is from UTC."""
    found = SystemProvider().resolve()
    assert found is not None
    assert found.utc_offset.startswith("UTC")
    assert found.sources["utc_offset"] == "system"


# --------------------------------------------------------------------------
# The tool
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_tool_reports_the_place_and_its_provenance(tmp_path) -> None:
    from arelis.tools.user_location import UserLocationTool

    resolver = LocationResolver([_profile(tmp_path, "location:\n  city: Springfield\n")])
    result = await UserLocationTool(resolver).run()
    assert result.ok
    assert "Springfield" in result.output
    assert result.data["known"] is True
    assert result.data["city"] == "Springfield"


@pytest.mark.asyncio
async def test_the_tool_succeeds_even_with_nothing_to_report(tmp_path) -> None:
    """Failing would invite the model to retry a call that cannot start
    returning an answer. The output says what the user has to do instead."""
    from arelis.tools.user_location import UserLocationTool

    resolver = LocationResolver([ManualProfileProvider(tmp_path / "absent.yaml")])
    result = await UserLocationTool(resolver).run()
    assert result.ok
    assert result.data["known"] is False
    assert "profile.yaml" in result.output


def test_the_tool_is_registered_and_can_be_switched_off(tmp_path) -> None:
    from arelis.tools import build_tool_registry
    from arelis.workspace import WorkspaceRoots

    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    registry = build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert "user_location" in registry.names()

    off = build_tool_registry({"tools": {}, "agent": {}, "location": {"enabled": False}}, workspace)
    assert "user_location" not in off.names()

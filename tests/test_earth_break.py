"""Try to break Earth / Reality contracts. These go red when the lie returns."""

from __future__ import annotations

import pytest

from arelis.earth.entity import Entity
from arelis.earth.frames import lla_to_ecef
from arelis.earth.runtime import EarthRuntime, set_earth
from arelis.tools.earth_tool import EarthTool


def _quake(eid: str, lat: float, lon: float) -> Entity:
    x, y, z = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=eid,
        cls="quake",
        layer="quakes",
        label="last shock",
        x=x,
        y=y,
        z=z,
        freshness="delayed",
        source="USGS all_day",
    )


def test_usgs_timeout_keeps_sim_quakes() -> None:
    from arelis.earth.live import _apply_live
    from arelis.earth.store import EntityStore

    store = EntityStore()
    store.upsert(_quake("usgs:sim", 35.0, 139.0))
    _apply_live(store, {"usgs": None}, {"usgs"}, view=None)
    assert store.get("usgs:sim") is not None


def test_leave_twice_is_already_solar() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    first = earth.leave()
    second = earth.leave()
    assert earth.active is False
    assert "solar" in second.lower() or "already" in second.lower()
    assert first != "" or second != ""


@pytest.mark.asyncio
async def test_earth_tool_leave_when_solar_is_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: True)
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    assert earth.active is True
    set_earth(earth)
    tool = EarthTool()
    left = await tool.run(action="leave")
    assert left.ok
    assert earth.active is False
    assert left.data["active"] is False
    assert left.output.startswith("Left Earth. Back to the solar lab.")
    again = await tool.run(action="leave")
    assert again.ok
    assert again.output.startswith("already solar")
    assert earth.active is False
    set_earth(None)


def test_launches_timeout_keeps_pad() -> None:
    from arelis.earth.live import _apply_live
    from arelis.earth.store import EntityStore

    store = EntityStore()
    x, y, z = lla_to_ecef(28.6, -80.6, 0.0)
    store.upsert(
        Entity(
            id="ll2:sim-pad",
            cls="site",
            layer="sites",
            label="sim pad",
            x=x,
            y=y,
            z=z,
            source="Launch Library 2",
        )
    )
    _apply_live(store, {"launches": None}, {"launches"}, view=None)
    assert store.get("ll2:sim-pad") is not None



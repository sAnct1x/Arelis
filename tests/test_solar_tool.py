"""Solar tool: Hohmann is free; impulse is gated; load is Horizons."""

from __future__ import annotations

import pytest

from arelis.tools.base import ToolRegistry
from arelis.tools.solar_tool import WRITE_ACTIONS, SolarTool


@pytest.mark.asyncio
async def test_hohmann_does_not_need_the_stage() -> None:
    tool = SolarTool()
    result = await tool.run(action="hohmann", r1_au=1.0, r2_au=1.523679)
    assert result.ok, result.output
    assert "Vis-viva" in result.output
    assert result.data["dv1"] > 0


@pytest.mark.asyncio
async def test_status_without_a_system_is_honest() -> None:
    from arelis.physics.runtime import set_system

    set_system(None)
    tool = SolarTool()
    result = await tool.run(action="status")
    assert result.ok
    assert "No solar system" in result.output


def test_impulse_needs_allow() -> None:
    registry = ToolRegistry()
    registry.register(SolarTool())
    assert "impulse" in WRITE_ACTIONS
    assert registry.needs_confirm("solar", {"action": "impulse", "name": "Earth"})
    assert not registry.needs_confirm("solar", {"action": "status"})
    assert registry.needs_confirm("solar", {"action": "add_planet", "r1_au": 2.5})
    assert registry.needs_confirm("solar", {"action": "tracer"})
    assert registry.needs_confirm("solar", {"action": "l4"})
    assert registry.needs_confirm("solar", {"action": "epoch", "epoch_gyr": 5.4})
    assert not registry.needs_confirm("solar", {"action": "craft"})
    assert not registry.needs_confirm("solar", {"action": "travel", "name": "Earth"})
    assert not registry.needs_confirm("solar", {"action": "lock", "name": "Earth"})
    assert "load_demo" not in SolarTool.parameters_schema["properties"]["action"]["enum"]


@pytest.mark.asyncio
async def test_lagrange_without_system_fails_cleanly() -> None:
    from arelis.physics.runtime import set_system

    set_system(None)
    tool = SolarTool()
    result = await tool.run(action="lagrange")
    assert not result.ok
    assert result.data["fail_class"] == "fail:empty"


@pytest.mark.asyncio
async def test_craft_without_a_system_fails_cleanly() -> None:
    from arelis.physics.runtime import set_system

    set_system(None)
    tool = SolarTool()
    result = await tool.run(action="craft")
    assert not result.ok
    assert result.data["fail_class"] == "fail:empty"


@pytest.mark.asyncio
async def test_craft_action_does_not_spawn_a_probe() -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    tool = SolarTool()
    result = await tool.run(action="craft")
    assert result.ok, result.output
    assert "no rideable craft" in result.output.lower()
    system = get_system()
    assert system is not None
    assert system.nbody.find("craft") is None
    set_system(None)


@pytest.mark.asyncio
async def test_lock_does_not_travel_and_travel_queues_warp() -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    tool = SolarTool()
    locked = await tool.run(action="lock", name="Earth")
    assert locked.ok, locked.output
    assert "did not move" in locked.output
    system = get_system()
    assert system is not None
    assert system.pending_inspect == "Earth"
    assert system.pending_travel is None
    warped = await tool.run(action="travel", name="Earth")
    assert warped.ok, warped.output
    assert "not an N-body burn" in warped.output
    assert system.pending_travel == "Earth"
    set_system(None)


@pytest.mark.asyncio
async def test_load_uses_horizons_and_labeled_cache() -> None:
    import httpx

    from arelis.physics.constants import BODIES
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.tools.catalog import CatalogTool

    blob = """
$$SOE
2451545.000000000 = A.D. 2000-Jan-01 12:00:00.0000 TDB
 X = 1.495978707000000E+08 Y =-2.000000000000000E+03 Z = 4.000000000000000E+03
 VX=-1.000000000000000E-03 VY= 2.978000000000000E+01 VZ=-4.000000000000000E-03
$$EOE
"""
    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(None)
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        hits["n"] += 1
        return httpx.Response(200, json={"result": blob})

    catalog = CatalogTool(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    )
    tool = SolarTool(catalog=catalog)
    first = await tool.run(action="load", date="2000-01-01", tracers=0)
    assert first.ok, first.output
    assert hits["n"] == len(BODIES)
    assert first.data.get("cached") is False
    system = get_system()
    assert system is not None
    assert system.nbody.find("Sun") is not None
    assert system.nbody.find("Earth") is not None
    assert "cached" not in system.epoch_tdb
    second = await tool.run(action="load", date="2000-01-01", tracers=0)
    assert second.ok, second.output
    assert hits["n"] == len(BODIES)
    assert second.data.get("cached") is True
    system = get_system()
    assert system is not None
    assert "cached fetch" in system.epoch_tdb
    assert system.ic_date == "2000-01-01"
    set_system(None)


@pytest.mark.asyncio
async def test_load_refresh_hits_horizons_again() -> None:
    import httpx

    from arelis.physics.constants import BODIES
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.tools.catalog import CatalogTool

    blob = """
$$SOE
2451545.000000000 = A.D. 2000-Jan-01 12:00:00.0000 TDB
 X = 1.495978707000000E+08 Y =-2.000000000000000E+03 Z = 4.000000000000000E+03
 VX=-1.000000000000000E-03 VY= 2.978000000000000E+01 VZ=-4.000000000000000E-03
$$EOE
"""
    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(None)
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        hits["n"] += 1
        return httpx.Response(200, json={"result": blob})

    catalog = CatalogTool(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    )
    tool = SolarTool(catalog=catalog)
    first = await tool.run(action="load", date="2000-01-02", tracers=0)
    assert first.ok, first.output
    n_first = hits["n"]
    assert n_first == len(BODIES)
    again = await tool.run(action="load", date="2000-01-02", tracers=0, refresh=True)
    assert again.ok, again.output
    assert hits["n"] == n_first + len(BODIES)
    assert again.data.get("cached") is False
    system = get_system()
    assert system is not None
    assert "cached" not in system.epoch_tdb
    set_system(None)


@pytest.mark.asyncio
async def test_load_does_not_replace_a_counterfactual() -> None:
    import httpx

    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.tools.catalog import CatalogTool

    blob = """
$$SOE
2451545.000000000 = A.D. 2000-Jan-01 12:00:00.0000 TDB
 X = 1.495978707000000E+08 Y =-2.000000000000000E+03 Z = 4.000000000000000E+03
 VX=-1.000000000000000E-03 VY= 2.978000000000000E+01 VZ=-4.000000000000000E-03
$$EOE
"""
    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(None)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"result": blob})

    tool = SolarTool(
        catalog=CatalogTool(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
        )
    )
    first = await tool.run(action="load", date="2000-01-04", tracers=0)
    assert first.ok, first.output
    system = get_system()
    assert system is not None
    assert system.prograde_impulse("Earth", 100.0)
    earth = system.nbody.find("Earth")
    assert earth is not None
    vx = earth.vx
    again = await tool.run(action="load", date="2000-01-04", tracers=0, refresh=True)
    assert again.ok, again.output
    assert again.data.get("replaced") is False
    system = get_system()
    assert system is not None
    assert system.counterfactual
    earth = system.nbody.find("Earth")
    assert earth is not None
    assert earth.vx == pytest.approx(vx)
    set_system(None)


@pytest.mark.asyncio
async def test_load_busy_horizons_stops_after_sun(monkeypatch) -> None:
    import httpx

    import arelis.tools.catalog as catalog
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.tools.catalog import CatalogTool

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setattr(catalog, "HORIZONS_RETRY_S", ())
    set_system(None)
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        hits["n"] += 1
        return httpx.Response(503, text="unavailable")

    tool = SolarTool(
        catalog=CatalogTool(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
        )
    )
    result = await tool.run(action="load", date="2000-01-03", tracers=0)
    assert not result.ok
    assert hits["n"] == 1
    assert "busy" in result.output.lower()
    assert "Mercury" not in result.output
    assert get_system() is None
    set_system(None)


def test_toggle_flag_enum_matches_the_tool() -> None:
    flags = SolarTool.parameters_schema["properties"]["flag"]["enum"]
    assert flags == [
        "osculating",
        "trails",
        "graphs",
        "lagrange",
        "gravity",
        "magnetic",
        "wind",
        "grid",
        "warp",
    ]


@pytest.mark.asyncio
async def test_toggle_gravity_and_rejects_unknown_flag() -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    tool = SolarTool()
    on = await tool.run(action="toggle", flag="gravity")
    assert on.ok, on.output
    system = get_system()
    assert system is not None
    assert system.overlay.show_gravity is True
    wind = await tool.run(action="toggle", flag="parker")
    assert wind.ok, wind.output
    assert system.overlay.show_wind is True
    assert "wind=" in wind.output
    bad = await tool.run(action="toggle", flag="chase")
    assert not bad.ok
    assert "gravity" in bad.output
    assert "magnetic" in bad.output
    assert "wind" in bad.output
    assert "grid" in bad.output
    system.apply_overlay("gravity", on=True)
    assert system.overlay.show_gravity is True
    system.apply_overlay("gravity", on=True)
    assert system.overlay.show_gravity is True
    system.apply_overlay("gravity", on=False)
    assert system.overlay.show_gravity is False
    set_system(None)

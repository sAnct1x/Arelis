"""Solar tool: Hohmann is free; impulse is gated; load is Horizons."""

from __future__ import annotations

import pytest

from arelis.tools.solar_tool import SolarTool


@pytest.mark.asyncio
async def test_realtime_locks_ias15_to_utc_now() -> None:
    from arelis.physics.clocks import tdb_jd_now
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    epoch = tdb_jd_now() - 0.01
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0, epoch_jd=epoch))
    tool = SolarTool()
    result = await tool.run(action="realtime")
    assert result.ok, result.output
    assert "UTC now" in result.output
    system = get_system()
    assert system is not None
    assert system.wall_lock is True
    assert system.paused is False
    assert system.t == pytest.approx(0.01 * 86_400.0, abs=5.0)
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



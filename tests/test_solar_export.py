"""Cited solar dump: hash of the IC, JSONL of live IAS15, tracers omitted."""

from __future__ import annotations

import json

import pytest

from arelis.physics.horizons import VectorState
from arelis.physics.ic_store import vectors_hash
from arelis.tools.base import SOLAR_WRITE_ACTIONS, ToolRegistry
from arelis.tools.confirm_copy import confirm_headline
from arelis.tools.solar_tool import WRITE_ACTIONS, SolarTool


def _sun() -> VectorState:
    return VectorState(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, units="SI", epoch_jd=2451545.0)


def test_vectors_hash_is_stable() -> None:
    states = {"Earth": _sun(), "Sun": _sun()}
    first = vectors_hash(states, "2000-01-01")
    shuffled = {"Sun": _sun(), "Earth": _sun()}
    assert vectors_hash(shuffled, "2000-01-01") == first
    assert len(first) == 64
    assert vectors_hash(states, "2000-01-02") != first


def test_dump_is_not_an_allow_card() -> None:
    assert WRITE_ACTIONS == frozenset(SOLAR_WRITE_ACTIONS)
    assert "dump" not in WRITE_ACTIONS
    registry = ToolRegistry()
    registry.register(SolarTool())
    assert not registry.needs_confirm("solar", {"action": "dump"})
    assert confirm_headline("solar", {"action": "dump"}) == "dump solar state"


@pytest.mark.asyncio
async def test_dump_without_a_system_fails_cleanly() -> None:
    from arelis.physics.runtime import set_system

    set_system(None)
    tool = SolarTool()
    result = await tool.run(action="dump")
    assert not result.ok
    assert result.data["fail_class"] == "fail:empty"


def test_dump_roundtrip_omits_tracers(tmp_path, monkeypatch) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.export import dump_state
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    states = sun_and_planet()
    system = SolarSystem.from_states(
        states, tracers=12, epoch_tdb="pytest IC", ic_date="2000-01-01"
    )
    assert system.ic_hash == vectors_hash(states, "2000-01-01")
    assert any(p.tracer for p in system.nbody.particles)
    system.overlay.show_grid = True
    folder = dump_state(system, stamp="20000101T000000Z")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == 1
    assert manifest["frame"] == "ECLIPJ2000"
    assert manifest["center"] == "SSB"
    assert manifest["ic_hash"] == system.ic_hash
    assert manifest["ic_date"] == "2000-01-01"
    assert manifest["camera"] is None
    assert manifest["still"] is False
    assert manifest["trigger"] == "dump"
    assert manifest["tracers_omitted"] is True
    assert manifest["overlay"]["grid"]["on"] is True
    assert "IAU" in manifest["overlay"]["grid"]["cite"]
    names = []
    for line in (folder / "state.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        names.append(row["name"])
        assert row["t"] == system.t
        assert len(row["r"]) == 3
        assert len(row["v"]) == 3
        assert "gm" in row
        assert "kind" in row
    assert "Sun" in names
    assert "Earth" in names
    tracer_names = {p.name for p in system.nbody.particles if p.tracer}
    assert tracer_names
    assert tracer_names.isdisjoint(names)


@pytest.mark.asyncio
async def test_solar_dump_writes_under_outputs(tmp_path, monkeypatch) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    set_system(
        SolarSystem.from_states(sun_and_planet(), tracers=0, ic_date="2000-01-01")
    )
    tool = SolarTool()
    result = await tool.run(action="dump")
    assert result.ok, result.output
    assert result.data["still"] is False
    folder = tmp_path / "outputs" / "physics" / "solar"
    written = list(folder.iterdir())
    assert written
    manifest = written[0] / "manifest.json"
    assert manifest.is_file()
    assert "No GL still" in result.output
    assert "ECLIPJ2000" in result.output
    body = json.loads((written[0] / "manifest.json").read_text(encoding="utf-8"))
    assert body["trigger"] == "dump"


def test_dump_on_leave_is_a_no_op_without_a_system(tmp_path, monkeypatch) -> None:
    from arelis.physics.export import dump_on_leave
    from arelis.physics.runtime import set_system

    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    set_system(None)
    assert dump_on_leave() is None
    root = tmp_path / "outputs" / "physics" / "solar"
    assert not root.exists() or not any(root.iterdir())


def test_dump_on_leave_writes_the_receipt(tmp_path, monkeypatch) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.export import dump_on_leave
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0, ic_date="2000-01-01"))
    folder = dump_on_leave(camera={"x": 1.0, "y": 2.0, "z": 3.0})
    assert folder is not None
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["trigger"] == "leave"
    assert manifest["camera"]["x"] == 1.0
    set_system(None)

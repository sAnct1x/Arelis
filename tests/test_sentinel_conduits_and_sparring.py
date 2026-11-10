"""Tests for polished Overseer shaders, kinetic 3D data conduits, and live Red Team sparring interception."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QWidget

from arelis import red_team_sparring
from arelis.ui import overseer_runtime
from arelis.ui.sentinel_host import SentinelWindow, teardown_sentinel_window

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"


def _entry_count(root: QObject) -> int:
    n = 0
    for child in root.findChildren(QObject):
        if "InstanceListEntry" in child.metaObject().className():
            n += 1
    return n


def test_overseer_shaders_include_claw_flare_obsidian_carapace_and_ocular_scan() -> None:
    errors = overseer_runtime.validate_overseer_shaders(ASSETS / "shaders")
    assert errors == [], errors

    hull_vert = (ASSETS / "shaders/hull.vert").read_text(encoding="utf-8")
    emissive_vert = (ASSETS / "shaders/emissive.vert").read_text(encoding="utf-8")
    hull_frag = (ASSETS / "shaders/hull.frag").read_text(encoding="utf-8")
    emissive_frag = (ASSETS / "shaders/emissive.frag").read_text(encoding="utf-8")
    lens_frag = (ASSETS / "shaders/lens.frag").read_text(encoding="utf-8")

    # Both vertex shaders deform forward claws via INSTANCE_DATA.y without breaking wave needles
    for vert in (hull_vert, emissive_vert):
        assert "clamp(packed - reachPairs * 2.0, 0.0, 1.0)" in vert
        assert "flare" in vert
    assert "CLEARCOAT_AMOUNT = 0.92;" in hull_frag
    assert "oilTint" in hull_frag
    assert "surge" in emissive_frag
    assert "hotCluster" in lens_frag


def test_kinetic_data_conduits_instancing_and_animation_in_overseer_qml(qt_app) -> None:
    units = [
        {
            "unit_id": "SNT-WRD-001",
            "caste": "warden",
            "state": "ENGAGED_DEFENSE",
            "position": [14.0, 1.2, -12.0],
            "laser_active": True,
            "laser_target": [22.0, 2.0, -18.0],
            "laser_kind": "defense",
        },
        {
            "unit_id": "SNT-HRV-001",
            "caste": "harvester",
            "state": "RETURNING",
            "position": [-10.0, 1.5, 8.0],
            "carrying_orb": True,
            "orb_color": "#22d3ee",
        },
    ]
    nodes = [
        {
            "node_id": "bastion-port-8790",
            "kind": "bastion",
            "label": ":8790 Sentinel Bridge",
            "position": [19.8, 0.0, 19.8],
            "status": "intercepting",
            "severity": "high",
        },
        {
            "node_id": "threat-0001",
            "kind": "threat",
            "label": "RED-TEAM: SSRF PROBE",
            "position": [22.0, 2.0, -18.0],
            "status": "policy_event",
            "severity": "critical",
        },
    ]
    fx_events = [
        {
            "kind": "packet_salvo",
            "origin": [-10.0, 1.5, 8.0],
            "target": [0.0, 0.0, 0.0],
            "color": "#38bdf8",
        }
    ]

    frame = overseer_runtime.build_frame(
        units,
        overseer_runtime.DEFAULT_CAMERA_DISTANCE,
        nodes=nodes,
        fx_events=fx_events,
    )
    conduits = frame["conduits"]
    assert len(conduits) > 10
    kinds = {c["kind"] for c in conduits}
    assert {"node", "packet", "beam", "orb"}.issubset(kinds)

    # Verify 3D quadratic Bezier motion toward Hive Core (0, 0, 0)
    pkt = next(c for c in conduits if c["kind"] == "orb")
    p0 = overseer_runtime.conduit_position_3d(pkt, 0.0)
    p1 = overseer_runtime.conduit_position_3d(pkt, 0.35)
    assert (p0[0], p0[1], p0[2]) != (p1[0], p1[1], p1[2])

    engine = QQmlEngine()
    engine.addImportPath(str(ASSETS))
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(ASSETS / "OverseerView.qml")))
    assert comp.status() == QQmlComponent.Status.Ready, comp.errors()
    inst = comp.create()
    assert inst is not None
    qt_app.processEvents()

    # Pause FrameAnimation so sceneTime steps deterministically
    for child in inst.findChildren(QObject):
        if "FrameAnimation" in child.metaObject().className():
            child.setProperty("running", False)

    conduit_cloud = next(
        child for child in inst.findChildren(QObject) if child.objectName() == "dataConduitCloud"
    )
    assert bool(conduit_cloud.property("visible")) is False

    inst.applyFrame(frame)
    qt_app.processEvents()
    assert bool(conduit_cloud.property("visible")) is True
    baseline_entries = _entry_count(inst)

    # Advancing sceneTime moves kinetic conduit packets without allocating new QObjects
    inst.setProperty("sceneTime", 1.25)
    qt_app.processEvents()
    assert _entry_count(inst) == baseline_entries

    for _ in range(6):
        inst.applyFrame(frame)
        qt_app.processEvents()
    assert _entry_count(inst) == baseline_entries

    inst.deleteLater()
    qt_app.processEvents()


@pytest.mark.asyncio
async def test_red_team_sparring_harness_triggers_live_swarm_interception(
    qt_app, tmp_path
) -> None:
    import sys

    sentinel_pkg = Path(__file__).resolve().parents[1] / "sentinel"
    if str(sentinel_pkg) not in sys.path:
        sys.path.insert(0, str(sentinel_pkg))
    from sentinel.core.hive import SwarmHive
    from sentinel.paths import set_runtime_root

    set_runtime_root(tmp_path)
    hive = SwarmHive()
    owner = QWidget()
    owner.resize(1280, 800)
    win = SentinelWindow(owner)
    owner.sentinel_window = win
    win._ensure_scene()
    qt_app.processEvents()

    frames_pushed: list[dict] = []

    def _on_snap(snap: dict) -> None:
        frames_pushed.append(win.apply_snapshot(snap))
        qt_app.processEvents()

    try:
        report = await red_team_sparring.run_hive_sparring_wave(
            hive, "full_wave", on_snapshot=_on_snap
        )
        assert report["ok"] is True
        assert report["vectors_dispatched"] == 3
        assert len(frames_pushed) == 2
        assert report["mid_conduit_count"] > 0

        # Verify Warden, Sanitizer, and Tripwire packs engaged and intercepted
        engaged = report["engaged_units"]
        engaged_castes = {u["caste"] for u in engaged}
        assert "warden" in engaged_castes
        assert "sanitizer" in engaged_castes
        assert any(u["claw"] == 0.85 for u in engaged if u["caste"] == "warden")

        by_caste = {item["caste"]: item for item in report["interceptions"]}
        assert by_caste["warden"]["ok"] is True
        assert by_caste["sanitizer"]["quarantined"] is True
        assert by_caste["tripwire"]["ok"] is True
    finally:
        await hive.trigger_emp("Sparring test cleanup")
        await hive.restore_from_emp()
        set_runtime_root(None)
        teardown_sentinel_window(owner)
        qt_app.processEvents()


def test_sentinel_units_and_nodes_stay_above_floor_and_step_smoothly(tmp_path) -> None:
    """Verify Sentinel units and 3D world nodes remain above y=0.45 and HUD status reflects state."""
    import sys

    sentinel_pkg = Path(__file__).resolve().parents[1] / "sentinel"
    if str(sentinel_pkg) not in sys.path:
        sys.path.insert(0, str(sentinel_pkg))
    from sentinel.core.fsm import CASTE_ORBIT_PROFILES
    from sentinel.core.hive import SwarmHive
    from sentinel.paths import set_runtime_root

    set_runtime_root(tmp_path)
    try:
        for caste_id, prof in CASTE_ORBIT_PROFILES.items():
            assert prof["y_band"] >= 2.0, f"{caste_id} y_band below floor clearance"
            assert prof["radius"] <= 25.0, f"{caste_id} radius outside arena"

        hive = SwarmHive()
        for _ in range(90):
            hive.step_world(1.0 / 60.0)
        snap = hive.world_snapshot()
        for u in snap["units"]:
            pos = u["position"]
            assert pos[1] >= 0.45, f"Unit {u['unit_id']} clipped below floor: y={pos[1]}"
            assert abs(pos[0]) < 36.0 and abs(pos[2]) < 36.0

        for n in snap["nodes"]:
            npos = n["position"]
            assert npos[1] >= 0.5, f"Node {n['node_id']} buried at y={npos[1]}"
            assert abs(npos[0]) < 36.0 and abs(npos[2]) < 36.0

        buckets = overseer_runtime.build_buckets(snap["units"])
        all_rows = [r for rows in buckets.values() for r in rows]
        assert any(r["vx"] != 0.0 or r["vz"] != 0.0 for r in all_rows)

        hud_idle = overseer_runtime.build_hud(snap)
        assert hud_idle["statusLine"] == "hive live · all local · sending out blocked"

        snap_working = dict(
            snap,
            active_banner={"title": "SENTINELS WORKING", "subtitle": "arXiv sweep"},
        )
        hud_working = overseer_runtime.build_hud(snap_working)
        assert "SENTINELS WORKING: arXiv sweep" in hud_working["statusLine"]

        snap_emp = dict(snap, emp={"tripped": True, "reason": "Operator test"})
        hud_emp = overseer_runtime.build_hud(snap_emp)
        assert "EMP EMERGENCY STOP ACTIVE" in hud_emp["statusLine"]
    finally:
        set_runtime_root(None)

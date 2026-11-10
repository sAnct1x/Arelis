"""PR6 Overseer: inset, fade lifecycle, scene filter, list window, LOD, zoom."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtQml import QJSEngine, QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QWidget

from arelis.ui import overseer_runtime
from arelis.ui.sentinel_host import (
    SentinelWindow,
    attach_sentinel_mote,
    teardown_sentinel_window,
)
from arelis.ui.sentinel_presence import (
    FADE_CLOSE_MS,
    FADE_CLOSED,
    FADE_OPEN,
    FADE_OPEN_MS,
    REDUCED_MS,
    RIGHT_UNCOVERED,
    PresenceController,
    fade_duration_ms,
    inset_geometry,
    mote_pos,
    right_uncovered,
)

LOGIC = Path(__file__).resolve().parents[1] / "sentinel/sentinel/ui/overseer/overseer_logic.js"


def _entry_count(root) -> int:
    n = 0
    for child in root.findChildren(QObject):
        if "InstanceListEntry" in child.metaObject().className():
            n += 1
    return n


def _qml_list(value):
    if value is None:
        return []
    to_var = getattr(value, "toVariant", None)
    if callable(to_var):
        value = to_var()
    return list(value)


def _logic_checks() -> dict:
    source = LOGIC.read_text(encoding="utf-8")
    engine = QJSEngine()
    # Qt JS has no Node `module`; bind the IIFE global and a stub exports object.
    engine.evaluate("var globalThis = this; var module = {exports: {}};")
    evaluated = engine.evaluate(source, str(LOGIC))
    if evaluated.isError():
        raise RuntimeError(evaluated.toString())
    script = r"""
(function () {
  const L = (typeof OverseerLogic !== "undefined")
    ? OverseerLogic
    : (module && module.exports);
  const out = {};
  out.lod200 = L.chooseLod(200, null);
  out.lod70 = L.chooseLod(70, null);
  out.lod50 = L.chooseLod(50, null);
  out.hystStay = L.chooseLod(160, 0);
  out.hystLeave = L.chooseLod(150, 0);
  out.hystEnter1 = L.chooseLod(70, 2);
  out.hystStay2 = L.chooseLod(65, 2);
  out.sil2 = L.silhouette(2);
  out.win = L.virtualWindow(0, 748, 100);
  out.demo = L.snapshotUnits({demo: true, units: [{unit_id: "SNT-DEMO"}]}).length;
  out.mixed = L.snapshotUnits({
    units: [
      {unit_id: "SNT-FAKE", demo: true},
      {unit_id: "SNT-SYN", synthetic: true},
      {unit_id: "SNT-WRD-001", caste: "warden", state: "PATROLLING"},
    ],
  }).map((u) => u.unit_id);
  out.dolly = L.cursorDolly([0, 0, 0], [10, 0, 0], 10, 20);
  out.pitchClose = L.pitchDeg(L.ZOOM_MIN);
  out.pitchWide = L.pitchDeg(L.ZOOM_MAX);
  out.inspWide = L.inspectorCollapsed(L.ZOOM_MAX, null);
  out.inspSelected = L.inspectorCollapsed(L.ZOOM_MAX, "SNT-WRD-001");
  out.rubberLo = L.wheelStep(L.ZOOM_MIN, -1);
  out.chipWide = L.chipState(30, false, 100);
  out.chipClose = L.chipState(50, false, 10);
  out.groups = L.groupUnits([
    {unit_id: "SNT-WRD-002", caste: "warden", state: "ENGAGED"},
    {unit_id: "SNT-WRD-001", caste: "warden", state: "PATROLLING"},
    {unit_id: "SNT-STK-001", caste: "stalker", state: "VECTORING"},
  ], "caste");
  out.empOk = L.actionAllowed("emp_halt");
  out.firewall = L.actionAllowed("firewall");
  out.kill = L.actionAllowed("kill");
  out.grant = L.actionAllowed("grant");
  out.idle = L.emptyTaskLabel(null);
  out.stateLabel = L.emptyTaskLabel("PATROLLING");
  out.zoomReduced = L.zoomDuration("focus", true);
  return JSON.stringify(out);
})()
"""
    wrapped = engine.evaluate(script)
    if wrapped.isError():
        raise RuntimeError(wrapped.toString())
    return json.loads(wrapped.toString())


# Serial: its Quick 3D teardown intermittently segfaults and took down an xdist worker
# (Ubuntu gw1, run 42693152838); the serial step keeps the crash from killing other tests.
@pytest.mark.serial
def test_overseer_inset_fade_scene_list_lod_zoom_and_lifecycle(qt_app, monkeypatch) -> None:
    geom = inset_geometry(2560, 1392)
    assert geom == (40, 44, 2110, 1306)
    assert right_uncovered(2560, geom) == RIGHT_UNCOVERED == 410
    small = inset_geometry(1280, 696)
    assert small[0] == 20 and small[1] == 22
    assert small[2] == 1055 and small[3] == 653
    assert mote_pos(2560, 1392) == (1250, 1090)
    assert fade_duration_ms(opening=True, reduced=False) == FADE_OPEN_MS == 650
    assert fade_duration_ms(opening=False, reduced=False) == FADE_CLOSE_MS == 500
    assert fade_duration_ms(opening=True, reduced=True) == REDUCED_MS == 200
    assert fade_duration_ms(opening=False, reduced=True) == 200

    presence = PresenceController()
    class _Surf:
        def __init__(self) -> None:
            self.presenceOpacity = 1.0

        def setProperty(self, key: str, value: object) -> None:
            setattr(self, key, value)

    surf = _Surf()
    assert presence.opacity == FADE_CLOSED
    assert presence.open_window() == 650
    assert presence.opacity == FADE_OPEN == 0.20
    assert presence.tick_scale == 0.25
    presence.apply_to(surf)
    assert surf.presenceOpacity == 0.20
    assert surf.presenceTick == 0.25
    assert presence.restore("error") == 500
    assert presence.opacity == FADE_CLOSED
    assert presence.tick_scale == 1.0
    assert presence.last_reason == "error"
    presence.apply_to(surf)
    assert surf.presenceOpacity == 1.0
    assert surf.presenceTick == 1.0
    assert presence.restore("quit", reduced=True) == 200
    assert presence.last_reason == "quit"

    js = _logic_checks()
    assert js["lod200"] == 0
    assert js["lod70"] == 1
    assert js["lod50"] == 2
    assert js["hystStay"] == 0
    assert js["hystLeave"] == 1
    assert js["hystEnter1"] == 1
    assert js["hystStay2"] == 2
    assert js["sil2"]["head"] == "tapered"
    assert js["sil2"]["lenses"] == 1
    assert js["sil2"]["tentacles"] == 4
    assert js["sil2"]["plates"] is False
    assert js["sil2"]["linkChains"] is False
    assert js["win"]["alive"] == 23
    assert js["win"]["rowH"] == 44
    assert js["demo"] == 0
    assert js["mixed"] == ["SNT-WRD-001"]
    assert js["dolly"] == [-10, 0, 0]
    assert js["pitchClose"] == 22
    assert js["pitchWide"] == 55
    assert js["inspWide"] is True
    assert js["inspSelected"] is False
    assert abs(js["rubberLo"] - 6 * 0.92) < 0.01
    assert js["chipWide"]["badges"] is True
    assert js["chipClose"]["chips"] is True
    assert [g["key"] for g in js["groups"]] == ["warden", "stalker"]
    assert js["groups"][0]["active"] == 1
    assert js["groups"][0]["units"][0]["unit_id"] == "SNT-WRD-002"
    assert js["empOk"] is True
    assert js["firewall"] is False
    assert js["kill"] is False
    assert js["grant"] is False
    assert js["idle"] == "idle"
    assert js["stateLabel"] == "patrolling"
    assert js["zoomReduced"] == 120

    owner = QWidget()
    owner.resize(2560, 1392)
    owner._quick_surface = _Surf()
    mote = attach_sentinel_mote(owner)
    assert mote is not None
    assert mote.pos().x() == 1250 - 11
    assert mote.pos().y() == 1090 - 11
    owner.show()
    qt_app.processEvents()
    owner.resize(1280, 696)
    qt_app.processEvents()
    mx, my = mote_pos(1280, 696)
    assert mote.pos().x() == mx - 11
    assert mote.pos().y() == my - 11
    owner.resize(2560, 1392)
    qt_app.processEvents()
    assert mote.pos().x() == 1250 - 11
    assert mote.pos().y() == 1090 - 11
    from arelis import sentinel_control

    monkeypatch.setattr(sentinel_control, "overseer_url", lambda: None)
    win = SentinelWindow(owner)
    owner.sentinel_window = win
    flags = win.windowFlags()
    assert bool(flags & Qt.WindowType.FramelessWindowHint)
    assert bool(flags & Qt.WindowType.Tool)
    win.show()
    qt_app.processEvents()
    assert win.geometry().width() == 2110
    assert win.geometry().height() == 1306
    assert win.presence.opacity == FADE_OPEN
    assert owner._quick_surface.presenceOpacity == FADE_OPEN
    assert win.is_offline()
    assert mote.isHidden()
    theme = win.property("sentinelTheme")
    assert theme in {"filament", "night", "sodium", "matrix"} or theme
    win.close()
    assert win.presence.opacity == FADE_CLOSED
    assert win.presence.last_reason == "close"
    assert owner._quick_surface.presenceOpacity == FADE_CLOSED
    assert not mote.isHidden()

    win2 = SentinelWindow(owner)
    owner.sentinel_window = win2
    win2.show()
    qt_app.processEvents()
    assert win2.presence.opacity == FADE_OPEN
    teardown_sentinel_window(owner)
    assert win2.presence.last_reason == "quit"
    assert win2.presence.opacity == FADE_CLOSED
    assert owner._quick_surface.presenceOpacity == FADE_CLOSED

    err_owner = QWidget()
    err_owner.resize(2560, 1392)
    err_owner._quick_surface = _Surf()
    err = SentinelWindow(err_owner)
    monkeypatch.setattr(sentinel_control, "overseer_url", lambda: "http://127.0.0.1:9/#token")
    monkeypatch.setattr(err, "_ensure_view", lambda: None)
    err.refresh()
    assert err.last_error()
    assert err.presence.last_reason == "error"
    assert err.presence.opacity == FADE_CLOSED
    assert err_owner._quick_surface.presenceOpacity == FADE_CLOSED
    err.close()

    assets = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"
    report = json.loads((assets / "export_report.json").read_text())
    by_lod = {row["lod"]: row for row in report}
    assert by_lod[0]["tris"] <= 12000 + 50
    assert by_lod[1]["tris"] <= 4000 + 50
    assert by_lod[2]["tris"] <= 1000 + 50
    assert by_lod[0]["raw_by_part"]["hull"] > 60000
    assert (assets / "meshes/lod0_hull_mesh.mesh").is_file()
    assert (assets / "Sentinel_lod2.qml").is_file()
    scene = win._ensure_scene()
    assert scene is not None
    qt_app.processEvents()
    root = scene.rootObject()
    assert root is not None
    assert root.property("particleBudget") == 520
    qml = (assets / "OverseerView.qml").read_text()
    assert "import QtQuick3D" in qml
    assert "InstanceList" in qml
    assert "CustomMaterial" in qml
    assert "shaders/hull.vert" in qml
    assert "View3D" in qml
    assert "ProceduralMesh" in qml
    assert "casteBandGuides" in qml and "tripwirePerimeter" in qml
    assert 'source: "#Cylinder"' not in qml
    assert "ringPositions" in qml
    assert "overseerBackdrop" in qml
    assert "Math.max(root.fill, 1.0 - root.reveal)" in qml
    assert "cameraDistance: 76" in qml
    assert "scale: Qt.vector3d(0.0012, 0.0012, 0.0012)" in qml
    assert overseer_runtime.DEFAULT_CAMERA_DISTANCE == 76.0
    assert "Qt.vector3d(finiteCoord(row.x), finiteCoord(row.y), finiteCoord(row.z))" in qml
    assert "Qt.vector3d(row.x || 0, row.z || 0, row.y || 0)" not in qml
    assert "Qt.vector3d(0.022, 0.022, 0.022)" in qml
    assert "scale: Qt.vector3d(0.0012, 0.0012, 0.0012)" in qml
    view_qml = scene.source().toLocalFile() if hasattr(scene, "source") else str(assets / "OverseerView.qml")
    assert view_qml.endswith("OverseerView.qml")

    engine = QQmlEngine()
    engine.addImportPath(str(assets))
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(assets / "OverseerView.qml")))
    # Wait briefly if the component is still loading.
    for _ in range(20):
        if comp.status() != QQmlComponent.Status.Loading:
            break
        qt_app.processEvents()
    if comp.status() != QQmlComponent.Status.Ready:
        msgs = "; ".join(err.toString() for err in comp.errors())
        raise AssertionError(f"OverseerView.qml failed to instantiate: {msgs}")
    inst = comp.create()
    assert inst is not None
    qt_app.processEvents()
    inst.setProperty("reveal", 0.0)
    inst.setProperty("fill", 0.0)
    qt_app.processEvents()
    plate_op = None
    backdrop = None
    for child in inst.findChildren(QObject):
        if child.objectName() == "overseerFillPlate":
            plate_op = float(child.property("opacity"))
        if child.objectName() == "overseerBackdrop":
            backdrop = child
    assert backdrop is not None
    assert plate_op is not None and abs(plate_op - 1.0) < 1e-5
    caste_rings = [
        child
        for child in inst.findChildren(QObject)
        if child.objectName() in ("casteBandGuides", "tripwirePerimeter")
    ]
    assert len(caste_rings) == 2
    meshes = [
        child
        for child in inst.findChildren(QObject)
        if "ProceduralMesh" in child.metaObject().className()
    ]
    assert len(meshes) == 2
    for ring in caste_rings:
        src = ring.property("source")
        src_s = src.toString() if src is not None and hasattr(src, "toString") else str(src or "")
        assert "#Cylinder" not in src_s

    def _instance_visibility(root):
        found = {}
        for child in root.findChildren(QObject):
            name = child.objectName()
            if name.startswith("instanced-") or name == "entryParticleCloud":
                found[name] = bool(child.property("visible"))
        return found

    report_map = overseer_runtime.load_mesh_report(assets / "export_report.json")
    # 100 wardens at wide distance: one caste, LOD2, three submeshes.
    wide = [
        {"unit_id": f"SNT-WRD-{i:03d}", "caste": "warden", "position": [i % 10, 0.4, i // 10], "scale": 1.0}
        for i in range(100)
    ]
    frame = overseer_runtime.build_frame(wide, camera_distance=90.0, viewport_h=1306, report=report_map)
    assert frame["budget"]["lodCounts"][2] == 100
    assert frame["budget"]["lodCounts"][0] == 0
    lod2 = report_map[2]["parts"]
    expected_tris = 100 * (lod2["hull"] + lod2["emissive"] + lod2["lens"])
    assert frame["budget"]["unitTris"] == expected_tris
    assert frame["budget"]["unitDrawCalls"] == 3
    assert frame["budget"]["withinTriBudget"]
    assert frame["budget"]["withinDrawBudget"]
    inst.applyFrame(frame)
    qt_app.processEvents()
    assert inst.property("unitDrawCalls") == 3
    assert inst.property("budgetTris") == expected_tris
    assert _qml_list(inst.property("lodCounts"))[2] == 100
    vis = _instance_visibility(inst)
    for part in ("hull", "emissive", "lens"):
        assert vis[f"instanced-warden:2:{part}"] is True
        assert vis[f"instanced-warden:0:{part}"] is False
        assert vis[f"instanced-warden:1:{part}"] is False
        for caste in ("stalker", "harvester", "sanitizer", "tripwire"):
            for lod in range(3):
                assert vis[f"instanced-{caste}:{lod}:{part}"] is False

    # Five castes at wide: 15 instanced models (5 x 3 parts).
    mixed = []
    for caste in overseer_runtime.CASTES:
        for i in range(20):
            mixed.append({"unit_id": f"{caste}-{i}", "caste": caste, "position": [i, 0.4, 0], "scale": 1.0})
    mixed_frame = overseer_runtime.build_frame(mixed, 90.0, 1306, report=report_map)
    assert mixed_frame["budget"]["unitDrawCalls"] == 15
    assert mixed_frame["budget"]["lodCounts"][2] == 100
    inst.applyFrame(mixed_frame)
    qt_app.processEvents()
    assert inst.property("unitDrawCalls") == 15
    vis = _instance_visibility(inst)
    for caste in overseer_runtime.CASTES:
        for part in ("hull", "emissive", "lens"):
            assert vis[f"instanced-{caste}:2:{part}"] is True
            assert vis[f"instanced-{caste}:0:{part}"] is False
            assert vis[f"instanced-{caste}:1:{part}"] is False

    close = [{"unit_id": "hero", "caste": "warden", "position": [0, 0.9, 0], "scale": 1.0}]
    close_frame = overseer_runtime.build_frame(close, 7.0, 1306, report=report_map)
    assert close_frame["units"][0]["lod"] == 0
    assert close_frame["units"][0]["height_px"] > 180
    axis = [{"unit_id": "axis", "caste": "warden", "position": [5.0, 2.5, 9.0], "scale": 1.0}]
    inst.applyFrame(overseer_runtime.build_frame(axis, 32.0, 1306, report=report_map))
    qt_app.processEvents()

    def _unit_instance_entries(root):
        # Skip conduit/source particles (scale ~= spec * 0.0022). Units stay >= 0.20.
        rows = []
        for child in root.findChildren(QObject):
            if "InstanceListEntry" not in child.metaObject().className():
                continue
            pos = child.property("position")
            sc = child.property("scale")
            if pos is None or sc is None:
                continue
            if float(sc.x()) < 0.05:
                continue
            rows.append((pos, sc))
        return rows

    found_pos = None
    for pos, _sc in _unit_instance_entries(inst):
        found_pos = (float(pos.x()), float(pos.y()), float(pos.z()))
        break
    assert found_pos is not None
    assert abs(found_pos[0] - 5.0) < 1e-4
    assert abs(found_pos[1] - 2.5) < 1e-4
    assert abs(found_pos[2] - 9.0) < 1e-4
    boom = [{"unit_id": "boom", "caste": "warden", "position": [999.0, 0.4, 0.0], "scale": 50.0}]
    inst.applyFrame(overseer_runtime.build_frame(boom, 32.0, 1306, report=report_map))
    qt_app.processEvents()
    boom_pos = None
    boom_sc = None
    for pos, sc in _unit_instance_entries(inst):
        boom_pos = (float(pos.x()), float(pos.y()), float(pos.z()))
        boom_sc = (float(sc.x()), float(sc.y()), float(sc.z()))
        break
    assert boom_pos is not None and abs(boom_pos[0]) < 1e-4
    assert abs(boom_pos[1] - 0.4) < 1e-4 and abs(boom_pos[2]) < 1e-4
    assert boom_sc is not None and all(abs(c - 2.0) < 1e-4 for c in boom_sc)
    inst.applyFrame(mixed_frame)
    qt_app.processEvents()

    paths = overseer_runtime.particle_paths(wide, count=520)
    assert len(paths) == 520
    assert sum(1 for p in paths if p["fromMote"]) == 208
    assert sum(1 for p in paths if not p["fromMote"]) == 312
    early = overseer_runtime.particle_position(paths[0], paths[0]["startMs"] - 1)
    assert early[2] == 0.0
    mid = overseer_runtime.particle_position(paths[0], paths[0]["startMs"] + 120)
    assert mid[2] == 1.0
    # Bowed control is above the chord (smaller y).
    assert paths[0]["control"][1] < (paths[0]["start"][1] + paths[0]["end"][1]) / 2

    tl = overseer_runtime.entry_timeline(0)
    assert tl["reveal"] == 0 and tl["edge"] == 0
    tl450 = overseer_runtime.entry_timeline(450)
    assert 0 < float(tl450["edge"]) < 1
    assert 0 < float(tl450["reveal"]) < 1
    tl1600 = overseer_runtime.entry_timeline(1600)
    assert float(tl1600["reveal"]) == 1 and tl1600["inputLive"] is True
    assert float(tl1600["moteFlight"]) == 1
    exit_tl = overseer_runtime.entry_timeline(500, reversing=True)
    assert float(exit_tl["reveal"]) == 0
    red = overseer_runtime.entry_timeline(200, reduced=True)
    assert red["duration"] == 200 and float(red["fade"]) == 0.20

    snap = {"units": [{"unit_id": "SNT-WRD-001", "caste": "warden", "position": [3, 0.9, -4], "state": "ENGAGED_DEFENSE", "heading": [1, 0, 0]}]}
    pushed = win.apply_snapshot(snap)
    assert sum(pushed["budget"]["lodCounts"].values()) == 1
    assert any(pushed["buckets"][k] for k in pushed["buckets"])
    assert overseer_runtime.claw_open("ENGAGED_DEFENSE") == 0.85
    real22 = {"units": []}
    mix = [("harvester", 8), ("warden", 6), ("sanitizer", 4), ("tripwire", 4)]
    n = 0
    for caste, count in mix:
        for i in range(count):
            real22["units"].append({
                "unit_id": f"SNT-{caste[:3].upper()}-{i:03d}",
                "caste": caste,
                "position": [8.0, 0.4, 0.0],
                "state": "PATROLLING",
            })
            n += 1
    assert n == 22
    win.apply_snapshot(real22)
    qt_app.processEvents()
    assert win._hud_labels["units"].text() == "Units 22"
    assert win._hud_labels["harvester"].text() == "Harvest 8"
    assert win._hud_labels["warden"].text() == "Warden 6"
    assert win._hud_labels["sanitizer"].text() == "Sanitize 4"
    assert win._hud_labels["tripwire"].text() == "Tripwire 4"
    assert win._hud_labels["stalker"].text() == "Stalker 0"
    win.apply_snapshot({"demo": True, "units": [{"unit_id": "x", "caste": "warden"}]})
    qt_app.processEvents()
    assert win._hud_labels["units"].text() == "Units 0"

    # Settled snapshots must not rebuild the 520-path entry cloud (CPU fixture).
    path_calls = {"n": 0}
    real_paths = overseer_runtime.particle_paths

    def _count_paths(*args, **kwargs):
        path_calls["n"] += 1
        return real_paths(*args, **kwargs)

    monkeypatch.setattr(overseer_runtime, "particle_paths", _count_paths)
    assert not win._entry_timer.isActive()
    win.apply_snapshot(real22)
    qt_app.processEvents()
    assert path_calls["n"] == 0
    win._entry_timer.start()
    win.apply_snapshot(real22)
    qt_app.processEvents()
    assert path_calls["n"] == 1
    win._entry_timer.stop()
    win.apply_snapshot(real22)
    qt_app.processEvents()
    assert path_calls["n"] == 1

    from arelis import sentinel_control

    scene_root = win._scene.rootObject() if win._scene is not None else None
    assert scene_root is not None
    scene_root.setProperty("cameraDistance", 90.0)
    qt_app.processEvents()
    monkeypatch.setattr(
        sentinel_control, "overseer_url", lambda: "http://127.0.0.1:9/#tok"
    )
    monkeypatch.setattr(
        sentinel_control, "bridge_target", lambda: ("127.0.0.1", 9, "tok")
    )
    real_fetch = overseer_runtime.fetch_snapshot
    monkeypatch.setattr(
        overseer_runtime, "fetch_snapshot", lambda *args, **kwargs: real22
    )
    win.start_entry_sequence()
    qt_app.processEvents()
    assert win._hud_labels["units"].text() == "Units 22"
    monkeypatch.setattr(overseer_runtime, "fetch_snapshot", real_fetch)
    assert abs(
        float(scene_root.property("cameraDistance"))
        - overseer_runtime.DEFAULT_CAMERA_DISTANCE
    ) < 1e-3
    assert abs(
        float(scene_root.property("cameraPitch"))
        - overseer_runtime.pitch_deg(overseer_runtime.DEFAULT_CAMERA_DISTANCE)
    ) < 1e-3

    fake_demo = overseer_runtime.snapshot_units({"demo": True, "units": [{"unit_id": "x"}]})
    assert fake_demo == []

    rects = overseer_runtime.hud_mask_rects(2110, 1306)
    assert overseer_runtime.point_in_rects(20, 20, rects)
    assert overseer_runtime.point_in_rects(100, 40, rects)
    assert not overseer_runtime.point_in_rects(800, 400, rects)
    assert overseer_runtime.point_in_rects(1800, 200, rects)
    full = overseer_runtime.hud_mask_rects(2110, 1306, full=True)
    assert overseer_runtime.point_in_rects(800, 400, full)
    emp = overseer_runtime.hud_mask_rects(2110, 1306, emp=True)
    assert overseer_runtime.point_in_rects(1055, 100, emp)

    def _opener(req, timeout=2.0):
        token = req.get_header("X-sentinel-token") or req.get_header("X-Sentinel-Token")
        assert token == "secret-token"
        class _Resp:
            def read(self):
                return json.dumps(snap).encode()
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        return _Resp()
    got = overseer_runtime.fetch_snapshot("127.0.0.1", 9, "secret-token", opener=_opener)
    assert got["units"][0]["unit_id"] == "SNT-WRD-001"

    for name in ("hull.vert", "hull.frag", "emissive.vert", "emissive.frag", "lens.vert", "lens.frag"):
        text = (assets / "shaders" / name).read_text()
        assert "void MAIN()" in text
    assert "INSTANCE_DATA" in (assets / "shaders" / "hull.vert").read_text()
    shader_errors = overseer_runtime.validate_overseer_shaders(assets / "shaders")
    assert shader_errors == [], shader_errors
    hull_vert = (assets / "shaders" / "hull.vert").read_text()
    assert "uTime" in hull_vert
    assert "INSTANCE_DATA.x + uTime" in hull_vert
    assert "clamp(limpBit, 0.0, 1.0)" in hull_vert
    assert "clamp(limpBit, 0.0, 1.0)" in (
        assets / "shaders" / "emissive.vert"
    ).read_text()
    assert "uTime: root.sceneTime" in qml
    # Pause the live clock in this fixture only so sceneTime stays put.
    # Production FrameAnimation is left unchanged.
    paused = 0
    for child in inst.findChildren(QObject):
        if "FrameAnimation" in child.metaObject().className():
            child.setProperty("running", False)
            paused += 1
    assert paused >= 1, "expected a FrameAnimation to pause for the binding check"
    inst.setProperty("sceneTime", 2.5)
    qt_app.processEvents()
    sticky = float(inst.property("sceneTime"))
    assert abs(sticky - 2.5) < 1e-6, sticky
    material_times = []
    for child in inst.findChildren(QObject):
        cls = child.metaObject().className()
        if "CustomMaterial" in cls:
            ut = child.property("uTime")
            if ut is not None:
                material_times.append(float(ut))
    assert material_times, "CustomMaterial uTime was not instantiated"
    assert any(abs(t - sticky) < 1e-5 for t in material_times), (sticky, material_times)
    inst.setProperty("sceneTime", 4.0)
    qt_app.processEvents()
    follow = float(inst.property("sceneTime"))
    assert abs(follow - 4.0) < 1e-6, follow
    followed = []
    for child in inst.findChildren(QObject):
        if "CustomMaterial" in child.metaObject().className():
            ut = child.property("uTime")
            if ut is not None:
                followed.append(float(ut))
    assert any(abs(t - follow) < 1e-5 for t in followed), (follow, followed)

    # Accounting budget at 100 units: clustered close, mixed rings close/mid/wide.
    close_cluster = overseer_runtime.build_frame(
        overseer_runtime.clustered_swarm(100), 7.0, 1306, report=report_map
    )
    assert close_cluster["budget"]["unitTris"] <= overseer_runtime.MAX_TRIS
    assert close_cluster["budget"]["withinTriBudget"]
    assert close_cluster["budget"]["withinDrawBudget"]
    assert close_cluster["budget"]["unitDrawCalls"] <= overseer_runtime.MAX_UNIT_DRAW
    # Without demotion this clustered close scene is ~1.2M tris.
    raw_lod0 = 100 * sum(report_map[0]["parts"][part] for part in overseer_runtime.PARTS)
    assert raw_lod0 > overseer_runtime.MAX_TRIS
    assert close_cluster["budget"]["unitTris"] < raw_lod0

    mixed_close = overseer_runtime.build_frame(
        overseer_runtime.layout_swarm(100), 7.0, 1306, report=report_map
    )
    mixed_mid = overseer_runtime.build_frame(
        overseer_runtime.layout_swarm(100), 32.0, 1306, report=report_map
    )
    mixed_wide = overseer_runtime.build_frame(
        overseer_runtime.layout_swarm(100), 90.0, 1306, report=report_map
    )
    for named, framed in (("close", mixed_close), ("mid", mixed_mid), ("wide", mixed_wide)):
        assert framed["budget"]["unitTris"] <= overseer_runtime.MAX_TRIS, named
        assert framed["budget"]["unitDrawCalls"] <= overseer_runtime.MAX_UNIT_DRAW, named
        assert framed["budget"]["drawCalls"] <= 80, named

    # Native wheel maps onto the renderer camera (dolly + pitch).
    start_d = float(inst.property("cameraDistance"))
    inst.applyWheel(-1)
    qt_app.processEvents()
    zoomed = float(inst.property("cameraDistance"))
    assert abs(zoomed - overseer_runtime.wheel_step(start_d, -1)) < 1e-4
    assert abs(float(inst.property("cameraPitch")) - overseer_runtime.pitch_deg(zoomed)) < 1e-3
    # Rubber-band: cannot run past 8% beyond the 6..110 m limits.
    inst.setProperty("cameraDistance", 6.0)
    inst.applyWheel(-8)
    qt_app.processEvents()
    assert float(inst.property("cameraDistance")) >= overseer_runtime.ZOOM_MIN * (
        1.0 - overseer_runtime.RUBBER
    )

    visible0 = [{"x": 1, "y": 0, "z": 0, "visible": 0}]
    inst.setParticles(visible0)
    qt_app.processEvents()
    hidden = _entry_count(inst)
    assert _instance_visibility(inst)["entryParticleCloud"] is False
    inst.setParticles([{"x": 1, "y": 0, "z": 0, "visible": 1}])
    qt_app.processEvents()
    shown = _entry_count(inst)
    assert shown == hidden + 1
    assert _instance_visibility(inst)["entryParticleCloud"] is True

    # Repeated applyFrame / setParticles must reuse entries (bounded QObject count).
    fifty = overseer_runtime.build_frame(
        [{"unit_id": f"P-{i}", "caste": "warden", "position": [i, 0.4, 0], "scale": 1.0} for i in range(50)],
        90.0,
        1306,
        report=report_map,
    )
    inst.applyFrame(fifty)
    qt_app.processEvents()
    baseline = _entry_count(inst)
    assert baseline > 0
    for _ in range(12):
        inst.applyFrame(fifty)
        inst.setParticles([{"x": i * 0.1, "y": 0, "z": 0, "visible": 1} for i in range(40)])
        qt_app.processEvents()
    after_loop = _entry_count(inst)
    assert after_loop == baseline, (baseline, after_loop)

    # Close/reopen the QML scene: a fresh root stays bounded to one frame's entries.
    inst.deleteLater()
    qt_app.processEvents()
    inst2 = comp.create()
    assert inst2 is not None
    qt_app.processEvents()
    inst2.applyFrame(fifty)
    inst2.setParticles([{"x": 0, "y": 0, "z": 0, "visible": 1} for _ in range(40)])
    qt_app.processEvents()
    reopened = _entry_count(inst2)
    assert reopened <= baseline
    inst2.applyFrame(fifty)
    inst2.setParticles([{"x": 0, "y": 0, "z": 0, "visible": 1} for _ in range(40)])
    qt_app.processEvents()
    assert _entry_count(inst2) == reopened
    inst2.deleteLater()
    qt_app.processEvents()


_ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"
_CLIP = "POSITION = INSTANCE_MODELVIEWPROJECTION_MATRIX * vec4"
_WAVE_NEEDLES = (
    "1.0 - smoothstep(-0.55, 0.15,",
    "INSTANCE_DATA.x + uTime",
    "clamp(limpBit, 0.0, 1.0)",
    "0.16 * tail * mix(1.0, 0.25, limp)",
    "* 5.5 + phase",
    "* 4.2 + phase * 1.7",
    "* amp * 0.7",
)


def _emissive_local_clip_errors(text: str) -> list[str]:
    errors: list[str] = []
    if "vec3 deformed = VERTEX;" not in text:
        errors.append("emissive.vert: missing local deformed store")
    if "VERTEX =" in text:
        errors.append("emissive.vert: assigns VERTEX")
    if f"{_CLIP}(deformed, 1.0);" not in text:
        errors.append("emissive.vert: missing POSITION from deformed")
    for needle in _WAVE_NEEDLES:
        if needle not in text:
            errors.append(f"emissive.vert: missing wave {needle!r}")
    return errors


def _lens_clip_errors(text: str) -> list[str]:
    errors: list[str] = []
    if f"{_CLIP}(VERTEX, 1.0);" not in text:
        errors.append("lens.vert: missing explicit POSITION clip")
    if "VERTEX =" in text:
        errors.append("lens.vert: assigns VERTEX")
    if "INSTANCE_DATA" in text or "sin(" in text:
        errors.append("lens.vert: unexpected wave inputs")
    return errors


def test_overseer_emissive_clips_wave_from_local_store() -> None:
    text = (_ASSETS / "shaders" / "emissive.vert").read_text()
    assert _emissive_local_clip_errors(text) == []
    mutated = text.replace(
        f"{_CLIP}(deformed, 1.0);",
        "VERTEX = deformed;\n    "
        f"{_CLIP}(VERTEX, 1.0);",
    )
    assert mutated != text
    assert _emissive_local_clip_errors(mutated)


def test_overseer_lens_writes_explicit_clip_position() -> None:
    text = (_ASSETS / "shaders" / "lens.vert").read_text()
    assert _lens_clip_errors(text) == []
    mutated = text.replace(
        f"{_CLIP}(VERTEX, 1.0);",
        "VERTEX = VERTEX;",
    )
    assert mutated != text
    assert _lens_clip_errors(mutated)

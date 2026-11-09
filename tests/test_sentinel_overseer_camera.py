"""Batch C camera: target vs hive, focus geometry, live evidence, wheel persist."""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView

from arelis.ui import overseer_runtime
from arelis.ui.sentinel_host import SentinelWindow, teardown_sentinel_window
from tests.overseer_render_helpers import isolated_render

VIEW_QML = (
    Path(__file__).resolve().parents[1]
    / "arelis/assets/sentinel/overseer/OverseerView.qml"
)
ASSETS = VIEW_QML.parent


def _units() -> list[dict]:
    return [
        {
            "unit_id": "SNT-WRD-001",
            "caste": "warden",
            "state": "ENGAGED_DEFENSE",
            "position": [11.2, 1.0, -9.2],
            "tentacles": 12,
        },
        {
            "unit_id": "SNT-HRV-001",
            "caste": "harvester",
            "state": "PATROLLING",
            "position": [-8.0, 0.4, 6.5],
            "tentacles": 7,
        },
    ]


def _view(qt_app):
    view = QQuickView()
    view.engine().addImportPath(str(ASSETS))
    view.setColor(QColor("#0b0714"))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.setSource(QUrl.fromLocalFile(str(VIEW_QML)))
    if view.status() != QQuickView.Status.Ready:
        raise AssertionError("; ".join(err.toString() for err in view.errors()))
    view.resize(900, 700)
    view.show()
    qt_app.processEvents()
    root = view.rootObject()
    assert root is not None
    return view, root


def test_overseer_pitch_passes_approved_close_mid_wide() -> None:
    assert overseer_runtime.pitch_deg(6.0) == 22.0
    assert overseer_runtime.pitch_deg(9.0) == 22.0
    assert abs(overseer_runtime.pitch_deg(32.0) - 36.0) < 1e-9
    assert abs(overseer_runtime.pitch_deg(96.0) - 55.0) < 1e-9
    assert overseer_runtime.pitch_deg(110.0) == 55.0
    linear_mid = 22.0 + overseer_runtime.zoom_t(32.0) * (55.0 - 22.0)
    assert abs(overseer_runtime.pitch_deg(32.0) - linear_mid) > 1.0
    assert overseer_runtime.framing_name(7.0) == "close"
    assert overseer_runtime.framing_name(32.0) == "mid"
    assert overseer_runtime.framing_name(96.0) == "wide"
    assert overseer_runtime.framing_name(12.0) == "unclassified"


@isolated_render()
def test_overseer_camera_focus_uses_snapshot_geometry(qt_app) -> None:
    view, root = _view(qt_app)
    root.applyUnits(_units())
    qt_app.processEvents()
    root.selectUnit("SNT-WRD-001")
    qt_app.processEvents()
    assert str(root.property("selectedUnitId")) == "SNT-WRD-001"
    pos = overseer_runtime.unit_view_pos(_units()[0])
    assert abs(float(root.property("cameraTargetX")) - pos[0]) < 1e-4
    assert abs(float(root.property("cameraTargetY")) - pos[1]) < 1e-4
    assert abs(float(root.property("cameraTargetZ")) - pos[2]) < 1e-4
    assert root.focusSelectedUnit() is True
    qt_app.processEvents()
    assert float(root.property("cameraDistance")) == overseer_runtime.CLOSE_DISTANCE
    assert abs(float(root.property("cameraPitch")) - overseer_runtime.pitch_deg(overseer_runtime.CLOSE_DISTANCE)) < 1e-3
    root.selectUnit("SNT-HRV-001")
    root.focusSelectedUnit()
    qt_app.processEvents()
    other = overseer_runtime.unit_view_pos(_units()[1])
    assert abs(float(root.property("cameraTargetX")) - other[0]) < 1e-4
    assert abs(float(root.property("cameraTargetX")) - pos[0]) > 1.0
    held = float(root.property("cameraTargetX"))
    root.selectUnit("SNT-MISSING")
    assert root.focusSelectedUnit() is False
    assert abs(float(root.property("cameraTargetX")) - held) < 1e-4
    assert overseer_runtime.focus_framing({"unit_id": "SNT-NONE"}) is None
    view.deleteLater()
    qt_app.processEvents()


@isolated_render()
def test_overseer_wheel_keeps_selection_and_frames_target(qt_app) -> None:
    view, root = _view(qt_app)
    root.applyUnits(_units())
    qt_app.processEvents()
    root.selectUnit("SNT-WRD-001")
    start = float(root.property("cameraDistance"))
    root.applyWheel(-10)
    qt_app.processEvents()
    assert str(root.property("selectedUnitId")) == "SNT-WRD-001"
    assert float(root.property("cameraDistance")) < start
    pos = overseer_runtime.unit_view_pos(_units()[0])
    assert abs(float(root.property("cameraTargetX")) - pos[0]) < 1e-3
    assert abs(float(root.property("cameraPitch")) - overseer_runtime.pitch_deg(
        float(root.property("cameraDistance"))
    )) < 1e-3
    # Hit-focus: a live pivot slides the target; clearing it does not invent a unit.
    root.setWheelPivot(1.0, 0.0, 0.0)
    old_t = (
        float(root.property("cameraTargetX")),
        float(root.property("cameraTargetY")),
        float(root.property("cameraTargetZ")),
    )
    old_d = float(root.property("cameraDistance"))
    root.applyWheel(-1)
    qt_app.processEvents()
    new_d = float(root.property("cameraDistance"))
    expected = overseer_runtime.cursor_dolly(old_t, (1.0, 0.0, 0.0), old_d, new_d)
    assert abs(float(root.property("cameraTargetX")) - expected[0]) < 1e-3
    root.clearWheelPivot()
    root.selectUnit("")
    root.setCameraTarget(0, 0, 0)
    root.applyWheel(-1)
    qt_app.processEvents()
    assert str(root.property("selectedUnitId") or "") == ""
    assert abs(float(root.property("cameraTargetX"))) < 1e-6
    assert abs(float(root.property("cameraTargetZ"))) < 1e-6
    view.deleteLater()
    qt_app.processEvents()


@isolated_render()
def test_overseer_camera_evidence_is_live_not_default(qt_app) -> None:
    view, root = _view(qt_app)
    root.applyUnits(_units())
    qt_app.processEvents()
    root.selectUnit("SNT-WRD-001")
    root.focusSelectedUnit()
    qt_app.processEvents()
    ev = root.cameraEvidence()
    if hasattr(ev, "toVariant"):
        ev = ev.toVariant()
    assert ev["cameraDistance"] == float(root.property("cameraDistance"))
    assert ev["cameraPitch"] == float(root.property("cameraPitch"))
    assert ev["selectedUnitId"] == "SNT-WRD-001"
    assert ev["framing"] == "mid"
    assert ev["cameraDistance"] != overseer_runtime.DEFAULT_CAMERA_DISTANCE
    blank = overseer_runtime.camera_evidence(None, None)
    assert blank == {}
    fitted = ev["cameraDistance"]
    root.fitSwarm()
    qt_app.processEvents()
    assert abs(float(root.property("cameraDistance")) - 96.0) < 1e-6
    assert float(root.property("cameraDistance")) != fitted
    assert abs(float(root.property("cameraPitch")) - 55.0) < 1e-6
    view.deleteLater()
    qt_app.processEvents()


@isolated_render()
def test_overseer_snapshot_refresh_keeps_selection_and_focus(qt_app) -> None:
    from PySide6.QtWidgets import QWidget

    owner = QWidget()
    owner.resize(1280, 800)
    win = SentinelWindow(owner)
    owner.sentinel_window = win
    win.resize(1280, 800)
    scene = win._ensure_scene()
    assert scene is not None
    win.show()
    qt_app.processEvents()
    root = scene.rootObject()
    if root is None:
        teardown_sentinel_window(win)
        return
    units = _units()
    snap = {
        "metrics": {},
        "units": units,
        "castes": [],
        "recent_receipts": [],
        "telemetry_log": [],
    }
    root.applyUnits(units)
    qt_app.processEvents()
    root.selectUnit("SNT-WRD-001")
    root.focusSelectedUnit()
    qt_app.processEvents()
    dist = float(root.property("cameraDistance"))
    win.apply_snapshot(snap)
    qt_app.processEvents()
    root.applyWheel(-10)
    qt_app.processEvents()
    win.apply_snapshot(snap)
    qt_app.processEvents()
    assert str(root.property("selectedUnitId")) == "SNT-WRD-001"
    card = root.property("inspectorCard")
    if hasattr(card, "toVariant"):
        card = card.toVariant()
    assert (card or {}).get("unit_id") == "SNT-WRD-001"
    report = win.camera_report()
    assert report.get("selectedUnitId") == "SNT-WRD-001"
    assert "cameraDistance" in report
    assert report["cameraDistance"] != overseer_runtime.DEFAULT_CAMERA_DISTANCE or dist == overseer_runtime.DEFAULT_CAMERA_DISTANCE
    pos = overseer_runtime.unit_view_pos(units[0])
    assert abs(report["cameraTargetX"] - pos[0]) < 1e-3
    teardown_sentinel_window(win)
    qt_app.processEvents()


def test_overseer_free_viewport_lens_shift_changes_with_inspector() -> None:
    open_shift = overseer_runtime.free_viewport_shift(2110, 1306, True)
    closed_shift = overseer_runtime.free_viewport_shift(2110, 1306, False)
    assert open_shift != closed_shift
    assert abs(open_shift[0]) > 0 or abs(open_shift[1]) > 0


def _named_text(root, name: str):
    matches = [item for item in root.findChildren(root.__class__) if item.objectName() == name]
    if matches:
        return matches[0]
    from PySide6.QtQuick import QQuickItem
    for item in root.findChildren(QQuickItem):
        if item.objectName() == name:
            return item
    if root.objectName() == name:
        return root
    return None


@isolated_render()
def test_overseer_camera_evidence_exposes_named_accessible_values(qt_app) -> None:
    view, root = _view(qt_app)
    root.applyUnits(_units())
    qt_app.processEvents()
    root.selectUnit("SNT-WRD-001")
    root.focusSelectedUnit()
    qt_app.processEvents()
    ev = root.cameraEvidence()
    if hasattr(ev, "toVariant"):
        ev = ev.toVariant()
    distance = _named_text(root, "OverseerCameraDistance")
    pitch = _named_text(root, "OverseerCameraPitch")
    target_x = _named_text(root, "OverseerCameraTargetX")
    selected = _named_text(root, "OverseerCameraSelectedUnitId")
    framing = _named_text(root, "OverseerCameraFraming")
    combined = _named_text(root, "OverseerCameraEvidence")
    assert distance is not None and pitch is not None and target_x is not None
    assert selected is not None and framing is not None and combined is not None
    assert float(distance.property("text")) == float(ev["cameraDistance"])
    assert float(pitch.property("text")) == float(ev["cameraPitch"])
    assert float(target_x.property("text")) == float(ev["cameraTargetX"])
    assert str(selected.property("text")) == "SNT-WRD-001"
    assert str(framing.property("text")) == "mid"
    label = str(combined.property("text") or "")
    assert "cameraDistance=" in label
    assert str(distance.property("text")) in label
    blank = overseer_runtime.camera_evidence(None, None)
    assert blank == {}
    view.deleteLater()
    qt_app.processEvents()


@isolated_render()
def test_overseer_fit_swarm_is_local_and_accessible(qt_app) -> None:
    view, root = _view(qt_app)
    root.applyUnits(_units())
    qt_app.processEvents()
    root.selectUnit("SNT-WRD-001")
    root.focusSelectedUnit()
    qt_app.processEvents()
    assert float(root.property("cameraDistance")) == overseer_runtime.CLOSE_DISTANCE
    button = _named_text(root, "OverseerAction_fitSwarm")
    assert button is not None
    assert bool(button.property("enabled")) is True
    labels = [str(child.property("text") or "") for child in button.childItems()]
    assert "Fit swarm" in labels
    plan = overseer_runtime.resolve_hud_command("fit_swarm", {}, selected_unit=_units()[0])
    assert plan["ok"] is True
    assert plan.get("local") is True
    assert plan["path"] is None
    assert plan["body"] is None
    hud = _named_text(root, "OverseerHud")
    assert hud is not None
    hud.hudCommand.emit("fit_swarm", {})
    qt_app.processEvents()
    assert abs(float(root.property("cameraDistance")) - 96.0) < 1e-6
    assert abs(float(root.property("cameraPitch")) - 55.0) < 1e-6
    assert abs(float(root.property("cameraTargetX"))) < 1e-6
    assert abs(float(root.property("cameraTargetZ"))) < 1e-6
    view.deleteLater()
    qt_app.processEvents()


def test_overseer_focus_projects_selected_unit_to_free_viewport() -> None:
    unit = _units()[0]
    pos = overseer_runtime.unit_view_pos(unit)
    width, height = 2110.0, 1306.0
    distance = overseer_runtime.CLOSE_DISTANCE
    pitch = overseer_runtime.pitch_deg(distance)
    px, py = overseer_runtime.project_world_to_viewport(
        pos, distance, pitch, pos, width, height, True,
    )
    cx, cy = overseer_runtime.free_viewport_center(width, height, True)
    assert abs(px - cx) < 1.0
    assert abs(py - cy) < 1.0
    hive = overseer_runtime.project_world_to_viewport(
        overseer_runtime.HIVE_TARGET, distance, pitch, pos, width, height, True,
    )
    # Hive is either behind the close camera (no projection) or well off
    # the free-viewport centre — not the Focus subject.
    assert math.isnan(hive[0]) or abs(hive[0] - cx) > 80 or abs(hive[1] - cy) > 80
    full_frac = overseer_runtime.projected_height_px(distance, height, 1.0) / height
    # UNIT_WORLD_H 1.56 at 7 m and 35 deg is about 35% of the full plate,
    # about 47% of the free well — not 60%. Do not retune FOV or height here.
    assert 0.05 < full_frac < 0.25
    well_h = height - 86.0 - 230.0
    assert full_frac * height < well_h * 0.5
    unshifted = overseer_runtime.project_world_to_viewport(
        pos, distance, pitch, pos, width, height, False,
    )
    assert unshifted != (px, py)


def _parse_evidence_line(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in str(text or "").split():
        if "=" in part:
            key, value = part.split("=", 1)
            parsed[key] = value
    return parsed


@isolated_render()
def test_overseer_fit_swarm_does_not_follow_selection_on_refresh(qt_app) -> None:
    from PySide6.QtWidgets import QWidget

    owner = QWidget()
    owner.resize(1280, 800)
    win = SentinelWindow(owner)
    owner.sentinel_window = win
    win.resize(1280, 800)
    scene = win._ensure_scene()
    assert scene is not None
    win.show()
    qt_app.processEvents()
    root = scene.rootObject()
    if root is None:
        teardown_sentinel_window(win)
        return
    units = _units()
    snap = {
        "metrics": {},
        "units": units,
        "castes": [],
        "recent_receipts": [],
        "telemetry_log": [],
    }
    win.apply_snapshot(snap)
    qt_app.processEvents()
    root.selectUnit("SNT-HRV-001")
    root.focusSelectedUnit()
    qt_app.processEvents()
    pos = overseer_runtime.unit_view_pos(units[1])
    assert abs(float(root.property("cameraTargetX")) - pos[0]) < 1e-3
    root.fitSwarm()
    qt_app.processEvents()
    assert str(root.property("cameraMode")) == "fit"
    assert str(root.property("selectedUnitId")) == "SNT-HRV-001"
    assert abs(float(root.property("cameraDistance")) - 96.0) < 1e-6
    assert abs(float(root.property("cameraTargetX"))) < 1e-6
    assert abs(float(root.property("cameraTargetZ"))) < 1e-6
    win.apply_snapshot(snap)
    qt_app.processEvents()
    assert str(root.property("selectedUnitId")) == "SNT-HRV-001"
    assert str(root.property("cameraMode")) == "fit"
    assert abs(float(root.property("cameraDistance")) - 96.0) < 1e-6
    assert abs(float(root.property("cameraPitch")) - 55.0) < 1e-6
    assert abs(float(root.property("cameraTargetX"))) < 1e-6
    assert abs(float(root.property("cameraTargetY"))) < 1e-6
    assert abs(float(root.property("cameraTargetZ"))) < 1e-6
    root.selectUnit("SNT-WRD-001")
    qt_app.processEvents()
    assert str(root.property("selectedUnitId")) == "SNT-WRD-001"
    assert str(root.property("cameraMode")) == "fit"
    assert abs(float(root.property("cameraTargetX"))) < 1e-6
    teardown_sentinel_window(win)
    qt_app.processEvents()


@isolated_render()
def test_overseer_frame_dump_reports_selected_instance(qt_app) -> None:
    view, root = _view(qt_app)
    root.applyUnits(_units())
    qt_app.processEvents()
    root.selectUnit("SNT-HRV-001")
    qt_app.processEvents()
    named = _named_text(root, "OverseerFrameDump")
    mode = _named_text(root, "OverseerCameraMode")
    assert named is not None and mode is not None
    text = str(named.property("text") or "")
    direct = root.frameDump()
    parsed = _parse_evidence_line(text)
    assert parsed.get("selectedId") == "SNT-HRV-001"
    assert parsed.get("selectedCaste") == "harvester"
    assert "harvester" in parsed.get("modelKey", "")
    assert "hull" in parsed.get("modelKey", "")
    pos = overseer_runtime.unit_view_pos(_units()[1])
    assert abs(float(parsed["instanceX"]) - pos[0]) < 1e-4
    assert abs(float(parsed["instanceY"]) - pos[1]) < 1e-4
    assert abs(float(parsed["instanceZ"]) - pos[2]) < 1e-4
    assert abs(float(parsed["rememberedX"]) - pos[0]) < 1e-4
    assert abs(float(parsed["rememberedY"]) - pos[1]) < 1e-4
    assert abs(float(parsed["rememberedZ"]) - pos[2]) < 1e-4
    assert parsed.get("cameraMode") == "follow"
    assert "8fd3ff" in parsed.get("instanceColor", "").lower()
    assert int(parsed["frameId"]) >= 1
    assert parsed.get("cameraFov") == "35"
    assert str(mode.property("text")) == "follow"
    assert "selectedId=SNT-HRV-001" in str(direct)
    view.deleteLater()
    qt_app.processEvents()

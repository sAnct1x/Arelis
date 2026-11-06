"""Batch C camera: target vs hive, focus geometry, live evidence, wheel persist."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView

from arelis.ui import overseer_runtime
from arelis.ui.sentinel_host import SentinelWindow, teardown_sentinel_window

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
    assert 6.0 <= float(root.property("cameraDistance")) <= 9.0
    assert abs(float(root.property("cameraPitch")) - 22.0) < 1e-3
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
    assert ev["framing"] == "close"
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

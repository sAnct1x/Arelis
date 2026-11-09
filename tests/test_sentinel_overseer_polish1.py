"""Overseer polish 1: rose only for real threats, honest labels and tooltips."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem

from arelis.ui import overseer_runtime

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"
ROSE = "#f43f5e"


def _beam_colors(state: str) -> set[str]:
    warden = {
        "unit_id": "SNT-WRD-001",
        "caste": "warden",
        "state": state,
        "position": [10.0, 0.6, 0.0],
        "laser_active": True,
        "laser_kind": "defense",
        "target_position": [20.0, 0.4, 0.0],
    }
    frame = overseer_runtime.build_frame([warden], 90.0, 1306)
    return {c["color"] for c in frame["conduits"] if c["kind"] == "beam"}


def _items(item: QQuickItem):
    yield item
    for child in item.childItems():
        yield from _items(child)


def test_routine_warden_patrol_beam_is_not_threat_rose() -> None:
    # Every Warden laser carries laser_kind "defense"; only a real engagement is rose.
    assert _beam_colors("VECTORING") == {overseer_runtime.CASTE_COLOR["warden"]}
    assert _beam_colors("ENGAGED_DEFENSE") == {ROSE}


def test_patrol_stream_ignores_the_hive_eye_colour_unless_carrying_an_orb() -> None:
    # The hive sends orb_color = caste eye colour on every unit (Warden #ff2a3a), so
    # four patrolling Wardens drew rose packets to the hive at Threats 0 (Atria, 168 px).
    warden = {
        "unit_id": "SNT-WRD-001", "caste": "warden", "state": "VECTORING",
        "position": [10.0, 0.6, 0.0], "orb_color": "#ff2a3a", "carrying_orb": False,
    }
    frame = overseer_runtime.build_frame([warden], 90.0, 1306)
    streams = {c["color"] for c in frame["conduits"] if c["id"].startswith("hive-conduit:")}
    assert streams == {overseer_runtime.CASTE_COLOR["warden"]}


def test_local_camera_commands_leave_no_console_status() -> None:
    selected = {"unit_id": "SNT-WRD-001", "caste": "warden"}
    focus = overseer_runtime.resolve_hud_command("focus", {}, selected_unit=selected)
    fit = overseer_runtime.resolve_hud_command("fit_swarm", {}, selected_unit=selected)
    assert focus["ok"] and fit["ok"]
    assert focus["status"] == "" and fit["status"] == ""


def test_hud_warrants_tooltip_labels_and_placeholders(qt_app) -> None:
    engine = QQmlEngine()
    engine.addImportPath(str(ASSETS))
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(ASSETS / "OverseerHud.qml")))
    if comp.status() != QQmlComponent.Status.Ready:
        raise AssertionError("; ".join(err.toString() for err in comp.errors()))
    hud = comp.create()
    assert hud is not None
    try:
        hud.setProperty("width", 2110)
        hud.setProperty("pills", {"warrants": 238, "threats": 0})
        qt_app.processEvents()
        items = list(_items(hud))
        pill = next(i for i in items if i.objectName() == "OverseerStrip_warrants")
        tips = [
            str(o.property("text"))
            for o in pill.findChildren(QObject)
            if "ToolTipAttached" in o.metaObject().className()
        ]
        assert tips == ["Evidence receipts in memory (includes up to 120 from earlier runs)"]
        texts = {str(i.property("text")) for i in items if i.property("text")}
        assert {"Caste", "Task", "Ring"} <= texts
        assert not {"caste", "task", "ring"} & texts
        assert any(t.startswith("Mode: ") for t in texts)
        for name in ("OverseerSwarmSearch", "OverseerMissionQuery", "OverseerLogSearch"):
            field = hud.findChild(QObject, name)
            assert field.property("placeholderTextColor").name() == "#a090d4", name
    finally:
        hud.deleteLater()
        qt_app.processEvents()

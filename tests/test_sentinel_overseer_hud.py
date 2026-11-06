"""Batch A HUD: pills, virtualized swarm list, inspector, console. Isolated QML."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QColor
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from arelis.ui import overseer_runtime
from arelis.ui.sentinel_host import SentinelWindow, teardown_sentinel_window

HUD_QML = (
    Path(__file__).resolve().parents[1]
    / "arelis/assets/sentinel/overseer/OverseerHud.qml"
)
ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"


def _units() -> list[dict]:
    return [
        {"unit_id": "SNT-WRD-002", "caste": "warden", "state": "PATROLLING", "tentacles": 12},
        {"unit_id": "SNT-WRD-001", "caste": "warden", "state": "ENGAGED_DEFENSE", "target_node_id": "THREAT-1", "tentacles": 12},
        {"unit_id": "SNT-HRV-001", "caste": "harvester", "state": "PATROLLING", "current_task": "gather ingress", "tentacles": 7},
    ]


def _snap() -> dict:
    return {
        "metrics": {"warrants_minted": 3, "security_events": 2},
        "units": _units(),
        "castes": [{"caste_id": "warden", "allowed_capabilities": ["intercept", "defend"]}],
        "recent_receipts": [{"unit_id": "SNT-WRD-001", "sha256": "abc123def"}],
        "telemetry_log": [
            {"seq": 1, "unit_id": "SNT-WRD-001", "caste": "warden", "level": "ALERT", "message": "hold the line"},
            {"seq": 2, "unit_id": "SNT-HRV-001", "caste": "harvester", "level": "HARVEST", "message": "packet in"},
        ],
    }


def test_overseer_pills_match_snapshot_metrics() -> None:
    pills = overseer_runtime.pill_counts(_units(), _snap()["metrics"])
    assert pills["units"] == 3
    assert pills["warden"] == 2
    assert pills["harvester"] == 1
    assert pills["stalker"] == 0
    assert pills["warrants"] == 3
    assert pills["threats"] == 2
    missing = overseer_runtime.pill_counts(_units(), None)
    assert missing["warrants"] == "unavailable"
    assert missing["threats"] == "unavailable"
    mutated = dict(pills)
    mutated["warrants"] = 99
    assert mutated["warrants"] != overseer_runtime.pill_counts(_units(), _snap()["metrics"])["warrants"]


def test_overseer_swarm_list_groups_virtualizes_and_selects() -> None:
    rows = overseer_runtime.swarm_rows(_units(), by="caste")
    kinds = [row["kind"] for row in rows]
    assert kinds[0] == "header"
    warden = next(row for row in rows if row["kind"] == "header" and row["key"] == "warden")
    assert warden["count"] == 2
    assert warden["active"] == 1
    unit_ids = [row["unit_id"] for row in rows if row["kind"] == "unit" and row["caste"] == "warden"]
    assert unit_ids[0] == "SNT-WRD-001"
    searched = overseer_runtime.swarm_rows(_units(), by="caste", query="HRV")
    assert [row["unit_id"] for row in searched if row["kind"] == "unit"] == ["SNT-HRV-001"]
    collapsed = overseer_runtime.swarm_rows(_units(), by="caste", collapsed={"warden"})
    assert not [row for row in collapsed if row.get("caste") == "warden"]
    window = overseer_runtime.virtual_window(0, 44 * 23, 34, row_h=44, pool=6)
    assert window["rowH"] == 44
    assert window["alive"] == 23 + 6
    mutated = overseer_runtime.virtual_window(0, 44 * 23, 34, row_h=40, pool=6)
    assert mutated["alive"] != window["alive"] or mutated["rowH"] != 44


def test_overseer_inspector_live_fields_and_zoom_collapse() -> None:
    card = overseer_runtime.inspector_card(
        _units()[1],
        castes=_snap()["castes"],
        receipts=_snap()["recent_receipts"],
    )
    assert card["state"] == "ENGAGED_DEFENSE"
    assert card["target"] == "THREAT-1"
    assert card["tentacles"] == 12
    assert card["capabilities"] == "intercept, defend"
    assert card["warrant_hash"] == "abc123def"
    assert card["last_action"] == "unavailable"
    assert card["time_on_task"] == "unavailable"
    assert card["eyes"] == "unavailable"
    assert card["sparkline"] == "unavailable"
    assert overseer_runtime.inspector_collapsed(96.0, None) is True
    assert overseer_runtime.inspector_collapsed(32.0, None) is False
    assert overseer_runtime.inspector_collapsed(96.0, "SNT-WRD-001") is False
    fake = dict(card)
    fake["eyes"] = 9
    assert overseer_runtime.inspector_card(_units()[1], castes=_snap()["castes"], receipts=_snap()["recent_receipts"])["eyes"] == "unavailable"


def test_overseer_console_filters_and_existing_dispatch(qt_app) -> None:
    logs = overseer_runtime.filter_logs(_snap()["telemetry_log"], "harvest", "")
    assert [row["unit_id"] for row in logs] == ["SNT-HRV-001"]
    threats = overseer_runtime.filter_logs(_snap()["telemetry_log"], "threat", "")
    assert [row["unit_id"] for row in threats] == ["SNT-WRD-001"]
    assert overseer_runtime.filter_logs(_snap()["telemetry_log"], "harvest", "missing") == []
    payload = {"mode": "arxiv", "query": "exoplanets"}
    assert payload["mode"] in {item[0] for item in overseer_runtime.MISSION_MODES}

    engine = QQmlEngine()
    engine.addImportPath(str(ASSETS))
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(HUD_QML)))
    if comp.status() != QQmlComponent.Status.Ready:
        raise AssertionError("; ".join(err.toString() for err in comp.errors()))
    inst = comp.create()
    assert inst is not None
    hud = overseer_runtime.build_hud(_snap(), selected_id="SNT-WRD-001", log_filter="all")
    inst.setProperty("pills", hud["pills"])
    inst.setProperty("swarmRows", hud["swarmRows"])
    inst.setProperty("inspector", hud["inspector"])
    inst.setProperty("logs", hud["logs"])
    inst.setProperty("inspectorOpen", True)
    inst.setProperty("selectedUnitId", "SNT-WRD-001")
    qt_app.processEvents()
    pills = inst.findChild(QObject, "OverseerPills")
    assert pills is not None
    swarm = inst.findChild(QObject, "OverseerSwarmList")
    assert swarm is not None
    assert bool(swarm.property("reuseItems")) is True
    assert inst.findChild(QObject, "OverseerInspector") is not None
    assert inst.findChild(QObject, "OverseerConsole") is not None
    assert inst.findChild(QObject, "OverseerDispatch") is not None
    seen = []

    def _capture(name, payload) -> None:
        seen.append((name, payload))

    inst.hudCommand.connect(_capture)
    inst.hudCommand.emit("dispatch", payload)
    qt_app.processEvents()
    assert seen and seen[-1][0] == "dispatch"
    assert seen[-1][1]["mode"] == "arxiv"
    broken = dict(payload)
    broken["mode"] = "invented"
    assert broken["mode"] not in {item[0] for item in overseer_runtime.MISSION_MODES}
    inst.deleteLater()
    qt_app.processEvents()


def test_overseer_hud_actions_refuse_wrong_unit_and_preserve_confirm(qt_app) -> None:
    selected = {
        "unit_id": "SNT-WRD-001",
        "caste": "warden",
        "state": "ENGAGED_DEFENSE",
    }
    recall = overseer_runtime.resolve_hud_command(
        "recall",
        {"unit_id": "SNT-WRD-001", "caste": "warden"},
        selected_unit=selected,
    )
    assert recall["ok"] is False
    assert recall["path"] is None
    assert recall["body"] is None
    assert "different unit" in recall["status"]

    wrong_id = overseer_runtime.resolve_hud_command(
        "retask",
        {
            "unit_id": "SNT-HRV-001",
            "caste": "harvester",
            "query": "scan sockets",
        },
        selected_unit=selected,
    )
    assert wrong_id["ok"] is False
    assert wrong_id["body"] is None
    assert wrong_id["path"] is None

    wrong_caste = overseer_runtime.resolve_hud_command(
        "retask",
        {
            "unit_id": "SNT-WRD-001",
            "caste": "harvester",
            "query": "scan sockets",
        },
        selected_unit=selected,
    )
    assert wrong_caste["ok"] is False
    assert wrong_caste["body"] is None

    matching = overseer_runtime.resolve_hud_command(
        "retask",
        {
            "unit_id": "SNT-WRD-001",
            "caste": "warden",
            "query": "scan sockets",
        },
        selected_unit=selected,
    )
    assert matching["ok"] is False
    assert matching["path"] is None
    assert matching["body"] is None
    assert "fail-closed" in matching["status"]

    wrong_retire = overseer_runtime.resolve_hud_command(
        "retire",
        {"unit_id": "SNT-HRV-001"},
        selected_unit=selected,
    )
    assert wrong_retire["ok"] is False
    assert wrong_retire["body"] is None

    ok_retire = overseer_runtime.resolve_hud_command(
        "retire",
        {"unit_id": "SNT-WRD-001"},
        selected_unit=selected,
    )
    assert ok_retire["ok"] is True
    assert ok_retire["body"] == {"op": "retire_unit", "unit_id": "SNT-WRD-001"}

    emp = overseer_runtime.resolve_hud_command(
        "emp_halt",
        {"restore": True, "reason": "Overseer emergency stop"},
        selected_unit=selected,
    )
    assert emp["ok"] is True
    assert emp["path"] == "/api/overseer/emp"
    assert emp["body"] == {"reason": "Overseer emergency stop"}
    assert "restore" not in emp["body"]
    restore = overseer_runtime.resolve_hud_command(
        "emp_restore", {}, selected_unit=selected
    )
    assert restore["ok"] is False

    focus = overseer_runtime.resolve_hud_command(
        "focus", {"unit_id": "SNT-WRD-001"}, selected_unit=selected
    )
    assert focus["ok"] is False
    assert "not implemented" in focus["status"]

    view = QQuickView()
    view.engine().addImportPath(str(ASSETS))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.setSource(QUrl.fromLocalFile(str(HUD_QML)))
    if view.status() != QQuickView.Status.Ready:
        errs = view.errors()
        raise AssertionError("; ".join(err.toString() for err in errs))
    view.resize(1280, 800)
    view.show()
    qt_app.processEvents()
    root = view.rootObject()
    assert root is not None
    hud = overseer_runtime.build_hud(_snap(), selected_id="SNT-WRD-001")
    root.setProperty("pills", hud["pills"])
    root.setProperty("swarmRows", hud["swarmRows"])
    root.setProperty("inspector", hud["inspector"])
    root.setProperty("logs", hud["logs"])
    root.setProperty("inspectorOpen", True)
    root.setProperty("selectedUnitId", "SNT-WRD-001")
    root.setProperty("missionMode", "arxiv")
    root.setProperty("missionQuery", "exoplanets")
    qt_app.processEvents()

    seen: list = []
    posted: list = []

    def bridge(name, payload) -> None:
        plan = overseer_runtime.resolve_hud_command(
            name, payload, selected_unit=selected
        )
        seen.append((str(name), overseer_runtime.coerce_hud_payload(payload), plan))
        if plan["ok"]:
            posted.append((plan["path"], plan["body"]))

    root.hudCommand.connect(bridge)

    def click_named(name: str) -> None:
        item = None
        for child in root.findChildren(QObject):
            if child.objectName() == name:
                item = child
                break
        assert item is not None, name
        width = float(item.property("width") or 0)
        height = float(item.property("height") or 0)
        scene_pt = item.mapToScene(QPointF(width / 2.0, height / 2.0))
        QTest.mouseClick(
            view, Qt.LeftButton, Qt.NoModifier, scene_pt.toPoint()
        )
        qt_app.processEvents()

    click_named("OverseerDispatch")
    assert seen and seen[-1][0] == "dispatch"
    assert seen[-1][1].get("mode") == "arxiv"
    assert seen[-1][1].get("query") == "exoplanets"
    assert posted[-1][0] == "/api/overseer/mission"
    assert posted[-1][1]["mode"] == "arxiv"

    n_posted = len(posted)
    click_named("OverseerAction_recall")
    assert seen[-1][0] == "recall"
    assert seen[-1][2]["ok"] is False
    assert seen[-1][2]["body"] is None
    assert len(posted) == n_posted

    click_named("OverseerAction_focus")
    assert seen[-1][0] == "focus"
    assert seen[-1][2]["ok"] is False
    assert len(posted) == n_posted

    click_named("OverseerAction_retire")
    assert seen[-1][0] == "retire"
    assert posted[-1] == (
        "/api/command",
        {"op": "retire_unit", "unit_id": "SNT-WRD-001"},
    )

    click_named("OverseerEmergencyStop")
    assert seen[-1][0] == "emp_halt"
    assert posted[-1][0] == "/api/overseer/emp"
    assert posted[-1][1] == {"reason": "Overseer emergency stop"}
    assert "restore" not in posted[-1][1]

    n_posted = len(posted)
    click_named("OverseerAction_retask")
    assert seen[-1][0] == "retask"
    assert seen[-1][2]["ok"] is False
    assert seen[-1][2]["body"] is None
    assert len(posted) == n_posted

    view.deleteLater()
    qt_app.processEvents()


def _named(root, name: str):
    for child in root.findChildren(QObject):
        if child.objectName() == name:
            return child
    swarm = None
    for child in root.findChildren(QObject):
        if child.objectName() == "OverseerSwarmList":
            swarm = child
            break
    content = swarm.property("contentItem") if swarm is not None else None
    kids = content.childItems() if content is not None and hasattr(content, "childItems") else []
    for child in kids:
        if child.objectName() == name:
            return child
    return None


def _variant(value):
    to_var = getattr(value, "toVariant", None)
    if callable(to_var):
        value = to_var()
    return value


def test_overseer_hud_named_row_invoke_keeps_inspector_across_polls(qt_app) -> None:
    owner = QWidget()
    owner.resize(1280, 800)
    win = SentinelWindow(owner)
    owner.sentinel_window = win
    win.resize(1280, 800)
    scene = win._ensure_scene()
    assert scene is not None
    assert scene.objectName() == "OverseerScene"
    win.show()
    qt_app.processEvents()
    host_root = scene.rootObject()
    assert host_root is not None
    host_root.setProperty("reveal", 1.0)
    host_root.setProperty("inputLive", True)
    host_root.setProperty("cameraDistance", 76.0)
    snap = _snap()
    win.apply_snapshot(snap)
    qt_app.processEvents()
    assert str(host_root.property("selectedUnitId") or "") == ""

    # QQuickWidget list delegates do not instantiate on this offscreen
    # backend (no QRhi). Use the same HUD document to exercise named
    # invoke, then the real host apply_snapshot path for poll persistence.
    engine = QQmlEngine()
    engine.addImportPath(str(ASSETS))
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(HUD_QML)))
    if comp.status() != QQmlComponent.Status.Ready:
        raise AssertionError("; ".join(err.toString() for err in comp.errors()))
    hud_item = comp.create()
    assert hud_item is not None
    hud_item.setWidth(440)
    hud_item.setHeight(800)
    hud = overseer_runtime.build_hud(snap, selected_id="")
    hud_item.setProperty("pills", hud["pills"])
    hud_item.setProperty("swarmRows", hud["swarmRows"])
    hud_item.setProperty("inspector", hud["inspector"])
    hud_item.setProperty("logs", hud["logs"])
    hud_item.setProperty("inspectorOpen", True)
    hud_item.setProperty("selectedUnitId", "")
    qt_app.processEvents()

    row = _named(hud_item, "OverseerSwarmRow_SNT-WRD-001")
    header = _named(hud_item, "OverseerSwarmHeader_warden")
    if header is None:
        header = _named(hud_item, "OverseerSwarmHeader_harvester")
    assert row is not None, "named swarm rows must exist for UIA invoke"
    assert "SNT-WRD-001" in str(row.property("rowLabel") or "")
    assert row.objectName() == "OverseerSwarmRow_SNT-WRD-001"

    chosen: list[str] = []

    def _chosen(unit_id) -> None:
        chosen.append(str(unit_id))
        win._on_unit_chosen(str(unit_id))

    hud_item.unitChosen.connect(_chosen)
    if header is not None:
        assert QMetaObject.invokeMethod(header, "invokeRow")
        qt_app.processEvents()
        assert chosen == []
        assert str(host_root.property("selectedUnitId") or "") == ""

    assert QMetaObject.invokeMethod(row, "invokeRow")
    qt_app.processEvents()
    assert chosen == ["SNT-WRD-001"]
    assert str(host_root.property("selectedUnitId") or "") == "SNT-WRD-001"
    card = _variant(host_root.property("inspectorCard")) or {}
    assert card.get("unit_id") == "SNT-WRD-001"
    assert bool(host_root.property("showInspector")) is True

    win.apply_snapshot(snap)
    qt_app.processEvents()
    assert str(host_root.property("selectedUnitId") or "") == "SNT-WRD-001"
    card = _variant(host_root.property("inspectorCard")) or {}
    assert card.get("unit_id") == "SNT-WRD-001"

    host_root.setProperty("cameraDistance", 96.0)
    win.apply_snapshot(snap)
    qt_app.processEvents()
    assert overseer_runtime.inspector_collapsed(96.0, None) is True
    assert overseer_runtime.inspector_collapsed(96.0, "SNT-WRD-001") is False
    assert str(host_root.property("selectedUnitId") or "") == "SNT-WRD-001"
    assert bool(host_root.property("showInspector")) is True
    card = _variant(host_root.property("inspectorCard")) or {}
    assert card.get("unit_id") == "SNT-WRD-001"

    other = _named(hud_item, "OverseerSwarmRow_SNT-HRV-001")
    assert other is not None
    assert QMetaObject.invokeMethod(other, "invokeRow")
    qt_app.processEvents()
    assert chosen[-1] == "SNT-HRV-001"
    assert str(host_root.property("selectedUnitId") or "") == "SNT-HRV-001"
    win.apply_snapshot(snap)
    qt_app.processEvents()
    assert str(host_root.property("selectedUnitId") or "") == "SNT-HRV-001"
    card = _variant(host_root.property("inspectorCard")) or {}
    assert card.get("unit_id") == "SNT-HRV-001"

    selected = {"unit_id": "SNT-HRV-001", "caste": "harvester"}
    recall = overseer_runtime.resolve_hud_command(
        "recall", {"unit_id": "SNT-HRV-001", "caste": "harvester"},
        selected_unit=selected,
    )
    retask = overseer_runtime.resolve_hud_command(
        "retask",
        {"unit_id": "SNT-HRV-001", "caste": "harvester", "query": "scan"},
        selected_unit=selected,
    )
    assert recall["ok"] is False and recall["body"] is None
    assert retask["ok"] is False and retask["body"] is None

    hud_item.deleteLater()
    teardown_sentinel_window(owner)
    qt_app.processEvents()


def _clipped_rgb250(image) -> int:
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if min(color.red(), color.green(), color.blue()) >= 250:
                count += 1
    return count


def test_overseer_hud_combo_is_dark_filament_and_footer_actions(qt_app) -> None:
    deploy = overseer_runtime.resolve_hud_command(
        "deploy",
        {"caste": "warden", "unit_id": "SNT-WRD-001"},
        selected_unit={"unit_id": "SNT-WRD-001", "caste": "warden"},
    )
    assert deploy["ok"] is True
    assert deploy["path"] == "/api/overseer/scale"
    assert deploy["body"] == {"caste": "warden", "delta": 1}
    blank = overseer_runtime.resolve_hud_command("deploy", {}, selected_unit={})
    assert blank["ok"] is False and blank["body"] is None

    view = QQuickView()
    view.engine().addImportPath(str(ASSETS))
    view.setColor(QColor("#0b0714"))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.setSource(QUrl.fromLocalFile(str(HUD_QML)))
    if view.status() != QQuickView.Status.Ready:
        raise AssertionError("; ".join(err.toString() for err in view.errors()))
    view.resize(1280, 800)
    view.show()
    qt_app.processEvents()
    root = view.rootObject()
    assert root is not None
    hud = overseer_runtime.build_hud(_snap(), selected_id="SNT-WRD-001")
    root.setProperty("pills", hud["pills"])
    root.setProperty("swarmRows", hud["swarmRows"])
    root.setProperty("inspector", hud["inspector"])
    root.setProperty("logs", hud["logs"])
    root.setProperty("inspectorOpen", True)
    root.setProperty("selectedUnitId", "SNT-WRD-001")
    root.setProperty("missionMode", "multi")
    qt_app.processEvents()

    assert _named(root, "OverseerSwarmFooter") is not None
    assert _named(root, "OverseerFooter_deploy") is not None
    recall_btn = _named(root, "OverseerFooter_recall")
    assert recall_btn is not None
    combo = _named(root, "OverseerMissionMode")
    assert combo is not None

    def _rect_colors(item) -> list:
        found: list = []
        color = item.property("color") if item is not None else None
        if color is not None and hasattr(color, "red"):
            found.append(color)
        kids = item.childItems() if item is not None and hasattr(item, "childItems") else []
        for child in kids:
            found.extend(_rect_colors(child))
        return found

    def _assert_dark(colors, where: str) -> None:
        assert colors, where
        hot = [
            (c.red(), c.green(), c.blue())
            for c in colors
            if min(c.red(), c.green(), c.blue()) >= 250
        ]
        assert not hot, (where, hot)
        assert any(
            c.red() <= 40 and c.green() <= 32 and c.blue() <= 64 for c in colors
        ), where

    _assert_dark(_rect_colors(combo), "combo")

    def _grab_or_none():
        image = view.grabWindow()
        if image.width() < 8 or image.height() < 8:
            return None
        visible = False
        for y in range(0, image.height(), 17):
            for x in range(0, image.width(), 17):
                color = image.pixelColor(x, y)
                if color.alpha() > 0 and max(color.red(), color.green(), color.blue()) > 8:
                    visible = True
                    break
            if visible:
                break
        return image if visible else None

    grabbed = _grab_or_none()
    if grabbed is not None:
        assert _clipped_rgb250(grabbed) == 0

    popup = combo.popup if hasattr(combo, "popup") else None
    if popup is not None and hasattr(popup, "open"):
        popup.open()
        qt_app.processEvents()
        _assert_dark(_rect_colors(popup), "popup")
        opened = _grab_or_none()
        if opened is not None:
            assert _clipped_rgb250(opened) == 0
        popup.close()
        qt_app.processEvents()

    view.deleteLater()
    qt_app.processEvents()

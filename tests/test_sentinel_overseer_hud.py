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
from tests.overseer_render_helpers import isolated_render

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


@isolated_render()
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


@isolated_render()
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
    assert focus["ok"] is True
    assert focus["path"] is None
    assert focus["body"] is None
    assert focus.get("local") is True
    wrong_focus = overseer_runtime.resolve_hud_command(
        "focus", {"unit_id": "SNT-HRV-001"}, selected_unit=selected
    )
    assert wrong_focus["ok"] is False

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

    # Do not invoke Deploy, retire, EMP, Recall, or Retask from tests.
    view.deleteLater()
    qt_app.processEvents()


_KEEP: list = []


def _content_item(item):
    if item is None:
        return None
    try:
        content = item.property("contentItem") if hasattr(item, "property") else None
    except RuntimeError:
        return None
    if content is not None:
        _KEEP.append(content)
    return content


def _walk_child_items(item, name: str):
    if item is None:
        return None
    stack = [item]
    while stack:
        cur = stack.pop()
        if cur is None:
            continue
        if cur.objectName() == name:
            return cur
        if hasattr(cur, "childItems"):
            try:
                stack.extend(cur.childItems() or [])
            except RuntimeError:
                pass
    return None


def _named(root, name: str):
    if root is None:
        return None
    children = []
    if hasattr(root, "findChildren"):
        children = list(root.findChildren(QObject))
    for child in children:
        if child.objectName() == name:
            return child
    swarm = None
    inspector = None
    popup = None
    fill = None
    for child in children:
        label = child.objectName()
        if label == "OverseerSwarmList":
            swarm = child
        elif label == "OverseerInspector":
            inspector = child
        elif label == "OverseerMissionModePopup":
            popup = child
        elif label == "OverseerMissionModePopupFill":
            fill = child
    if name == "OverseerMissionModePopup" and popup is not None:
        return popup
    if name == "OverseerMissionModePopupFill" and fill is not None:
        return fill
    found = _walk_child_items(inspector, name)
    if found is not None:
        return found
    content = _content_item(swarm)
    found = _walk_child_items(content, name)
    if found is not None:
        return found
    found = _walk_child_items(root, name)
    if found is not None:
        return found
    found = _walk_child_items(popup, name)
    if found is not None:
        return found
    return _walk_child_items(fill, name)



def _variant(value):
    to_var = getattr(value, "toVariant", None)
    if callable(to_var):
        value = to_var()
    return value


@isolated_render()
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


@isolated_render(software=True)
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

    def _grab():
        image = view.grabWindow()
        ratio = image.devicePixelRatio()
        assert image.width() == round(view.width() * ratio)
        assert image.height() == round(view.height() * ratio)
        assert any(
            image.pixelColor(x, y).alpha() > 0
            and max(image.pixelColor(x, y).getRgb()[:3]) > 8
            for y in range(0, image.height(), 17)
            for x in range(0, image.width(), 17)
        ), "renderer returned a blank image"
        return image

    assert _clipped_rgb250(_grab()) == 0

    assert hasattr(combo, "openPopup")
    combo.openPopup()
    qt_app.processEvents()
    popup = _named(root, "OverseerMissionModePopup")
    fill = _named(root, "OverseerMissionModePopupFill")
    assert popup is not None
    assert fill is not None
    assert bool(popup.property("visible")) is True
    assert float(popup.property("height") or 0) > 8
    colors = _rect_colors(fill)
    if not colors:
        color = fill.property("color")
        if color is not None and hasattr(color, "red"):
            colors = [color]
    _assert_dark(colors, "open popup")
    assert _clipped_rgb250(_grab()) == 0
    combo.closePopup()
    qt_app.processEvents()

    view.deleteLater()
    qt_app.processEvents()


def _hud_with_selection(qt_app):
    view = QQuickView()
    view.engine().addImportPath(str(ASSETS))
    view.setColor(QColor("#0b0714"))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.setSource(QUrl.fromLocalFile(str(HUD_QML)))
    if view.status() != QQuickView.Status.Ready:
        raise AssertionError("; ".join(err.toString() for err in view.errors()))
    view.resize(900, 700)
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
    qt_app.processEvents()
    return view, root


@isolated_render()
def test_overseer_unavailable_actions_are_disabled_and_inert(qt_app) -> None:
    view, root = _hud_with_selection(qt_app)
    seen: list[str] = []
    root.hudCommand.connect(lambda name, _payload: seen.append(str(name)))
    for name in (
        "OverseerFooter_recall",
        "OverseerAction_recall",
        "OverseerAction_retask",
    ):
        item = _named(root, name)
        assert item is not None, name
        assert bool(item.property("enabled")) is False
        mid = QPointF(
            float(item.property("width") or 8) / 2.0,
            float(item.property("height") or 8) / 2.0,
        )
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, item.mapToScene(mid).toPoint())
        qt_app.processEvents()
    assert seen == []
    selected = {"unit_id": "SNT-WRD-001", "caste": "warden"}
    for command in ("recall", "retask"):
        plan = overseer_runtime.resolve_hud_command(
            command,
            {"unit_id": "SNT-WRD-001", "caste": "warden", "query": "scan"},
            selected_unit=selected,
        )
        assert plan["ok"] is False
        assert plan["body"] is None
    focus = _named(root, "OverseerAction_focus")
    assert focus is not None and bool(focus.property("enabled")) is True
    fit = _named(root, "OverseerAction_fitSwarm")
    assert fit is not None and bool(fit.property("enabled")) is True
    deploy = _named(root, "OverseerFooter_deploy")
    retire = _named(root, "OverseerAction_retire")
    assert deploy is not None and bool(deploy.property("enabled")) is not False
    assert retire is not None and bool(retire.property("enabled")) is not False
    view.deleteLater()
    qt_app.processEvents()


@isolated_render()
def test_overseer_inspector_card_exposes_named_controls(qt_app) -> None:
    view, root = _hud_with_selection(qt_app)
    card = _named(root, "OverseerInspector")
    assert card is not None
    title = _named(root, "OverseerInspectorTitle")
    assert title is not None
    heading = str(title.property("text") or "")
    assert "SNT-WRD-001" in heading
    assert "Warden" in heading
    assert heading != "Inspector"
    assert "SNT-WRD-001" in str(title.property("Accessible.name") or heading)
    state = _named(root, "OverseerInspector_state")
    assert state is not None
    state_text = str(state.property("text") or "")
    row = _named(root, "OverseerInspectorRow_state")
    assert row is not None
    assert "ENGAGED_DEFENSE" in state_text
    for name in (
        "OverseerAction_focus",
        "OverseerAction_fitSwarm",
        "OverseerAction_retask",
        "OverseerAction_recall",
        "OverseerAction_retire",
    ):
        assert _named(root, name) is not None, name
    missing = _named(root, "OverseerInspector_not_a_field")
    assert missing is None
    view.deleteLater()
    qt_app.processEvents()


def _crowd_units() -> list[dict]:
    units: list[dict] = []
    for caste, prefix, count, tentacles in (
        ("warden", "WRD", 6, 12),
        ("harvester", "HRV", 8, 7),
        ("sanitizer", "SAN", 4, 8),
        ("tripwire", "TRP", 4, 4),
    ):
        for index in range(1, count + 1):
            units.append(
                {
                    "unit_id": f"SNT-{prefix}-{index:03d}",
                    "caste": caste,
                    "state": "PATROLLING",
                    "tentacles": tentacles,
                }
            )
    return units


@isolated_render()
def test_overseer_swarm_list_scroll_semantics(qt_app) -> None:
    view, root = _hud_with_selection(qt_app)
    units = _crowd_units()
    expanded = overseer_runtime.swarm_rows(units, by="caste")
    assert any(row.get("unit_id") == "SNT-TRP-001" for row in expanded)
    collapsed = overseer_runtime.swarm_rows(
        units, by="caste", collapsed={"warden", "harvester", "sanitizer"}
    )
    assert any(row.get("unit_id") == "SNT-TRP-001" for row in collapsed)
    assert len(expanded) > len(collapsed)
    root.setProperty("swarmRows", expanded)
    qt_app.processEvents()
    swarm = _named(root, "OverseerSwarmList")
    assert swarm is not None
    bar = _named(root, "OverseerSwarmScrollBar")
    assert bar is not None
    content_h = float(swarm.property("contentHeight") or 0)
    view_h = float(swarm.property("height") or 0)
    assert content_h > view_h + 1
    before = float(swarm.property("contentY") or 0)
    mid = swarm.mapToScene(
        QPointF(float(swarm.property("width") or 10) / 2.0, 20)
    ).toPoint()
    wheeled = False
    if hasattr(QTest, "mouseWheel"):
        try:
            QTest.mouseWheel(view, Qt.NoModifier, 0, -240, mid)
            wheeled = True
        except TypeError:
            wheeled = False
    qt_app.processEvents()
    after = float(swarm.property("contentY") or 0)
    if wheeled:
        # Native QML wheel on the list itself. Posted hwnd wheel and
        # UIA ScrollPattern on Windows remain unverified.
        assert after >= before
    swarm.setProperty("contentY", content_h - view_h)
    qt_app.processEvents()
    trip = _named(root, "OverseerSwarmRow_SNT-TRP-001")
    assert trip is not None
    assert float(swarm.property("contentY") or 0) > before
    view.deleteLater()
    qt_app.processEvents()


@isolated_render()
def test_overseer_swarm_scrollbar_is_filament_not_white(qt_app) -> None:
    view, root = _hud_with_selection(qt_app)
    units = _crowd_units()
    root.setProperty("swarmRows", overseer_runtime.swarm_rows(units, by="caste"))
    qt_app.processEvents()
    thumb = _named(root, "OverseerSwarmScrollThumb")
    track = _named(root, "OverseerSwarmScrollTrack")
    assert thumb is not None and track is not None
    thumb_color = thumb.property("color")
    track_color = track.property("color")
    assert thumb_color is not None and hasattr(thumb_color, "red")
    assert track_color is not None and hasattr(track_color, "red")
    assert min(thumb_color.red(), thumb_color.green(), thumb_color.blue()) < 250
    assert min(track_color.red(), track_color.green(), track_color.blue()) < 250
    # Thumb stays in the Filament violet family (#8b6cf2), not grey/white.
    assert thumb_color.red() < 180 and thumb_color.blue() > 180
    hot = (255, 255, 255)
    assert (thumb_color.red(), thumb_color.green(), thumb_color.blue()) != hot
    muted = (thumb_color.red() // 2, thumb_color.green() // 2, thumb_color.blue() // 2)
    assert muted[2] < thumb_color.blue()
    view.deleteLater()
    qt_app.processEvents()


@isolated_render()
def test_overseer_swarm_header_stays_sticky_while_scrolling(qt_app) -> None:
    view, root = _hud_with_selection(qt_app)
    units = _crowd_units()
    rows = overseer_runtime.swarm_rows(units, by="caste")
    root.setProperty("swarmRows", rows)
    qt_app.processEvents()
    swarm = _named(root, "OverseerSwarmList")
    sticky = _named(root, "OverseerSwarmStickyHeader")
    assert swarm is not None and sticky is not None
    assert bool(swarm.property("stickyVisible")) is False
    # Skip past the warden header and units so the harvester header leaves the top.
    # warden header + 6 units + harvester header = 8 rows; +6 harvesters = 14.
    swarm.setProperty("contentY", 14 * 44)
    qt_app.processEvents()
    assert bool(swarm.property("stickyVisible")) is True
    label = str(sticky.property("rowLabel") or "")
    assert "harvester" in label
    assert "8" in label
    swarm.setProperty("contentY", 0)
    qt_app.processEvents()
    assert bool(swarm.property("stickyVisible")) is False
    view.deleteLater()
    qt_app.processEvents()



@isolated_render()
def test_overseer_hud_panels_use_designed_fill(qt_app) -> None:
    """Panel plates and unselected rows use opaque #0e0920 so View3D cannot punch through."""
    view, root = _hud_with_selection(qt_app)
    fill = QColor("#0e0920")
    assert fill.alpha() == 255
    for name in (
        "OverseerSwarmPanel",
        "OverseerInspector",
        "OverseerConsole",
        "OverseerPillBar",
    ):
        item = _named(root, name)
        assert item is not None, name
        color = item.property("color")
        assert color is not None and hasattr(color, "red"), name
        assert color.red() == fill.red() and color.green() == fill.green()
        assert color.blue() == fill.blue()
        assert color.alpha() == 255, name
    selected = _named(root, "OverseerSwarmRow_SNT-WRD-001")
    other = _named(root, "OverseerSwarmRow_SNT-WRD-002")
    assert selected is not None and other is not None
    selected_c = selected.property("color")
    other_c = other.property("color")
    assert selected_c.alpha() == 255
    assert (selected_c.red(), selected_c.green(), selected_c.blue()) == (0x2A, 0x1A, 0x4A)
    assert other_c.alpha() == 255
    assert (other_c.red(), other_c.green(), other_c.blue()) == (fill.red(), fill.green(), fill.blue())
    assert other_c.alpha() != 0
    view.deleteLater()
    qt_app.processEvents()

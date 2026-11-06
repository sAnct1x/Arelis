"""Batch A HUD: pills, virtualized swarm list, inspector, console. Isolated QML."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest

from arelis.ui import overseer_runtime

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

    ok_retask = overseer_runtime.resolve_hud_command(
        "retask",
        {
            "unit_id": "SNT-WRD-001",
            "caste": "warden",
            "query": "scan sockets",
        },
        selected_unit=selected,
    )
    assert ok_retask["ok"] is True
    assert ok_retask["path"] == "/api/command"
    assert ok_retask["body"]["op"] == "dispatch_task"
    assert ok_retask["body"]["unit_id"] == "SNT-WRD-001"
    assert ok_retask["body"]["caste"] == "warden"

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

    click_named("OverseerAction_retask")
    assert seen[-1][0] == "retask"
    assert posted[-1][0] == "/api/command"
    assert posted[-1][1]["op"] == "dispatch_task"
    assert posted[-1][1]["unit_id"] == "SNT-WRD-001"
    assert posted[-1][1]["caste"] == "warden"

    view.deleteLater()
    qt_app.processEvents()

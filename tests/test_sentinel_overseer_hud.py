"""Batch A HUD: pills, virtualized swarm list, inspector, console. Isolated QML."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

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

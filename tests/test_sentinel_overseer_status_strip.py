"""Overseer status strip (Iris FIX-LIST rank 1) replaces the pill row: it reads the
snapshot's threat, defender, caste, warrant and newest-event numbers at a glance,
and on a narrow window collapses the last three blocks to chips (Vela)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

from arelis.ui import overseer_runtime
from tests.overseer_render_helpers import isolated_render

WARRANTS_TIP = "Evidence receipts in memory (includes up to 120 from earlier runs)"
ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"


def _texts(item) -> list[str]:
    if not item.isVisible():
        return []
    out = [str(item.property("text"))] if item.property("text") else []
    for child in item.childItems():
        out += _texts(child)
    return out


@isolated_render()
def test_status_strip_reads_threats_defenders_castes_and_last_event(qt_app) -> None:
    snap = {
        "metrics": {"warrants_minted": 238, "security_events": 0},
        "units": [
            {"unit_id": "SNT-WRD-001", "caste": "warden", "state": "VECTORING"},
            {"unit_id": "SNT-WRD-002", "caste": "warden", "state": "PATROLLING"},
            {"unit_id": "SNT-HRV-001", "caste": "harvester", "state": "PATROLLING"},
        ],
        "telemetry_log": [
            {"seq": 1, "iso_time": "13:25:39.001", "message": "boot"},
            {"seq": 2, "iso_time": "13:25:40.120", "message": "3-Sentinel Pack (SNT-TRP-001) "
             "finished tripwire:verify (ok=True, title=)"},
        ],
    }
    engine = QQmlEngine()
    engine.addImportPath(str(ASSETS))
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(ASSETS / "OverseerHud.qml")))
    hud = comp.create()
    assert hud is not None, "; ".join(e.toString() for e in comp.errors())
    try:
        hud.setProperty("width", 2110)
        hud.setProperty("height", 1306)
        hud.setProperty("pills", overseer_runtime.build_hud(snap)["pills"])
        qt_app.processEvents()
        assert hud.findChild(QObject, "OverseerPills") is None

        def block(name: str) -> list[str]:
            return _texts(hud.findChild(QObject, "OverseerStrip_" + name))

        assert block("threats") == ["THREATS", "0", "All clear"]
        # The Swarm header's active count (VECTORING counts) is the engaged number.
        assert block("defenders") == ["DEFENDERS", "2", "Wardens patrolling · 1 engaged"]
        assert block("units") == [
            "UNITS BY CASTE", "3", "Warden 2", "Stalker 0", "Harvester 1", "Sanitizer 0", "Tripwire 0",
        ]
        assert block("warrants") == ["WARRANTS", "238"]
        assert block("lastEvent") == ["LAST EVENT", "13:25:40", "Tripwire verify, ok"]

        # Default 1200 px window: Threats and Defenders stay whole, the rest are
        # chips with the full label and detail in the tooltip, all inside the
        # header row and clear of the title and Emergency stop.
        hud.setProperty("width", 1200)
        qt_app.processEvents()
        assert hud.findChild(QObject, "OverseerPillBar").property("height") == 86
        assert block("threats") == ["THREATS", "0", "All clear"]
        assert block("defenders") == ["DEFENDERS", "2", "Wardens patrolling · 1 engaged"]
        assert [block(n) for n in ("units", "warrants", "lastEvent")] == [["3"], ["238"], ["13:25"]]

        def tip(name: str) -> str:
            return str(hud.findChild(QObject, "OverseerStrip_" + name).property("tip"))

        assert tip("threats") == "Threats: 0 All clear. Engaged castes: Warden 1"
        assert "Stalker 0" in tip("units")
        assert tip("warrants").endswith(WARRANTS_TIP)
        assert "13:25:40 Tripwire verify, ok" in tip("lastEvent")
        strip = hud.findChild(QObject, "OverseerStatusStrip")
        title = hud.findChild(QObject, "OverseerTitle")
        title_right = title.mapToItem(hud, QPointF(title.width(), 0)).x()
        assert strip.mapToItem(hud, QPointF(0, 0)).x() >= title_right + 24
        stop = hud.findChild(QObject, "OverseerEmergencyStop").mapToItem(hud, QPointF(0, 0)).x()
        last = hud.findChild(QObject, "OverseerStrip_lastEvent")
        assert last.isVisible()
        assert last.mapToItem(hud, QPointF(last.width(), 56)).x() <= stop - 16
    finally:
        hud.deleteLater()
        qt_app.processEvents()

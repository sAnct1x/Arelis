"""Overseer status strip (Iris FIX-LIST rank 1) replaces the pill row: it reads the
snapshot's threat, defender, caste, warrant and newest-event numbers at a glance."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

from arelis.ui import overseer_runtime
from tests.overseer_render_helpers import isolated_render

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"


def _texts(item) -> list[str]:
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
    finally:
        hud.deleteLater()
        qt_app.processEvents()

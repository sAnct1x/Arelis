"""Overseer polish rank 3: inspector docked outside the free well."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView

from arelis.ui import overseer_runtime
from tests.overseer_render_helpers import isolated_render

HUD_QML = (
    Path(__file__).resolve().parents[1]
    / "arelis/assets/sentinel/overseer/OverseerHud.qml"
)
ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"


def _units() -> list[dict]:
    return [
        {
            "unit_id": "SNT-HRV-001",
            "caste": "harvester",
            "state": "PATROLLING",
            "tentacles": 8,
            "current_task": "gather ingress",
        },
        {
            "unit_id": "SNT-WRD-001",
            "caste": "warden",
            "state": "PATROLLING",
            "tentacles": 12,
        },
    ]


def _snap() -> dict:
    return {
        "metrics": {"warrants_minted": 238, "security_events": 0},
        "units": _units(),
        "castes": [
            {
                "caste_id": "harvester",
                "allowed_capabilities": [
                    "fetch_url",
                    "query_arxiv",
                    "query_horizons",
                    "query_wikipedia",
                    "write_harvest_report",
                ],
            }
        ],
        "recent_receipts": [],
        "telemetry_log": [
            {
                "seq": 1,
                "iso_time": "13:17:46.100",
                "unit_id": "SNT-HRV-001",
                "caste": "harvester",
                "level": "HARVEST",
                "message": "New listening TCP port :8080 opened on host since boot",
            },
            {
                "seq": 2,
                "iso_time": "13:25:40.120",
                "unit_id": "SNT-TRP-001",
                "caste": "tripwire",
                "level": "TRIPWIRE",
                "message": "3-Sentinel HUNTER-SEEKER Pack (SNT-TRP-001) finished tripwire:verify (ok=True, title=)",
            },
        ],
    }


def _named(root, name: str):
    if root is None:
        return None
    stack = [root]
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


@isolated_render(software=True)
def test_overseer_inspector_docks_outside_well_without_unavailable(qt_app) -> None:
    """One behaviour change: docked inspector only when selected, no unavailable rows."""
    # Free well loses the dock column (360 + 24 edge + 16 gap) when open.
    open_c = overseer_runtime.free_viewport_center(2110, 1306, True)
    closed_c = overseer_runtime.free_viewport_center(2110, 1306, False)
    # Iris wants well centre x 1055 once the swarm gutter is 400 (rank 5).
    # With today's swarm width 440 the open centre is 1075; the right edge is 1710.
    assert abs(open_c[0] - 1075.0) < 1.0
    assert open_c[0] < closed_c[0]
    assert abs(overseer_runtime._free_viewport_edges(2110, 1306, True)[2] - 1710.0) < 1.0
    assert overseer_runtime.free_viewport_shift(2110, 1306, True) != overseer_runtime.free_viewport_shift(
        2110, 1306, False
    )

    card = overseer_runtime.inspector_card(
        _units()[0],
        castes=_snap()["castes"],
        receipts=_snap()["recent_receipts"],
        telemetry_log=_snap()["telemetry_log"],
    )
    assert card["unit_id"] == "SNT-HRV-001"
    assert card["role"] == "Gather"
    assert [row["key"] for row in card["live"]] == ["state", "tentacles"]
    assert "Target" in card["missing"]
    assert "Warrant hash" in card["missing"]
    assert card["capabilities"] == [
        "fetch_url",
        "query_arxiv",
        "query_horizons",
        "query_wikipedia",
        "write_harvest_report",
    ]
    assert len(card["recent"]) == 1
    assert "8080" in card["recent"][0]["message"]
    assert "unavailable" not in str(card)

    view = QQuickView()
    view.engine().addImportPath(str(ASSETS))
    view.setColor(QColor("#0b0714"))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.setSource(QUrl.fromLocalFile(str(HUD_QML)))
    assert view.status() == QQuickView.Status.Ready, [e.toString() for e in view.errors()]
    view.resize(2110, 1306)
    view.show()
    qt_app.processEvents()
    root = view.rootObject()
    assert root is not None

    empty_hud = overseer_runtime.build_hud(_snap(), selected_id="", camera_distance=32.0)
    root.setProperty("pills", empty_hud["pills"])
    root.setProperty("swarmRows", empty_hud["swarmRows"])
    root.setProperty("inspector", empty_hud["inspector"])
    root.setProperty("logs", empty_hud["logs"])
    root.setProperty("inspectorOpen", False)
    root.setProperty("selectedUnitId", "")
    qt_app.processEvents()
    panel = _named(root, "OverseerInspector")
    assert panel is not None
    assert bool(panel.property("visible")) is False
    assert empty_hud["inspectorCollapsed"] is True

    hud = overseer_runtime.build_hud(_snap(), selected_id="SNT-HRV-001")
    root.setProperty("pills", hud["pills"])
    root.setProperty("swarmRows", hud["swarmRows"])
    root.setProperty("inspector", hud["inspector"])
    root.setProperty("logs", hud["logs"])
    root.setProperty("inspectorOpen", True)
    root.setProperty("selectedUnitId", "SNT-HRV-001")
    qt_app.processEvents()
    panel = _named(root, "OverseerInspector")
    assert panel is not None
    assert bool(panel.property("visible")) is True
    assert float(panel.property("width") or 0) == 360
    # 24 px from the right edge of the 2110 window.
    right_edge = float(panel.property("x") or 0) + float(panel.property("width") or 0)
    assert abs(right_edge - (2110 - 24)) < 1.5
    assert float(panel.property("x") or 0) >= 1710 - 1  # well ends at 1710
    height = float(panel.property("height") or 0)
    assert height > 200
    assert height < 900  # hugs content; no 240 px empty band forcing a tall plate

    title = _named(root, "OverseerInspectorTitle")
    assert title is not None and "SNT-HRV-001" in str(title.property("text") or "")
    role = _named(root, "OverseerInspectorRole")
    assert role is not None
    assert "Harvester" in str(role.property("text") or "")
    assert "Gather" in str(role.property("text") or "")
    state = _named(root, "OverseerInspector_state")
    assert state is not None and "PATROLLING" in str(state.property("text") or "")
    tent = _named(root, "OverseerInspector_tentacles")
    assert tent is not None and "8" in str(tent.property("text") or "")
    assert _named(root, "OverseerInspector_eyes") is None  # missing, not a row
    miss = _named(root, "OverseerInspectorMissingList")
    assert miss is not None
    miss_text = str(miss.property("text") or "")
    assert "Eyes" in miss_text and "Target" in miss_text
    assert "unavailable" not in miss_text.lower()
    recent = _named(root, "OverseerInspectorRecent")
    assert recent is not None and bool(recent.property("visible")) is True
    retask = _named(root, "OverseerAction_retask")
    assert retask is not None
    assert bool(retask.property("enabled")) is False
    assert "unavailable" not in str(retask.property("Accessible.name") or "").lower()
    deselect = _named(root, "OverseerInspectorDeselect")
    assert deselect is not None

    # Deselect hides the dock.
    root.unitChosen.emit("")
    qt_app.processEvents()
    # Signal alone does not clear selectedUnitId on a bare HUD; the View does.
    # Drive the same path the View uses:
    root.setProperty("selectedUnitId", "")
    root.setProperty("inspectorOpen", False)
    root.setProperty("inspector", overseer_runtime.inspector_card(None))
    qt_app.processEvents()
    assert bool(panel.property("visible")) is False

    view.deleteLater()
    qt_app.processEvents()

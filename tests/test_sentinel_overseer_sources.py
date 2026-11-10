"""Overseer edge source nodes light a beam only on a real harvest fetch."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView

from arelis.ui import overseer_runtime as o
from tests.overseer_render_helpers import isolated_render

VIEW_QML = (
    Path(__file__).resolve().parents[1]
    / "arelis/assets/sentinel/overseer/OverseerView.qml"
)


def test_source_nodes_beam_only_when_harvest_fetch_is_live() -> None:
    assert o.normalize_harvest_source("arxiv") == "arxiv"
    assert o.normalize_harvest_source("wikipedia", "Star") == "wikipedia"
    assert o.normalize_harvest_source("horizons", "Mars") == "horizons"
    assert o.normalize_harvest_source("url", "https://example.com/a") == "web"
    assert o.normalize_harvest_source("synthetic") == ""

    idle = o.build_frame(
        [
            {
                "unit_id": "SNT-WRD-001",
                "caste": "warden",
                "state": "PATROLLING",
                "position": [4, 0.5, 0],
            }
        ],
        76.0,
        nodes=[],
    )
    assert idle["activeSources"] == []
    beacons = [c for c in idle["conduits"] if str(c.get("id", "")).startswith("source-beacon:")]
    beams = [c for c in idle["conduits"] if str(c.get("id", "")).startswith("source-beam:")]
    assert {c["source_id"] for c in beacons} == {"arxiv", "wikipedia", "horizons", "web"}
    assert beams == []
    assert len(idle["sourceLabels"]) == 4
    assert all(not row["hot"] for row in idle["sourceLabels"])

    # Live harvest_target node (hive removes it when the fetch ends).
    live_nodes = [
        {
            "node_id": "node-hrv-0007",
            "kind": "harvest_target",
            "label": "ARXIV: fusion",
            "status": "extracting",
            "position": [22.0, 2.0, 4.0],
            "metadata": {"action": "arxiv", "target": "fusion", "unit_id": "SNT-HRV-001"},
        }
    ]
    busy = o.build_frame(
        [
            {
                "unit_id": "SNT-HRV-001",
                "caste": "harvester",
                "state": "ENGAGED_HARVEST",
                "position": [10, 0.5, 2],
                "current_task": "Extracting arxiv: fusion",
            }
        ],
        76.0,
        nodes=live_nodes,
    )
    assert busy["activeSources"] == ["arxiv"]
    beams = [c for c in busy["conduits"] if str(c.get("id", "")).startswith("source-beam:")]
    assert beams and all(c["source_id"] == "arxiv" for c in beams)
    hot = next(row for row in busy["sourceLabels"] if row["id"] == "arxiv")
    cold = next(row for row in busy["sourceLabels"] if row["id"] == "wikipedia")
    assert hot["hot"] is True
    assert cold["hot"] is False

    # Unit task alone (no node yet) still lights the matching source.
    from_task = o.active_harvest_sources(
        units=[
            {
                "unit_id": "SNT-HRV-002",
                "caste": "harvester",
                "state": "ENGAGED_HARVEST",
                "current_task": "Extracting wikipedia: nebula",
            }
        ],
        nodes=[],
    )
    assert from_task == {"wikipedia"}

    # Negatives: warrant carry and token-less harvest must not light Web.
    warrant = o.build_frame(
        [
            {
                "unit_id": "SNT-WRD-001",
                "caste": "warden",
                "state": "CARRYING_WARRANT",
                "position": [3, 0.5, 1],
                "current_task": "Delivering warrant",
            }
        ],
        76.0,
        nodes=[],
    )
    assert warrant["activeSources"] == []
    assert [c for c in warrant["conduits"] if str(c.get("id", "")).startswith("source-beam:")] == []

    empty_harvest = o.build_frame(
        [
            {
                "unit_id": "SNT-HRV-003",
                "caste": "harvester",
                "state": "ENGAGED_HARVEST",
                "position": [6, 0.5, 1],
                "current_task": "",
            }
        ],
        76.0,
        nodes=[],
    )
    assert empty_harvest["activeSources"] == []
    assert [
        c for c in empty_harvest["conduits"] if str(c.get("id", "")).startswith("source-beam:")
    ] == []

    extracting_only = o.build_frame(
        [
            {
                "unit_id": "SNT-HRV-004",
                "caste": "harvester",
                "state": "ENGAGED_HARVEST",
                "position": [7, 0.5, 1],
                "current_task": "Extracting",
            }
        ],
        76.0,
        nodes=[],
    )
    assert extracting_only["activeSources"] == []
    assert [
        c for c in extracting_only["conduits"] if str(c.get("id", "")).startswith("source-beam:")
    ] == []


@isolated_render()
def test_source_labels_show_on_screen_and_keep_their_delegates(qt_app) -> None:
    """mapFrom3DScene z is a distance in scene units, so a 0..1 depth test hid
    every label. Labels show in the free scene area, hide under the HUD, and
    keep their delegates while the scene animates."""
    view = QQuickView()
    view.engine().addImportPath(str(VIEW_QML.parent))
    view.setColor(QColor("#0b0714"))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.setSource(QUrl.fromLocalFile(str(VIEW_QML)))
    assert view.status() == QQuickView.Status.Ready, view.errors()
    view.resize(2110, 1306)
    view.show()
    qt_app.processEvents()
    root = view.rootObject()
    # Fit swarm frames the whole hive, sources included, at every band size.
    root.fitSwarm()
    root.applyFrame(o.build_frame([], 96.0, 1306.0, nodes=[]))
    qt_app.processEvents()
    rows = root.property("sourceLabelScreen")
    rows = rows.toVariant() if hasattr(rows, "toVariant") else rows
    shown = [r for r in rows if r["visible"]]
    assert shown, rows
    free = (min(440, 2110 * 0.26), 86, 2110 - 20, 1306 - 230)
    for r in rows:
        inside = free[0] < r["sx"] < free[2] and free[1] < r["sy"] < free[3]
        assert r["visible"] == inside, r
    def label(sid):
        name = "OverseerSourceLabel_" + sid
        return next((c for c in root.childItems() if c.objectName() == name), None)

    first = {r["id"]: label(r["id"]) for r in shown}
    assert all(item is not None and item.isVisible() for item in first.values()), first
    t = float(root.property("sceneTime"))
    for i in range(30):
        root.setProperty("sceneTime", t + 0.016 * (i + 1))
    qt_app.processEvents()
    for sid, item in first.items():
        assert label(sid) is item
    view.close()
    view.deleteLater()
    qt_app.processEvents()

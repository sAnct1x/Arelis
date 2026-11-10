"""Overseer edge source nodes light a beam only on a real harvest fetch."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSizeF, QUrl
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
    # The root owns the size: the Windows runner clamps a 2110 x 1306 window
    # to 1028 x 749, and the free area below is computed for 2110 x 1306.
    view.setResizeMode(QQuickView.SizeViewToRootObject)
    view.setSource(QUrl.fromLocalFile(str(VIEW_QML)))
    assert view.status() == QQuickView.Status.Ready, view.errors()
    root = view.rootObject()
    root.setSize(QSizeF(2110, 1306))
    view.show()
    qt_app.processEvents()
    assert (root.width(), root.height()) == (2110, 1306)
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


def _swarm(total: int) -> list[dict]:
    mix = [("sanitizer", 0.16), ("warden", 0.28), ("stalker", 0.02), ("tripwire", 0.10)]
    units = []
    for caste, share in mix:
        units += [{"unit_id": f"{caste}-{i}", "caste": caste} for i in range(round(total * share))]
    units += [{"unit_id": f"harvester-{i}", "caste": "harvester"} for i in range(total - len(units))]
    return [
        dict(u, state="PATROLLING", position=[0, 0.5, 0], heading=[1, 0, 0], scale=0.36)
        for u in units
    ]


@isolated_render()
def test_default_view_frames_perimeter_and_every_source_label(qt_app) -> None:
    """The default camera is Iris's wide frame, pulled back until the
    perimeter and all four source labels sit in the scene area the HUD
    leaves free, at every band size and at the Windows CI clamp."""
    from PySide6.QtQml import QQmlEngine, QQmlExpression

    view = QQuickView()
    view.engine().addImportPath(str(VIEW_QML.parent))
    view.setColor(QColor("#0b0714"))
    # The root owns the size: the Windows runner clamps a 2110 x 1306 window
    # to 1028 x 749, and each free area below is computed for the size asked.
    view.setResizeMode(QQuickView.SizeViewToRootObject)
    view.setSource(QUrl.fromLocalFile(str(VIEW_QML)))
    assert view.status() == QQuickView.Status.Ready, view.errors()
    view.show()
    root = view.rootObject()
    ring = QQmlExpression(
        QQmlEngine.contextForObject(root),
        root,
        "(function(){ var out = []; for (var i = 0; i < 24; i++) {"
        " var a = i * Math.PI / 12, m = view.mapFrom3DScene(Qt.vector3d("
        "perimeterRadius * Math.cos(a), 0, perimeterRadius * Math.sin(a)));"
        " out.push([m.x, m.y]) } return out })()",
    )
    for w, h in ((2110, 1306), (1028, 749)):
        root.setSize(QSizeF(w, h))
        qt_app.processEvents()
        assert (root.width(), root.height()) == (w, h)
        free = (min(440, w * 0.26), 86, w - 20, h - 230)
        for total in (50, 100, 128):
            root.applyFrame(o.build_frame(_swarm(total), 96.0, float(h), nodes=[]))
            qt_app.processEvents()
            assert str(root.property("cameraMode")) == "overview"
            assert abs(float(root.property("cameraPitch")) - o.OVERVIEW_PITCH_DEG) < 1e-3
            pts = ring.evaluate()[0]
            pts = pts.toVariant() if hasattr(pts, "toVariant") else pts
            for x, y in pts:
                assert free[0] <= x <= free[2] and free[1] <= y <= free[3], (w, total, x, y)
            rows = root.property("sourceLabelScreen")
            rows = rows.toVariant() if hasattr(rows, "toVariant") else rows
            assert len(rows) == 4 and all(r["visible"] for r in rows), (w, total, rows)
            for r in rows:
                name = "OverseerSourceLabel_" + r["id"]
                item = next(c for c in root.childItems() if c.objectName() == name)
                box = (item.x(), item.y(), item.x() + item.width(), item.y() + item.height())
                assert item.isVisible() and item.width() > 0, (w, total, r)
                assert free[0] <= box[0] and box[2] <= free[2], (w, total, r, box)
                assert free[1] <= box[1] and box[3] <= free[3], (w, total, r, box)
    view.close()
    view.deleteLater()
    qt_app.processEvents()

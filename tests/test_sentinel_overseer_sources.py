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
    assert o.normalize_harvest_source("url", "https://example.com/a") == "example.com"
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
    nodes = idle["sourceNodes"]
    beams = [c for c in idle["conduits"] if str(c.get("id", "")).startswith("source-beam:")]
    assert nodes == []
    assert idle["sourceLabels"] == []
    assert beams == []

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
    assert {row["id"] for row in busy["sourceLabels"]} == {"arxiv"}
    assert hot["hot"] is True
    assert hot["label"] == "arXiv"

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
    root.applyFrame(o.build_frame(
        [{
            "unit_id": "SNT-HRV-001",
            "caste": "harvester",
            "state": "ENGAGED_HARVEST",
            "action": "arxiv",
            "current_task": "arxiv: fusion",
            "position": [10, 0.5, 2],
        }],
        96.0,
        1306.0,
        nodes=[{
            "node_id": "ht-1",
            "kind": "harvest_target",
            "label": "arXiv",
            "status": "extracting",
            "metadata": {"action": "arxiv", "target": "fusion", "unit_id": "SNT-HRV-001"},
        }],
    ))
    qt_app.processEvents()
    rows = root.property("sourceLabelScreen")
    rows = rows.toVariant() if hasattr(rows, "toVariant") else rows
    shown = [r for r in rows if r["visible"]]
    assert shown, rows
    free = o._free_viewport_edges(2110, 1306, False)
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
    field edge sits in the scene area the HUD leaves free, at every
    swarm size and at the Windows CI clamp."""
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
        "(function(){ var out = []; for (var i = 0; i < 16; i++) {"
        " var a = i * Math.PI / 8, r = root.fieldMax(a),"
        " m = view.mapFrom3DScene(Qt.vector3d("
        "r * Math.cos(a), 0.02, -r * Math.sin(a)));"
        " out.push([m.x, m.y]) } return out })()",
    )
    for w, h in ((2110, 1306), (1028, 749)):
        root.setSize(QSizeF(w, h))
        qt_app.processEvents()
        assert (root.width(), root.height()) == (w, h)
        free = o._free_viewport_edges(w, h, False)
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
            if rows:
                for r in rows:
                    sx, sy = r.get("sx", r.get("x")), r.get("sy", r.get("y"))
                    assert free[0] - 8 <= sx <= free[2] + 8, (w, total, r)
                    assert free[1] - 8 <= sy <= free[3] + 8, (w, total, r)
    view.close()
    view.deleteLater()
    qt_app.processEvents()


def test_harvest_sources_follow_real_hosts_not_a_fixed_catalog() -> None:
    """Any fetch host or local tool gets its own source, not the Web bucket.

    Idle snapshots do not paint the old four-name catalog. Overflow past
    MAX_GATES folds by traffic then id; there is no invented 'other' gate.
    Revert of the identity/catalog change fails this test.
    """
    assert o.normalize_harvest_source("url", "https://www.github.com/foo/bar") == "github.com"
    assert o.harvest_source_label("github.com") == "github.com"
    assert o.normalize_harvest_source("url", "http://localhost:8080/docs") == "localhost:8080"
    assert o.normalize_harvest_source("files", "README.md") == "files"
    assert o.normalize_harvest_source("url", "https://docs.python.org/3/") == "docs.python.org"
    assert o.normalize_harvest_source("url", "https://news.ycombinator.com/item?id=1") == "news.ycombinator.com"
    assert o.normalize_harvest_source("url", "https://example.com/a") == "example.com"
    assert o.normalize_harvest_source("url", "https://export.arxiv.org/api/query") == "arxiv"
    assert o.normalize_harvest_source("url", "https://en.wikipedia.org/wiki/Mars") == "wikipedia"
    assert o.normalize_harvest_source("synthetic") == ""

    idle = o.build_frame(
        [{
            "unit_id": "SNT-WRD-001",
            "caste": "warden",
            "state": "PATROLLING",
            "position": [4, 0.5, 0],
        }],
        76.0,
        nodes=[],
    )
    assert idle["sourceLabels"] == []
    assert idle["sourceNodes"] == []
    assert idle["activeSources"] == []

    units = [
        {
            "unit_id": "SNT-HRV-001", "caste": "harvester", "state": "ENGAGED_HARVEST",
            "position": [10, 0.5, 2], "action": "url",
            "current_task": "https://github.com/x/y",
        },
        {
            "unit_id": "SNT-HRV-002", "caste": "harvester", "state": "ENGAGED_HARVEST",
            "position": [11, 0.5, 2], "action": "files",
            "current_task": "files: README.md",
        },
        {
            "unit_id": "SNT-HRV-003", "caste": "harvester", "state": "ENGAGED_HARVEST",
            "position": [12, 0.5, 2], "action": "url",
            "current_task": "http://localhost:8080/x",
        },
    ]
    nodes = [
        {
            "node_id": "n1", "kind": "harvest_target", "status": "extracting",
            "metadata": {"action": "url", "target": "https://github.com/x/y", "unit_id": "SNT-HRV-001"},
        },
        {
            "node_id": "n2", "kind": "harvest_target", "status": "extracting",
            "metadata": {"action": "files", "target": "README.md", "unit_id": "SNT-HRV-002"},
        },
        {
            "node_id": "n3", "kind": "harvest_target", "status": "extracting",
            "metadata": {"action": "url", "target": "http://localhost:8080/x", "unit_id": "SNT-HRV-003"},
        },
    ]
    busy = o.build_frame(units, 76.0, nodes=nodes)
    by_id = {row["id"]: row for row in busy["sourceLabels"]}
    assert set(by_id) == {"github.com", "localhost:8080", "files"}
    assert "web" not in by_id
    assert by_id["github.com"]["label"] == "github.com"
    assert by_id["localhost:8080"]["label"] == "localhost:8080"
    assert by_id["files"]["label"] == "files"
    pos = {sid: (row["x"], row["z"]) for sid, row in by_id.items()}
    assert len(set(pos.values())) == 3

    many_units, many_nodes = [], []
    for i in range(9):
        host = f"host{i:02d}.example.net"
        uid = f"SNT-HRV-{i:03d}"
        many_units.append({
            "unit_id": uid, "caste": "harvester", "state": "ENGAGED_HARVEST",
            "position": [10, 0.5, 2], "action": "url", "current_task": f"https://{host}/p",
        })
        many_nodes.append({
            "node_id": f"n{i}", "kind": "harvest_target", "status": "extracting",
            "metadata": {"action": "url", "target": f"https://{host}/p", "unit_id": uid},
        })
    over = o.build_frame(many_units, 76.0, nodes=many_nodes)
    ids = [row["id"] for row in over["sourceLabels"]]
    assert len(ids) == o._max_gates() == 8
    assert "other" not in ids
    assert "web" not in ids
    assert "host08.example.net" not in ids
    assert ids == sorted(ids)

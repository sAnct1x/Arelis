"""Overseer Pass C: orb, unit plates and tentacles, source nodes."""

from __future__ import annotations

import struct
from pathlib import Path

from arelis.ui import overseer_curves as curves
from arelis.ui import overseer_runtime as o
from tests.overseer_render_helpers import isolated_render

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"
MESHES = ASSETS / "meshes"


def test_orb_energy_follows_tok_rate_and_never_fakes_activity() -> None:
    assert o.orb_energy(0) == 0.3
    assert o.orb_energy(60) == 1.0
    assert o.orb_energy(30) == 0.65
    idle = o.orb_state({}, 0)
    assert idle["energy"] == 0.3
    assert idle["memoryCount"] == 0
    assert idle["toolsCount"] == 0
    assert idle["memoryLabel"] == "Memory · 0 from last chat"
    assert idle["toolsLabel"] == "Tools 0 running"
    live = o.orb_state(
        {"memories_in_context": 14, "tools_running": [{"id": "calc", "elapsed": 4, "timeout": 20}]},
        60,
    )
    assert live["energy"] == 1.0
    assert live["memoryCount"] == 14
    assert live["toolsCount"] == 1
    assert live["memoryLabel"] == "Memory · 14 from last chat"
    assert live["toolsLabel"] == "Tools 1 running"
    assert live["toolsLitArc"][1] == 0.08 * (4 / 20)
    frame = o.build_frame([], 96.0, snap={}, tok_rate=0)
    assert frame["orb"]["energy"] == 0.3
    assert frame["orb"]["memoryCount"] == 0


def test_lod2_has_three_eyes_and_lod1_links_only_on_fetchers() -> None:
    report = o.load_mesh_report()
    assert report[2]["parts"]["lens"] == 60  # 3 eyes
    assert report[1]["parts"]["lens"] == 560  # 7 eyes
    # New balsam meshes are one draw each.
    for name in (
        "unit_hull_lod2", "unit_seams_lod2", "unit_eyes_lod2",
        "unit_hull_lod1", "tentacle_tube_lod2", "tentacle_links_lod1",
        "source_glass", "source_emissive", "orb_nucleus", "orb_shell",
    ):
        path = MESHES / f"{name}_mesh.mesh"
        buf = path.read_bytes()
        _fid, _ver, _off, count = struct.unpack_from("<IIII", buf, len(buf) - 16)
        (start,) = struct.unpack_from("<Q", buf, len(buf) - 16 - 16 * count)
        subsets = struct.unpack_from("<14I", buf, start + 12)[9]
        assert subsets == 1, (name, subsets)

    idle = [
        {"unit_id": "SNT-WRD-001", "caste": "warden", "state": "PATROLLING", "position": [14, 0.5, 0]},
        {"unit_id": "SNT-HRV-001", "caste": "harvester", "state": "PATROLLING", "position": [20, 0.5, 2]},
    ]
    wide = o.build_frame(idle, 95.1893, 1306.0)
    by_id = {u["unit_id"]: u for u in wide["units"]}
    assert by_id["SNT-WRD-001"]["lod"] == 2
    assert by_id["SNT-HRV-001"]["lod"] == 2

    fetch = [
        idle[0],
        {
            "unit_id": "SNT-HRV-001",
            "caste": "harvester",
            "state": "ENGAGED_HARVEST",
            "action": "arxiv",
            "current_task": "arxiv: fusion",
            "position": [20, 0.5, 2],
        },
    ]
    nodes = [{
        "node_id": "ht-1", "kind": "harvest_target", "label": "arXiv",
        "metadata": {"action": "arxiv", "target": "fusion", "unit_id": "SNT-HRV-001"},
    }]
    busy = o.build_frame(fetch, 95.1893, 1306.0, nodes=nodes)
    by_id = {u["unit_id"]: u for u in busy["units"]}
    assert by_id["SNT-WRD-001"]["lod"] == 2
    assert by_id["SNT-HRV-001"]["lod"] == 1
    assert by_id["SNT-HRV-001"].get("lod_forced") == 1
    assert by_id["SNT-HRV-001"]["harvest_target"] is not None

    # Focused unit also steps up to LOD1; LOD0 only when genuinely close.
    focused = o.build_frame(idle, 95.1893, 1306.0, selected_id="SNT-WRD-001")
    by_id = {u["unit_id"]: u for u in focused["units"]}
    assert by_id["SNT-WRD-001"]["lod"] == 1
    assert by_id["SNT-HRV-001"]["lod"] == 2

    close = o.build_frame(idle, 7.0, 1306.0, target=(14.0, 0.5, 0.0))
    by_id = {u["unit_id"]: u for u in close["units"]}
    # At 7 m the selected-side unit is a genuine close-up.
    assert by_id["SNT-WRD-001"]["lod"] in (0, 1)
    if by_id["SNT-WRD-001"]["lod"] == 0:
        assert by_id["SNT-WRD-001"]["height_px"] > o.LOD0_PX * (1 - o.HYST)

    # Reaching tips move toward the source; idle tips stay behind the hull.
    pose = (0.0, 0.0, 0.0)
    idle_pts = curves.control_points(pose=pose, yaw=0, scale=1.0, lod=1, slot=0, reach=0.0)
    reach_pts = curves.control_points(
        pose=pose, yaw=0, scale=1.0, lod=1, slot=0, reach=1.0, target=(20.0, 3.0, 0.0),
    )
    assert idle_pts[0][0] < 0  # root is on the tail (-X)
    assert reach_pts[-1][0] > idle_pts[-1][0]
    assert abs(reach_pts[-1][0] - 20.0) < abs(idle_pts[-1][0] - 20.0)


def test_source_nodes_carry_request_counts_and_idle_lit() -> None:
    idle = o.build_frame([], 96.0, nodes=[])
    assert len(idle["sourceNodes"]) == 4
    assert all(n["lit"] == 0.15 and n["scale"] == 1.0 and n["status"] == "idle" for n in idle["sourceNodes"])
    assert "source-beacon:" not in "".join(c["id"] for c in idle["conduits"])

    units = [{
        "unit_id": "SNT-HRV-001", "caste": "harvester", "state": "ENGAGED_HARVEST",
        "action": "arxiv", "current_task": "arxiv: fusion", "position": [10, 0.5, 2],
    }]
    nodes = [{
        "node_id": "ht-1", "kind": "harvest_target", "label": "arXiv",
        "metadata": {"action": "arxiv", "target": "fusion", "unit_id": "SNT-HRV-001"},
    }]
    busy = o.build_frame(units, 96.0, nodes=nodes)
    arxiv = next(n for n in busy["sourceNodes"] if n["id"] == "arxiv")
    wiki = next(n for n in busy["sourceNodes"] if n["id"] == "wikipedia")
    assert arxiv["open"] == 1 and arxiv["lit"] == 1.0 and arxiv["scale"] == 1.25
    assert arxiv["status"] == "1 requests open"
    assert wiki["open"] == 0 and wiki["lit"] == 0.15 and wiki["status"] == "idle"
    label = next(r for r in busy["sourceLabels"] if r["id"] == "arxiv")
    assert label["status"] == "1 requests open"


@isolated_render()
def test_pass_c_view_loads_orb_sources_and_tentacles(qt_app) -> None:
    from PySide6.QtCore import QObject, QSizeF, QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQuick import QQuickView

    view = QQuickView()
    view.engine().addImportPath(str(ASSETS))
    view.setColor(QColor("#0b0714"))
    view.setResizeMode(QQuickView.SizeViewToRootObject)
    view.setSource(QUrl.fromLocalFile(str(ASSETS / "OverseerView.qml")))
    assert view.status() == QQuickView.Status.Ready, view.errors()
    root = view.rootObject()
    root.setSize(QSizeF(1280, 800))
    view.show()
    qt_app.processEvents()
    units = [
        {"unit_id": "SNT-WRD-001", "caste": "warden", "state": "PATROLLING", "position": [8, 0.5, 0]},
        {
            "unit_id": "SNT-HRV-001", "caste": "harvester", "state": "ENGAGED_HARVEST",
            "action": "arxiv", "current_task": "arxiv: fusion", "position": [16, 0.5, 2],
        },
    ]
    nodes = [{
        "node_id": "ht-1", "kind": "harvest_target", "label": "arXiv",
        "metadata": {"action": "arxiv", "target": "fusion", "unit_id": "SNT-HRV-001"},
    }]
    root.applyFrame(o.build_frame(units, 95.1893, 800.0, nodes=nodes, snap={"memories_in_context": 3}))
    qt_app.processEvents()
    assert root.findChild(QObject, "orbNucleus") is not None
    assert root.findChild(QObject, "orbFilaments") is not None
    assert root.findChild(QObject, "orbShell") is not None
    assert root.findChild(QObject, "sourceGlass") is not None
    assert root.findChild(QObject, "tentacleTubesLod2") is not None
    assert int(root.property("memoryCount") or 0) == 3
    assert abs(float(root.property("orbEnergy")) - 0.3) < 1e-6
    counts = root.property("tentacleCounts")
    counts = counts.toVariant() if hasattr(counts, "toVariant") else counts
    assert (counts or {}).get("tube2", 0) >= 4  # the idle warden
    assert (counts or {}).get("links1", 0) >= 8  # the fetcher
    view.close()
    view.deleteLater()
    qt_app.processEvents()

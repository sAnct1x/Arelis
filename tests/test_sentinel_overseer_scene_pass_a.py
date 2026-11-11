"""Overseer scene, Pass A: idle nodes draw nothing; stars follow the hive."""

from __future__ import annotations

import struct
from pathlib import Path

from arelis.ui import overseer_runtime as o
from tests.overseer_render_helpers import isolated_render

MESHES = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer/meshes"


def test_idle_hive_nodes_draw_no_beacon_or_stream() -> None:
    idle = [
        {"node_id": "port-8443", "kind": "bastion", "position": [12.0, 1.0, -7.0]},
        {"node_id": "crystal-1", "kind": "memory", "position": [-4.0, 2.0, 9.0]},
    ]
    # The fixed source beacons (Web, arXiv, ...) still draw; the nodes do not.
    base = o.build_conduits([], [], active_sources=set())
    assert o.build_conduits([], idle, active_sources=set()) == base
    hot = [{"node_id": "port-22", "kind": "bastion", "severity": "high", "position": [3.0, 0.0, 3.0]}]
    assert len(o.build_conduits([], hot, active_sources=set())) > len(base)


def test_star_drift_follows_open_requests_not_throughput() -> None:
    swarm = o.layout_swarm(12)
    idle = o.build_frame(swarm, 96.0, 1306.0, nodes=[])
    assert idle["hiveActivity"] == 0
    # One open request: the hive's harvest_target node for that fetch.
    fetch = {
        "node_id": "fetch-1",
        "kind": "harvest_target",
        "position": [30.0, 2.0, 0.0],
        "metadata": {"unit_id": swarm[0]["unit_id"]},
    }
    assert 0 < o.build_frame(swarm, 96.0, 1306.0, nodes=[fetch])["hiveActivity"] < 1


def _mesh_subsets(path: Path) -> int:
    """Subset count of a Qt Quick 3D .mesh file: each subset is one draw call."""
    buf = path.read_bytes()
    _fid, _ver, _off, count = struct.unpack_from("<IIII", buf, len(buf) - 16)
    (start,) = struct.unpack_from("<Q", buf, len(buf) - 16 - 16 * count)
    # Mesh header (12 bytes), then 14 uint32 sizes; subsetsCount is the 10th.
    return struct.unpack_from("<14I", buf, start + 12)[9]


def test_each_instanced_unit_part_is_one_draw_call() -> None:
    meshes = sorted(MESHES.glob("lod*_mesh.mesh"))
    assert len(meshes) == 9
    assert {m.name: _mesh_subsets(m) for m in meshes} == {m.name: 1 for m in meshes}


@isolated_render()
def test_idle_repoll_pushes_nothing_and_view_keeps_the_runtime_orbit(qt_app) -> None:
    from PySide6.QtWidgets import QWidget

    from arelis.ui.sentinel_host import SentinelWindow, teardown_sentinel_window

    owner = QWidget()
    win = SentinelWindow(owner)
    owner.sentinel_window = win
    win.resize(1280, 800)
    scene = win._ensure_scene()
    win.show()
    qt_app.processEvents()
    root = scene.rootObject()
    units = [
        {"unit_id": f"SNT-WRD-00{i}", "caste": "warden", "state": "PATROLLING", "position": [i, 0, 0]}
        for i in (1, 2, 3)
    ]
    log = [{"timestamp": "2026-11-09T22:10:00", "category": "PATROL", "unit_id": "SNT-WRD-001", "message": "ok"}]

    def snap(ts: float) -> dict:
        return {"metrics": {}, "units": [dict(u) for u in units], "telemetry_log": list(log), "timestamp": ts}

    hud_resets: list[int] = []
    root.hudLogsChanged.connect(lambda: hud_resets.append(1))
    root.setProperty("sceneTime", 50.0)
    win.apply_snapshot(snap(1000.0))
    assert hud_resets
    hud_resets.clear()
    # Pass F pushes free-flow poses on each poll (no GPU lane orbit).
    # The Swarm log is unchanged, so applyHud does not fire again.
    first = {}
    for u in units:
        p = root.unitPositionOf(u["unit_id"])
        first[u["unit_id"]] = [p.property(k).toNumber() for k in "xyz"]
    root.setProperty("sceneTime", 53.0)
    win.apply_snapshot(snap(1003.0))
    assert hud_resets == []  # no applyHud
    moved = False
    for u in units:
        p = root.unitPositionOf(u["unit_id"])
        got = [p.property(k).toNumber() for k in "xyz"]
        assert all(abs(v) < 80 for v in got)
        if max(abs(a - b) for a, b in zip(got, first[u["unit_id"]], strict=True)) > 1e-3:
            moved = True
    assert moved
    teardown_sentinel_window(win)
    qt_app.processEvents()


@isolated_render()
def test_glow_costs_two_passes_per_level_not_a_fixed_fourteen(qt_app) -> None:
    """ExtendedSceneEnvironment glow ran 14 blur passes from half size whatever
    glowLevel said, which on the box cost about 20 ms p95 at 128 units. The
    scene's own bloom runs one quarter-size threshold pass, a horizontal and a
    vertical blur per level, one sum and the full-size tonemap."""
    import time

    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    from PySide6.QtQuick import QQuickView

    qml = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer/OverseerView.qml"
    view = QQuickView()
    view.engine().addImportPath(str(qml.parent))
    view.setSource(QUrl.fromLocalFile(str(qml)))
    assert view.status() == QQuickView.Status.Ready, view.errors()
    view.resize(1028, 749)
    view.show()
    root = view.rootObject()
    root.setProperty("reveal", 1.0)  # the entry fade-in is over
    ctx = QQmlEngine.contextForObject(root)

    def ev(src: str):
        return QQmlExpression(ctx, root, src).evaluate()[0]

    ev("view.renderStats.extendedDataCollectionEnabled = true")
    passes = 0
    end = time.monotonic() + 20
    while not passes and time.monotonic() < end:
        qt_app.processEvents()
        time.sleep(0.01)
        passes = int(ev("view.renderStats.renderPassCount") or 0)
    levels = int(root.property("glowLevels"))
    # The scene, the threshold pass, two blurs per level, the sum, the tonemap.
    assert passes == 1 + 1 + 2 * levels + 2
    view.deleteLater()
    qt_app.processEvents()

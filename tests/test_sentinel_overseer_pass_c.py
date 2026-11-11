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
    assert report[2]["parts"]["head"] == 1192
    assert report[2]["parts"]["tentacle"] == 66
    assert report[1]["parts"]["head"] == 6056
    # New balsam meshes are one draw each.
    for name in (
        "sentinel_head_lod2", "sentinel_head_lod1", "sentinel_tentacle_lod2",
        "sentinel_tentacle_lod1",
        "source_glass", "source_emissive", "orb_core", "orb_shell",
        "orb_filaments_d", "orb_ring_memory_d", "orb_ring_tools_d", "orb_ring_results_d",
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
    assert root.findChild(QObject, "orbCore") is not None
    assert root.findChild(QObject, "orbRingResults") is not None
    assert root.findChild(QObject, "memoryTilt") is not None
    assert root.findChild(QObject, "memorySpinNode") is not None
    assert root.findChild(QObject, "orbFilaments") is not None
    assert root.findChild(QObject, "orbShell") is not None
    assert root.findChild(QObject, "sourceGlass") is not None
    assert root.findChild(QObject, "tentacleLod2") is not None
    assert int(root.property("memoryCount") or 0) == 3
    assert abs(float(root.property("orbEnergy")) - 0.3) < 1e-6
    counts = root.property("tentacleCounts")
    counts = counts.toVariant() if hasattr(counts, "toVariant") else counts
    assert (counts or {}).get("2", 0) >= 10  # idle warden, 8 trail + 2 hook
    assert (counts or {}).get("1", 0) >= 13  # the fetcher, 11 trail + 2 hook
    view.close()
    view.deleteLater()
    qt_app.processEvents()



@isolated_render()
def test_orb_gains_at_thirty_eight_tok_leave_core_structure_readable(qt_app) -> None:
    """Pinned 38 tok/s must keep the core under the bloom knee.

    Energy still maps 0.3 idle to 1.0 at 60 tok/s. Pass C gains (nucleus
    1.8 E, filaments 2.2 E, shell 2.4, pulse 1.5) clipped the centre.
    The core peak is 0.78 * (0.5 + 0.5 E): about 0.68 at 38 tok/s.
    """
    from PySide6.QtCore import QByteArray, QObject, QSizeF, QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQml import QQmlComponent
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
    energy = o.orb_energy(38)
    root.setProperty("tokRate", 38)
    root.setProperty("orbEnergy", energy)
    root.setProperty("orbEnergyShown", energy)
    qt_app.processEvents()
    probe = QQmlComponent(view.engine())
    probe.setData(
        QByteArray(
            b"import QtQuick\n"
            b"QtObject {\n"
            b"    property real corePeak: 0\n"
            b"    property real fil: 0\n"
            b"    property real shell: 0\n"
            b"    property real pulse: 0\n"
            b"    property real power: 0\n"
            b"    property real body: 0\n"
            b"    function read(n, f, s, p) {\n"
            b"        var g = n.materials[0].coreGain\n"
            b"        var fl = n.materials[0].coreFloor\n"
            b"        var e = n.materials[0].energy\n"
            b"        corePeak = g * (fl + (1.0 - fl) * e)\n"
            b"        fil = f.materials[0].gain\n"
            b"        shell = s.materials[0].shellGain\n"
            b"        pulse = p.materials[0].shellGain\n"
            b"        power = s.materials[0].shellPower\n"
            b"        body = s.materials[0].shellBody\n"
            b"    }\n"
            b"}"
        ),
        QUrl(),
    )
    reader = probe.create()
    assert reader is not None, "; ".join(e.toString() for e in probe.errors())
    reader.read(
        root.findChild(QObject, "orbCore"),
        root.findChild(QObject, "orbFilaments"),
        root.findChild(QObject, "orbShell"),
        root.findChild(QObject, "orbPulseShell"),
    )
    core_peak = float(reader.property("corePeak"))
    fil_gain = float(reader.property("fil"))
    shell_gain = float(reader.property("shell"))
    pulse_gain = float(reader.property("pulse"))
    shell_power = float(reader.property("power"))
    shell_body = float(reader.property("body"))
    core_gain = float(root.property("orbCoreGain"))
    core_floor = float(root.property("orbCoreFloor"))
    expected_peak = core_gain * (core_floor + (1.0 - core_floor) * energy)
    assert core_peak <= 0.75, core_peak
    assert fil_gain <= 0.75, fil_gain
    assert shell_gain <= 0.80, shell_gain
    assert pulse_gain <= 0.65, pulse_gain
    assert abs(shell_power - 3.0) < 1e-5
    assert abs(shell_body - 0.06) < 1e-5
    assert abs(core_peak - expected_peak) < 1e-5
    assert abs(fil_gain - float(root.property("orbFilamentGain")) * energy) < 1e-5
    assert abs(shell_gain - float(root.property("orbShellGain"))) < 1e-5
    assert abs(pulse_gain - float(root.property("orbPulseShellGain"))) < 1e-5
    view.close()
    view.deleteLater()
    qt_app.processEvents()


def test_bloom_h_steps_in_output_size() -> None:
    """H passes of levels 2 and 3 must step in OUTPUT_SIZE, not INPUT_SIZE."""
    text = (ASSETS / "shaders" / "bloom_h.frag").read_text()
    # Strip comments so a mention of the old bug in a comment is fine.
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))
    assert "1.0 / OUTPUT_SIZE.x" in code
    assert "1.0 / INPUT_SIZE.x" not in code
    bloom = (ASSETS / "OverseerBloom.qml").read_text()
    assert "uKnee: 0.86" in bloom or "property real uKnee: 0.86" in bloom


@isolated_render()
def test_orb_rings_split_tilt_and_spin(qt_app) -> None:
    """Each ring is a fixed tilt parent with a spin-only child, so the ellipse stays put."""
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
    memory_tilt = root.findChild(QObject, "memoryTilt")
    memory_spin = root.findChild(QObject, "memorySpinNode")
    tools_tilt = root.findChild(QObject, "toolsTilt")
    tools_spin = root.findChild(QObject, "toolsSpinNode")
    results_tilt = root.findChild(QObject, "resultsTilt")
    assert memory_tilt is not None and memory_spin is not None
    assert tools_tilt is not None and tools_spin is not None
    assert results_tilt is not None
    assert memory_spin.parent() is memory_tilt
    assert tools_spin.parent() is tools_tilt
    # Results have no spin child: titles ride the orbit in 2D.
    assert root.findChild(QObject, "resultsSpinNode") is None

    def euler(node):
        v = node.property("eulerRotation")
        return (float(v.x()), float(v.y()), float(v.z()))

    mx, my, mz = euler(memory_tilt)
    assert abs(mx - 6.62) < 1e-4 and abs(my) < 1e-4 and abs(mz + 28.75) < 1e-4
    tx, ty, tz = euler(tools_tilt)
    assert abs(tx + 0.22) < 1e-4 and abs(ty) < 1e-4 and abs(tz - 13.97) < 1e-4
    rx, ry, rz = euler(results_tilt)
    assert abs(rx + 4.52) < 1e-4 and abs(ry) < 1e-4 and abs(rz - 2.86) < 1e-4
    root.setProperty("memorySpin", 40.0)
    root.setProperty("toolsSpin", 15.0)
    qt_app.processEvents()
    assert abs(euler(memory_spin)[1] - 40.0) < 1e-4
    assert abs(euler(memory_tilt)[1]) < 1e-4  # tilt Y stays 0 while the child spins
    assert abs(euler(tools_spin)[1] - 15.0) < 1e-4
    ring = root.findChild(QObject, "orbRingMemory")
    assert ring is not None and ring.parent() is memory_spin
    view.close()
    view.deleteLater()
    qt_app.processEvents()


@isolated_render()
def test_core_focus_preset_frames_the_orb(qt_app) -> None:
    """coreFocus targets the orb, hides units, and leaves 24 m unit focus alone."""
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
    root.setSize(QSizeF(2110, 1306))
    view.setGeometry(0, 0, 2110, 1306)
    view.show()
    qt_app.processEvents()
    units = [
        {"unit_id": "SNT-WRD-001", "caste": "warden", "state": "PATROLLING", "position": [8, 0.5, 0]},
    ]
    root.applyFrame(o.build_frame(units, 95.1893, 1306.0))
    qt_app.processEvents()
    assert o.CLOSE_DISTANCE == 24.0
    assert abs(float(root.property("specDistance")) - 126.4) < 1e-4
    # Overview is still the default.
    assert str(root.property("cameraMode")) == "overview"
    entered = root.enterCoreFocus(True)
    assert entered is True
    qt_app.processEvents()
    assert bool(root.property("coreMode")) is True
    assert str(root.property("cameraMode")) == "core"
    assert abs(float(root.property("cameraTargetX")) - 0.0) < 1e-4
    assert abs(float(root.property("cameraTargetY")) - 1.6) < 1e-4
    assert abs(float(root.property("cameraTargetZ")) - 0.0) < 1e-4
    assert abs(float(root.property("cameraPitch")) - 22.0) < 1e-4
    free = root.freeViewportRect()
    expected = o.core_focus_distance(1306.0, float(free.width()))
    assert abs(float(root.property("cameraDistance")) - expected) < 1e-3
    assert expected >= 15.0
    # Unit bodies are hidden; the orb stays up.
    hull = root.findChild(QObject, "instanced-warden:2:head")
    if hull is not None:
        assert hull.property("visible") is False
    assert root.findChild(QObject, "orbCore") is not None
    # 24 m unit focus is unchanged once we leave core.
    root.selectUnit("SNT-WRD-001")
    assert root.focusSelectedUnit() is True
    qt_app.processEvents()
    assert bool(root.property("coreMode")) is False
    assert float(root.property("cameraDistance")) == o.CLOSE_DISTANCE
    assert abs(float(root.property("cameraPitch")) - o.pitch_deg(o.CLOSE_DISTANCE)) < 1e-3
    # Re-enter and wheel out past 24 m hands off to the overview ease.
    root.enterCoreFocus(True)
    qt_app.processEvents()
    root.setProperty("cameraDistance", 24.0)
    root.applyWheel(-1)
    qt_app.processEvents()
    assert bool(root.property("coreMode")) is False
    # Wheel inside core stays in 10..24 m.
    root.enterCoreFocus(True)
    qt_app.processEvents()
    d0 = float(root.property("cameraDistance"))
    root.applyWheel(1)
    qt_app.processEvents()
    d1 = float(root.property("cameraDistance"))
    assert 10.0 <= d1 <= 24.0
    assert d1 <= d0 + 1e-6
    root.exitCoreFocus(True)
    qt_app.processEvents()
    assert bool(root.property("coreMode")) is False
    assert str(root.property("cameraMode")) == "overview"
    view.close()
    view.deleteLater()
    qt_app.processEvents()

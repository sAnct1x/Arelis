"""Overseer Pass E2: Iris fix-c05bb78 label keep-out and instance colour."""

from __future__ import annotations

from pathlib import Path

from arelis.ui import overseer_runtime as o
from tests.overseer_render_helpers import isolated_render

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"


@isolated_render()
def test_instance_colour_stays_white_and_caste_goes_to_unit_tex(qt_app) -> None:
    """Qt multiplies mesh COLOR by the instance colour. Heads were tinted
    by eye colour and tentacle radius / prong / slit data picked up the
    caste channels. Instance colour must stay white; caste lives in
    unitTex T7.yzw."""
    from PySide6.QtCore import QObject, QSizeF, QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQuick import QQuickView

    qml = (ASSETS / "OverseerView.qml").read_text()
    assert 'e.color = "#ffffff"' in qml
    assert "cullMode: Material.NoCulling" in qml

    # Sanitizer blue is 0.42; that channel used to smash tentacle prong ids.
    units = [
        {
            "unit_id": "SNT-SAN-001",
            "caste": "sanitizer",
            "state": "PATROLLING",
            "position": [8.0, 0.6, 0.0],
            "heading": [1, 0, 0],
        },
    ]
    frame = o.build_frame(units, 95.1893, 1306.0)
    view = QQuickView()
    view.engine().addImportPath(str(ASSETS))
    view.setColor(QColor("#0b0714"))
    view.setResizeMode(QQuickView.SizeViewToRootObject)
    view.setSource(QUrl.fromLocalFile(str(ASSETS / "OverseerView.qml")))
    assert view.status() == QQuickView.Status.Ready, view.errors()
    root = view.rootObject()
    root.setSize(QSizeF(1280, 800))
    view.setGeometry(0, 0, 1280, 800)
    view.show()
    qt_app.processEvents()
    root.setProperty("paused", True)
    root.setProperty("reveal", 1.0)
    root.applyFrame(frame)
    root.refreshUnitTex()
    qt_app.processEvents()
    tex = root.findChild(QObject, "overseerUnitTex")
    assert tex is not None
    row = tex.sampleRow(0)
    assert row and len(row) >= 32, row
    # T7.yzw = linear caste colour of #f2c56b
    want = tuple((c / 255.0) ** 2.2 for c in (0xF2, 0xC5, 0x6B))
    got = (float(row[29]), float(row[30]), float(row[31]))
    assert all(abs(a - b) < 0.02 for a, b in zip(got, want, strict=True)), (got, want)
    # Don't close the view: sampleRow holds the texture buffer and close can stall.


@isolated_render()
def test_unit_close_drops_tools_label_off_the_header(qt_app) -> None:
    """In unit close the orb Tools block was placed because the shell was
    large on screen, then nudged up into the Sentinels header. The block
    layout is for core focus only, and any label that hits a HUD keep-out
    or the frame is dropped, not nudged."""
    from PySide6.QtCore import QSizeF, QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    from PySide6.QtQuick import QQuickView

    qml = (ASSETS / "OverseerView.qml").read_text()
    assert "shell.rs >= 90 && root.coreMode" in qml
    assert "var rects = hudKeepOut()" in qml

    units = [
        {
            "unit_id": "SNT-HRV-001",
            "caste": "harvester",
            "state": "ENGAGED_HARVEST",
            "action": "arxiv",
            "current_task": "arxiv: fusion",
            "position": [13.69, 0.6, 8.28],
            "heading": [1, 0, 0],
            "target_node_id": "ht-1",
        },
    ]
    nodes = [{
        "node_id": "ht-1",
        "kind": "harvest_target",
        "label": "arXiv",
        "position": [14.0, 1.0, 8.0],
        "status": "EXTRACTING",
        "progress": 0.4,
        "metadata": {"action": "arxiv", "target": "fusion", "unit_id": "SNT-HRV-001"},
    }]
    snap = {
        "memories_in_context": 14,
        "tools_running": [
            {"id": "summarize", "elapsed": 4, "timeout": 20},
            {"id": "read_pdf", "elapsed": 2, "timeout": 20},
            {"id": "search_arxiv", "elapsed": 1, "timeout": 20},
        ],
    }
    frame = o.build_frame(units, 16.0, 1306.0, nodes=nodes, snap=snap)

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
    root.setProperty("paused", True)
    root.setProperty("reveal", 1.0)
    root.applyFrame(frame)
    root.selectUnit("SNT-HRV-001")
    root.setProperty("cameraDistance", 16.0)
    root.setProperty("cameraPitch", o.pitch_deg(16.0))
    root.setProperty("cameraTargetX", 13.69)
    root.setProperty("cameraTargetY", 0.6)
    root.setProperty("cameraTargetZ", 8.28)
    root.setProperty("coreMode", False)
    qt_app.processEvents()
    ctx = QQmlEngine.contextForObject(root)

    def ev(src: str):
        return QQmlExpression(ctx, root, src).evaluate()[0]

    ev("projectOrbLabels()")
    qt_app.processEvents()

    def titles() -> list[str]:
        blocks = root.property("orbLabelBlocks")
        blocks = blocks.toVariant() if hasattr(blocks, "toVariant") else blocks
        out = []
        for b in blocks or []:
            if isinstance(b, dict):
                out.append(str(b.get("title") or b.get("id") or ""))
            else:
                out.append(str(b.property("title") if hasattr(b, "property") else b))
        return out

    close_titles = titles()
    assert "Tools" not in close_titles, f"Tools label in unit close: {close_titles}"
    # Nothing placed in the header keep-out (margin + 72 + 8).
    blocks = root.property("orbLabelBlocks")
    blocks = blocks.toVariant() if hasattr(blocks, "toVariant") else blocks
    header_y1 = round(1306 * 0.02) + 72 + 8
    for b in blocks or []:
        if isinstance(b, dict):
            y, h = float(b.get("y") or 0), float(b.get("h") or 0)
        else:
            y, h = float(b.property("y") or 0), float(b.property("h") or 0)
        assert y + h <= header_y1 or y >= header_y1, f"label overlaps header: y={y} h={h} titles={close_titles}"

    ev("enterCoreFocus(true)")
    qt_app.processEvents()
    core_titles = titles()
    assert "Tools" in core_titles, f"Tools missing in core view: {core_titles}"

"""Overseer Pass E: tentacles actually write pixels (the hide-all test)."""

from __future__ import annotations

import time
from pathlib import Path

from arelis.ui import overseer_runtime as o
from tests.overseer_render_helpers import isolated_render

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"


def _changed_pixels(a, b) -> int:
    a = a.convertToFormat(a.Format.Format_RGB32)
    b = b.convertToFormat(b.Format.Format_RGB32)
    w, h = a.width(), a.height()
    changed = 0
    for y in range(h):
        for x in range(w):
            if a.pixel(x, y) != b.pixel(x, y):
                changed += 1
    return changed


@isolated_render(native_gl=True)
def test_hiding_tentacles_changes_scene_pixels(qt_app) -> None:
    """At f47b487, hiding every tentacle Model changed 0 pixels because the
    curve texture never received the unit rows from QML (all zeros, NaN
    positions). After Pass E the hide-all diff must be nonzero."""
    from PySide6.QtCore import QObject, QSizeF, QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQuick import QQuickView

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
    frame = o.build_frame(units, 16.0, 800.0, nodes=nodes, snap={"memories_in_context": 3})

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
    root.selectUnit("SNT-HRV-001")
    root.setProperty("cameraDistance", 16.0)
    root.setProperty("cameraPitch", o.pitch_deg(16.0))
    root.setProperty("cameraTargetX", 13.69)
    root.setProperty("cameraTargetY", 0.6)
    root.setProperty("cameraTargetZ", 8.28)
    root.refreshUnitTex()
    qt_app.processEvents()
    end = time.monotonic() + 4
    while time.monotonic() < end:
        qt_app.processEvents()
        time.sleep(0.02)

    counts = root.property("tentacleCounts")
    counts = counts.toVariant() if hasattr(counts, "toVariant") else counts
    total = sum(int((counts or {}).get(k, 0) or 0) for k in ("0", "1", "2"))
    assert total > 0, f"no tentacle instances: {counts}"

    tex = root.findChild(QObject, "overseerUnitTex")
    assert tex is not None
    row = tex.sampleRow(0)
    assert row, "unitTex row 0 is empty"
    assert any(abs(float(v)) > 1e-6 for v in row[:4]), f"unitTex row still zero: {row[:8]}"

    img1 = view.grabWindow()
    for name in ("tentacleLod0", "tentacleLod1", "tentacleLod2"):
        model = root.findChild(QObject, name)
        if model is not None:
            model.setProperty("visible", False)
    qt_app.processEvents()
    time.sleep(0.05)
    qt_app.processEvents()
    img2 = view.grabWindow()
    changed = _changed_pixels(img1, img2)
    assert changed > 0, f"hiding tentacles changed {changed} pixels"
    view.close()
    view.deleteLater()
    qt_app.processEvents()

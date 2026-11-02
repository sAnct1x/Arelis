"""ARELIS_SURFACE=quick, slice 2: the GPU draws the ring, strands, dust and hub threads.

The worker then paints only what is not ported (beads, stems, tethers) on a clear layer, the
surface's QML loads with the orbit state it binds, and that state emits only on change.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QUrl
from PySide6.QtGui import QImage, QPainter


def test_worker_paints_only_the_unported_layer_and_the_gpu_orbit_state_emits_on_change(
    qt_app,
) -> None:
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    from arelis.ui.filament_field import FilamentField
    from arelis.ui.persona_face.orbit_state import OrbitState
    from arelis.ui.persona_face.quick_surface import SURFACE_QML

    rect = QRect(0, 0, 1200, 700)
    field = FilamentField()
    field.set_hub(QPointF(1000, 320), 900)
    for _ in range(60):
        field.tick(0.033)
    x, y = field._point(0.30, 0.0, rect).toTuple()

    def alpha_at(paint) -> int:
        img = QImage(rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        paint(p, rect)
        p.end()
        return img.pixelColor(int(x), int(y)).alpha()

    assert alpha_at(field._paint) == 255  # the old paint: void and strands everywhere
    assert alpha_at(field.paint_unported) == 0  # no void, no strand: the GPU has them

    state = OrbitState()
    state.update(field, rect, now=0.0)
    first = state.emits
    assert first > 0 and state.property("active") and state.property("hasHub")
    state.update(field, rect, now=0.5)
    assert state.emits == first  # nothing moved, nothing sent
    field.set_state("speak")
    state.update(field, rect, now=0.6)
    assert state.property("weather") == "speak" and state.emits > first

    engine = QQmlEngine()
    engine.rootContext().setContextProperty("orbitState", state)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(SURFACE_QML)))
    root = component.create()
    assert root is not None, [e.toString() for e in component.errors()]
    from PySide6.QtQuick import QQuickItem

    assert root.findChild(QQuickItem, "orbitGpu").property("visible") is True

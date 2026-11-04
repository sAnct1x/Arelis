"""Filament, ARELIS_SURFACE=quick: the orbit tree stays fully on and keeps moving under the open
chat tile. It used to fade out, then to hold still there; Christopher wants it always on and live."""

from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRect, QUrl
from PySide6.QtTest import QTest

TREE_LAYERS = (
    "orbitTreeFibers",
    "orbitTreeGlow",
    "orbitPool",
    "orbitPulses",
    "orbitFlares",
)


def test_the_tree_keeps_drawing_under_the_open_chat_and_its_fibers_keep_moving(qt_app) -> None:
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickItem

    from arelis.ui.filament_field import FilamentField
    from arelis.ui.persona_face.orbit_state import OrbitState
    from arelis.ui.persona_face.quick_surface import SURFACE_QML

    rect = QRect(0, 0, 1200, 700)
    field = FilamentField()
    field.set_hub(QPointF(1000, 320), 900)
    state = OrbitState()
    state.update(field, rect, now=0.0)
    engine = QQmlEngine()
    engine.rootContext().setContextProperty("orbitState", state)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(SURFACE_QML)))
    root = component.create()
    assert root is not None, [e.toString() for e in component.errors()]

    clock = root.findChild(QObject, "orbitFiberClock")
    # The chat tile open over the crown, as the atmosphere tick used to report it.
    cx, cy, rx, ry = field.ellipse(rect, settled=True)
    field.cover = QRect(int(cx - rx), int(cy - ry), int(rx * 2), int(ry * 2.6))
    state.update(field, rect, now=0.1)
    QTest.qWait(300)
    start = clock.property("currentFrame")
    QTest.qWait(600)  # longer than the old fade
    assert clock.property("running") and clock.property("currentFrame") > start  # fibers redraw
    drawn = [root.findChild(QQuickItem, n).property("visible") for n in TREE_LAYERS]
    assert drawn == [True] * len(TREE_LAYERS)
    assert root.findChild(QQuickItem, "orbitTree").property("treeOn") == 1.0

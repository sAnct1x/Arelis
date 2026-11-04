"""Filament, ARELIS_SURFACE=quick: the orbit tree stays fully on under the open chat tile (it used
to fade out; Christopher wants it always on), but its fibers hold still there, drawn from their
cached texture, so no fiber redraws under the chat (the frame cost while generating)."""

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


def test_the_tree_keeps_drawing_under_the_open_chat_with_its_fibers_held(qt_app) -> None:
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
    assert clock.property("running")
    # The chat tile open over the crown, as the atmosphere tick reports it.
    cx, cy, rx, ry = field.ellipse(rect, settled=True)
    field.cover = QRect(int(cx - rx), int(cy - ry), int(rx * 2), int(ry * 2.6))
    state.update(field, rect, now=0.1)
    QTest.qWait(900)  # longer than the old fade
    drawn = [root.findChild(QQuickItem, n).property("visible") for n in TREE_LAYERS]
    assert drawn == [True] * len(TREE_LAYERS)
    assert root.findChild(QQuickItem, "orbitTree").property("treeOn") == 1.0
    assert not clock.property("running")  # no fiber redraws under the chat
    field.cover = None  # the chat closed
    state.update(field, rect, now=0.2)
    assert clock.property("running")

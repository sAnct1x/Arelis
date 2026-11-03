"""Filament, ARELIS_SURFACE=quick: while the open chat tile covers the orbit tree, the tree fades
out and its layers stop drawing (it costs nothing under the tile); when the chat closes it fades
back in and draws again. A tile off to the side leaves it alone."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QUrl
from PySide6.QtTest import QTest

TREE_LAYERS = (
    "orbitTreeTex0",
    "orbitTreeTex1",
    "orbitTreeTex2",
    "orbitTreeTex3",
    "orbitTreeGlow",
    "orbitPool",
    "orbitPulses",
    "orbitFlares",
)


def test_the_tree_stops_drawing_under_the_open_chat_and_comes_back_when_it_closes(qt_app) -> None:
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

    def drawn() -> list[bool]:
        QTest.qWait(900)  # past the fade
        return [root.findChild(QQuickItem, n).property("visible") for n in TREE_LAYERS]

    cx, cy, rx, ry = field.ellipse(rect, settled=True)
    field.cover = QRect(int(cx - rx), int(cy - ry), int(rx * 2), int(ry * 2.6))  # over the crown
    state.update(field, rect, now=0.1)
    assert drawn() == [False] * len(TREE_LAYERS)
    field.cover = None  # the chat closed
    state.update(field, rect, now=0.2)
    assert drawn() == [True] * len(TREE_LAYERS)
    field.cover = QRect(1100, 0, 100, 120)  # a tile in the corner, off the tree
    state.update(field, rect, now=0.3)
    assert drawn() == [True] * len(TREE_LAYERS)

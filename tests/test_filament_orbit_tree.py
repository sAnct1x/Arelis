"""Filament, ARELIS_SURFACE=quick: in idle the orbit is Iris's v11b tree. Its trunk stands on the
floor under the ring, forks inside it, and the floor link runs left from her feet (below her
hub) to the trunk base; the GPU layers that draw it (fibers, packets, flares) ship baked. It
stays a tree while she thinks or speaks: the tree's layers never fade out as form rises."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QUrl


def test_tree_stands_under_the_ring_and_stays_while_she_thinks(qt_app) -> None:
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickItem

    from arelis.ui.filament_field import FilamentField
    from arelis.ui.persona_face.orbit_state import OrbitState
    from arelis.ui.persona_face.qq3d_avatar import QML_DIR
    from arelis.ui.persona_face.quick_surface import SURFACE_QML

    rect = QRect(0, 0, 1200, 700)
    field = FilamentField()
    field.set_hub(QPointF(1000, 320), 900)
    state = OrbitState()
    state.update(field, rect, now=0.0)
    cx, cy, rx, ry = field.ellipse(rect, settled=True)
    tree, feet = state.property("tree"), state.property("feet")
    base_x, base_y, fork_x, fork_y = tree.x(), tree.y(), tree.z(), tree.w()

    assert feet.x() == 1000 and feet.y() == base_y  # her feet: on the floor below her hub
    assert base_y > cy + ry and base_y > 0.9 * rect.height()  # the base is on the floor
    assert abs(base_x - cx) < rx * 0.1 and base_x < 900  # under the ring, left of her band
    assert base_x < feet.x()  # the floor link runs left from her feet to the root
    assert cy < fork_y < base_y and abs(fork_x - cx) < rx * 0.1  # it forks inside the ring

    engine = QQmlEngine()
    engine.rootContext().setContextProperty("orbitState", state)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(SURFACE_QML)))
    root = component.create()
    assert root is not None, [e.toString() for e in component.errors()]
    orbit = next(i for i in root.findChildren(QQuickItem) if i.property("treeOn") is not None)
    for form in (0.0, 1.0):  # idle, then thinking / speaking (form 1)
        orbit.setProperty("form", form)
        assert orbit.property("treeOn") == 1.0, form
        for name in ("orbitTree", "orbitTree1", "orbitPulses", "orbitFlares"):
            layer = root.findChild(QQuickItem, name)
            assert layer is not None and layer.property("visible") is True, (name, form)
            shader = QML_DIR / layer.property("vertexShader").toString()
            assert shader.is_file(), shader

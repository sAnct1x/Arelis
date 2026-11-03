"""Filament, ARELIS_SURFACE=quick: in idle the orbit is Iris's v11b tree. Its trunk stands on the
floor under the ring, forks inside it, and the floor link runs left from just outside her near
foot (not between her feet) to the trunk base; the GPU layers that draw it (fibers, packets,
flares) ship baked. It stays a tree while she thinks or speaks: the tree's layers never fade
out as form rises."""

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

    # The floor link starts off her near foot, toward the tree, not between her feet (her hub)
    assert 1000 - 0.2 * rect.height() < feet.x() < 1000 - 0.1 * rect.height()
    assert feet.y() == base_y
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


def test_tree_waits_hidden_before_the_load_starts(qt_app) -> None:
    """Her T-pose: before begin_ring_growth the GPU tree is held at 'wait' with no growth."""
    from arelis.ui.filament_field import FilamentField
    from arelis.ui.persona_face.orbit_state import OrbitState

    field = FilamentField()
    field.set_hub(QPointF(1000, 320), 900)
    assert field.ring_started is False
    state = OrbitState()
    state.update(field, QRect(0, 0, 1200, 700), now=0.0)
    assert state.property("ringPhase") == "wait"
    assert state.property("ringGrow") == 0.0


def _crown_field(qt_app):
    from arelis.ui.filament_field import FilamentField
    from arelis.ui.persona_face.orbit_state import OrbitState

    rect = QRect(0, 0, 1280, 696)
    field = FilamentField()
    field.set_hub(QPointF(1000, 330), 860)
    state = OrbitState()
    state.update(field, rect, now=0.0)
    return field, state, rect


def test_tiles_stay_in_the_crown_while_she_thinks(qt_app) -> None:
    """The limbs end on the tiles: tiles that rode the current swept them toward her."""
    from arelis.ui.filament_field import FLOATS, FREE_FLOATS

    field, _state, rect = _crown_field(qt_app)
    cx, cy, rx, ry = field.ellipse(rect, settled=True)
    for form, t in ((0.0, 3.0), (1.0, 11.0), (1.0, 40.0)):
        field.form, field.time = form, t
        for name, _t, _pad in FLOATS:
            if name in FREE_FLOATS:
                continue
            p = field.bead_point(name, rect)
            assert abs(p.x() - cx) < rx + 60 and abs(p.y() - cy) < ry + 60, (name, form, p)


def test_reality_sits_top_left_and_the_tree_reaches_it(qt_app) -> None:
    field, state, rect = _crown_field(qt_app)
    home = field.home_rect(rect)
    p = field.bead_point("reality", rect)
    assert p.x() < home.left() + home.width() * 0.2 and p.y() < home.top() + home.height() * 0.3
    assert state.property("reality") == field.reality_center(rect)  # its limb's end (pulses)


def test_chat_strand_leaves_her_chest_not_her_hub(qt_app) -> None:
    field, _state, rect = _crown_field(qt_app)
    field.set_heart(QPointF(1004, 250))
    assert field.thread_start("chat", rect) == QPointF(1004, 250)

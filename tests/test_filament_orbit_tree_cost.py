"""Filament, ARELIS_SURFACE=quick: under the orbit tree the old ring strands and hub threads have
alpha 0, so they are not drawn at all; and each half of the tree's fibers is a GridMesh with as
many columns as tree.vert maps (twigs take fewer per fiber than the limbs)."""

from __future__ import annotations

import re

from PySide6.QtCore import QPointF, QRect, QUrl


def test_under_the_tree_the_hidden_ring_layers_draw_nothing(qt_app) -> None:
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickItem

    from arelis.ui.filament_field import FilamentField
    from arelis.ui.persona_face.orbit_state import OrbitState
    from arelis.ui.persona_face.qq3d_avatar import QML_DIR
    from arelis.ui.persona_face.quick_surface import SURFACE_QML

    field = FilamentField()
    field.set_hub(QPointF(1000, 320), 900)
    state = OrbitState()
    state.update(field, QRect(0, 0, 1200, 700), now=0.0)
    engine = QQmlEngine()
    engine.rootContext().setContextProperty("orbitState", state)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(SURFACE_QML)))
    root = component.create()
    assert root is not None, [e.toString() for e in component.errors()]
    orbit = next(i for i in root.findChildren(QQuickItem) if i.property("treeOn") is not None)

    def drawn_by(stage: str) -> list[QQuickItem]:  # the Repeaters' layers are child items only
        items = orbit.childItems()
        return [i for i in items if i.property("vertexShader") == QUrl(stage)]

    strands = drawn_by("orbit/strand.vert.qsb") + drawn_by("orbit/thread.vert.qsb")
    assert len(strands) == 7 and not any(s.property("visible") for s in strands)

    src = (QML_DIR / "orbit" / "tree.vert").read_text(encoding="utf-8")
    consts = dict(re.findall(r"const float (\w+) = ([\d.]+);", src))
    k, k_twig = float(consts["K"]), float(consts["K_TWIG"])
    f_twig, f_lroot, fibers = (float(consts[n]) for n in ("F_TWIG", "F_LROOT", "FIBERS"))
    cols = f_twig * k + (f_lroot - f_twig) * k_twig + (fibers - f_lroot) * k
    for name in ("orbitTree", "orbitTree1", "orbitTree2", "orbitTree3"):
        mesh = root.findChild(QQuickItem, name).property("mesh")
        assert mesh.property("resolution").width() + 1 == cols / 4, name
    assert (cols / 4) % k == 0 and cols / 2 < f_twig * k  # the quarters split between fibers
    assert (cols * 3 / 4 - f_twig * k) % k_twig == 0

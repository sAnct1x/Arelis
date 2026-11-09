"""Which orbit layer is which draw in a PIX/RenderDoc capture.

Qt Quick (6.11) names passes, not items: with QSG_RHI_PROFILE=1 a capture shows the markers
"Qt Quick scene render", "Qt Quick opaque batches" and "Qt Quick alpha batches", and the
ShaderEffect draws inside carry no item names. Each orbit layer's GridMesh has its own size,
though, so its vertex and index counts identify it. This prints them from QuickOrbit.qml
itself (QQuickGridMesh: (w+1)*(h+1) vertices, h*2*(w+2) strip indices), so the table can't
drift from the scene.

    python tools/orbit_draw_table.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# What each objectName is called in the review threads.
ROLE = {
    "orbitTree": "fibers (quarter 0)",
    "orbitTree1": "fibers (quarter 1)",
    "orbitTree2": "fibers (quarter 2)",
    "orbitTree3": "fibers (quarter 3)",
    "orbitTreeGlow": "glow",
    "orbitPool": "pool",
    "orbitPulses": "pulses",
    "orbitFlares": "flares",
    "orbitDust": "dust",
}


def rows():
    from PySide6.QtCore import QPointF, QRect, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    QGuiApplication.instance() or QGuiApplication([])
    from arelis.ui.filament_field import FilamentField
    from arelis.ui.persona_face.orbit_state import OrbitState
    from arelis.ui.persona_face.qq3d_avatar import QML_DIR

    field = FilamentField()
    field.set_hub(QPointF(1200, 500), 1000)
    st = OrbitState()
    st.update(field, QRect(0, 0, 1600, 900), now=0.0)
    engine = QQmlEngine()
    engine.rootContext().setContextProperty("orbitState", st)
    comp = QQmlComponent(engine)
    comp.setData(
        b"import QtQuick\nQuickOrbit { st: orbitState }\n",
        QUrl.fromLocalFile(str(QML_DIR / "_t.qml")),
    )
    orbit = comp.create()
    if orbit is None:
        raise SystemExit(comp.errorString())
    out = []

    def walk(it):
        for c in it.children():  # Repeater delegates are QObject children too
            yield c
            yield from walk(c)

    for item in walk(orbit):
        if item.metaObject().indexOfProperty("fragmentShader") < 0 or not item.property("visible"):
            continue  # not a ShaderEffect
        name = item.objectName() or "(unnamed)"
        mesh = item.property("mesh")
        if mesh is not None:
            res = mesh if hasattr(mesh, "width") else mesh.property("resolution")
            w, h = res.width(), res.height()
        else:
            w, h = 1, 1
        verts, idx = (w + 1) * (h + 1), h * 2 * (w + 2)
        out.append(
            (
                name,
                ROLE.get(item.objectName(), ""),
                verts,
                idx,
                item.property("vertexShader").toString() or "-",
            )
        )
    return out


def main() -> None:
    print(f"{'objectName':<30} {'role':<38} {'verts':>7} {'indices':>8}  vertex shader")
    for name, role, v, i, vs in rows():
        print(f"{name:<30} {role:<38} {v:>7} {i:>8}  {vs}")


if __name__ == "__main__":
    main()

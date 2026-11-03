"""While she generates, a packet reaches every tile (six crown tiles and reality) within a few
seconds; on the calm 15 s loop only the two or three whose turn fell in a reply ever lit."""

from __future__ import annotations

import itertools
import re

import pytest
from PySide6.QtCore import Q_ARG, QMetaObject, QPointF, QRect, Qt, QUrl
from PySide6.QtWidgets import QApplication


def _offsets(glsl: str) -> dict[int, float]:
    body = glsl[glsl.index("float packetOffset(int j)") :]
    body = body[: body.index("}")]
    found = {int(j): float(v) for j, v in re.findall(r"j == (\d+)\) return ([0-9.]+)", body)}
    found[10] = float(re.search(r"\n\s*return ([0-9.]+);", body).group(1))
    return found


def test_every_tile_gets_a_packet_soon_after_she_starts_generating() -> None:
    QApplication.instance() or QApplication([])
    from PySide6.QtQml import QQmlComponent, QQmlEngine

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
        pytest.skip(comp.errorString())
    glsl = (QML_DIR / "orbit" / "common.glsl").read_text(encoding="utf-8")
    loop = float(re.search(r"const float TREE_LOOP = ([0-9.]+)", glsl).group(1))
    offsets = _offsets(glsl)
    assert set(offsets) >= {0, 1, 2, 3, 4, 5, 10}

    def step(seconds: float) -> list[float]:
        seen = []
        for _ in range(int(seconds * 60)):
            QMetaObject.invokeMethod(
                orbit, "step", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", 1 / 60)
            )
            seen.append(float(orbit.property("packetFlow")))
        return seen

    step(20.0)  # calm
    field.set_state("think")
    st.update(field, QRect(0, 0, 1600, 900), now=1.0)
    flows = step(5.0)
    lit = set()
    for a, b in itertools.pairwise(flows):
        for j in (0, 1, 2, 3, 4, 5, 10):
            pa, pb = (offsets[j] + a / loop) % 1.0, (offsets[j] + b / loop) % 1.0
            if pa < 0.82 <= pb:  # its packet reaches the tile (flare.vert: phase 0.82)
                lit.add(j)
    assert lit == {0, 1, 2, 3, 4, 5, 10}
    # And each of those seven nodes has a flare to light: the flare mesh is 4 columns a node.
    from PySide6.QtCore import QObject

    flares = orbit.findChild(QObject, "orbitFlares")
    res = flares.property("mesh").property("resolution")
    assert (res.width() + 1) // 4 == 7

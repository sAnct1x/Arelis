"""face.js holds her head level and a little to her left whatever the body clip does to her chest.

The clips curl her chest forward and turn it (v14k: head down ~15-30 deg and turned to her right),
because the head was only driven on top of its parent. Here a stand-in chest is pitched 20 deg
forward and yawed 15 deg to her right after face.js starts; the head's world forward must stay
level and point slightly to her left (+x).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

QtQml = pytest.importorskip("PySide6.QtQml")
QtCore = pytest.importorskip("PySide6.QtCore")

FACE = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "persona_q3d" / "face.js"

QML = """import QtQuick
import "%s" as Face
QtObject {
    function run() {
        const q = Qt.quaternion(1, 0, 0, 0)
        const bone = (n, kids) => { const b = Qt.createQmlObject("import QtQuick; QtObject { property quaternion rotation; property quaternion sceneRotation; property vector3d position; property var children: []; property var parent }", this)
            b.objectName = n; b.rotation = q; b.sceneRotation = q; b.children = kids || []; return b }
        const head = bone("CC_Base_Head"), chest = bone("CC_Base_Spine02", [bone("CC_Base_NeckTwist01"), head])
        const root = bone("ellah", [chest])
        const link = (n) => n.children.forEach((c) => { c.parent = n; link(c) }); link(root)
        const f = Face.create(root, { seed: 5 })
        const mul = (a, b) => [a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3], a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
            a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1], a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0]]
        const rad = Math.PI / 180, pitch = [Math.cos(10 * rad), Math.sin(10 * rad), 0, 0]   // 20 deg: +z tips down
        const yaw = [Math.cos(-7.5 * rad), 0, Math.sin(-7.5 * rad), 0]                          // 15 deg toward -x (her right)
        const c = mul(yaw, pitch)
        chest.sceneRotation = Qt.quaternion(c[0], c[1], c[2], c[3])
        const out = []
        for (let i = 0; i < 120; i++) { f.update(1 / 30)
            const h = head.rotation, w = mul(c, [h.scalar, h.x, h.y, h.z])
            const z = mul(mul(w, [0, 0, 0, 1]), [w[0], -w[1], -w[2], -w[3]])   // world +z of the head
            out.push([Math.atan2(z[1], z[3]) / rad, Math.asin(z[2]) / rad]) }
        return JSON.stringify(out)
    }
}
"""


def test_head_stays_level_and_slightly_left_when_the_chest_leans_and_turns(
    qapp: object, tmp_path: Path
) -> None:
    src = tmp_path / "t.qml"
    src.write_text(QML % FACE.as_uri())
    eng = QtQml.QQmlEngine()
    comp = QtQml.QQmlComponent(eng, QtCore.QUrl.fromLocalFile(str(src)))
    obj = comp.create()
    assert obj is not None, [e.toString() for e in comp.errors()]
    raw = QtCore.QMetaObject.invokeMethod(obj, "run", QtCore.Q_RETURN_ARG("QVariant"))
    rows = json.loads(raw)
    yaws, pitches = [r[0] for r in rows], [r[1] for r in rows]
    assert max(abs(p) for p in pitches) < 4, pitches  # level, not carried down by the chest
    assert 1 < sum(yaws) / len(yaws) < 10, yaws  # a little to her left, not to her right

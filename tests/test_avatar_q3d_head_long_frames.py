"""Her head stays in its designed sway when frames arrive slowly.

The mixer hands face.js up to 0.1 s per frame after a stall. The head springs were Euler steps, and at
that step the talking nod spring rang out until her head swung far off to one side. Runs face.js on a
bare Qt Quick 3D bone chain, so the private model is not needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

QtQml = pytest.importorskip("PySide6.QtQml")
QtCore = pytest.importorskip("PySide6.QtCore")

FACE = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "persona_q3d" / "face.js"

QML = """import QtQuick
import QtQuick3D
import "%s" as Face
Node {
    id: root; objectName: "ellah"
    Node { id: neck; objectName: "CC_Base_NeckTwist01"
        Node { id: head; objectName: "CC_Base_Head"
            Node { objectName: "CC_Base_JawRoot" } Node { objectName: "CC_Base_L_Eye" } Node { objectName: "CC_Base_R_Eye" } } }
    function deg(n) { return 2 * Math.acos(Math.min(1, Math.abs(n.rotation.scalar))) * 180 / Math.PI }
    function run() {
        const f = Face.create(root, { seed: 5 })
        f.setState("speaking")
        let worst = 0
        for (let i = 0; i < 100; i++) {
            f.setSpeaking(0.2 + 0.7 * Math.abs(Math.sin(i * 0.4)))
            f.update(0.1)
            const a = deg(head) + deg(neck)
            if (!(a <= worst)) worst = a
        }
        return worst
    }
}
"""


def test_head_stays_in_range_at_the_longest_mixer_frame(qapp: object, tmp_path: Path) -> None:
    src = tmp_path / "t.qml"
    src.write_text(QML % FACE.as_uri())
    eng = QtQml.QQmlEngine()
    comp = QtQml.QQmlComponent(eng, QtCore.QUrl.fromLocalFile(str(src)))
    obj = comp.create()
    assert obj is not None, [e.toString() for e in comp.errors()]
    worst = QtCore.QMetaObject.invokeMethod(obj, "run", QtCore.Q_RETURN_ARG("QVariant"))
    assert worst < 20  # head plus neck, degrees; about 7 at this frame length, 3 at 60 fps

"""Mixer.qml rests her body a little toward viewer's left, whatever turn the clip holds.

Christopher (2026-11-02): even after #517 her resting angle read as turned toward viewer's right. The clips
swing her hips and some hold a turn (Talking sits ~17 deg right for seconds), and nothing took it back.
A stand-in clip holds the Hip 17 deg right; after 10 s her hips must face slightly left of forward.
"""

from __future__ import annotations

from pathlib import Path

import pytest

QtQml = pytest.importorskip("PySide6.QtQml")
QtCore = pytest.importorskip("PySide6.QtCore")

PKG = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "persona_q3d"

QML = """import QtQuick
import "%s"
QtObject {
    function run() {
        const q = Qt.quaternion(1, 0, 0, 0)
        const mk = (s) => Qt.createQmlObject("import QtQuick; QtObject { " + s + " }", this)
        const bone = (n, parent) => { const b = mk("property quaternion rotation; property var parent; property quaternion sceneRotation: parent ? parent.sceneRotation.times(rotation) : rotation")
            b.objectName = n; b.rotation = q; b.parent = parent || null; return b }
        const hip = bone("CC_Base_Hip"), waist = bone("CC_Base_Waist", hip), s1 = bone("CC_Base_Spine01", waist), s2 = bone("CC_Base_Spine02", s1)
        const r = 17 / 2 * Math.PI / 180; hip.rotation = Qt.quaternion(Math.cos(r), 0, Math.sin(r), 0)   // the clip holds her 17 deg right
        const groups = [hip, waist, s1, s2].map((b) => { const g = mk("property var target; property string property: 'rotation'"); g.target = b; return g })
        const tl = mk("property var keyframeGroups; property real startFrame: 0; property real endFrame: 4000; property real currentFrame; property bool enabled; property var animations")
        tl.objectName = "v2_BreathingIdle"; tl.keyframeGroups = groups; tl.animations = [mk("property bool running")]
        const mx = Qt.createQmlObject('import "%s"; Mixer { running: false }', this)
        mx.model = { data: [tl] }; mx.init()
        for (let i = 0; i < 300; i++) mx.tick(1 / 30)   // 10 s
        const h = hip.sceneRotation, z = h.times(Qt.quaternion(0, 0, 0, 1)).times(h.conjugated())
        return Math.atan2(z.x, z.z) * 180 / Math.PI
    }
}
"""


def test_body_rests_slightly_left_when_the_clip_holds_her_right(qapp: object, tmp_path: Path) -> None:
    src = tmp_path / "t.qml"
    src.write_text(QML % (PKG.as_uri(), PKG.as_uri()))
    eng = QtQml.QQmlEngine()
    comp = QtQml.QQmlComponent(eng, QtCore.QUrl.fromLocalFile(str(src)))
    obj = comp.create()
    assert obj is not None, [e.toString() for e in comp.errors()]
    yaw = QtCore.QMetaObject.invokeMethod(obj, "run", QtCore.Q_RETURN_ARG("QVariant"))
    assert -6 < yaw < -1, yaw  # slightly toward viewer's left, not the clip's 17 deg right

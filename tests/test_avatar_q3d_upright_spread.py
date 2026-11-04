"""Mixer.qml stands her upright by spreading the turn over the spine, not folding her belly at the Waist.

v14k turned only CC_Base_Waist back 6.5 deg each frame on top of the clip, so the Waist alone bent
~16 deg in Talking and her stomach creased at that joint. A stand-in skeleton with a clip that holds
rest checks each of Waist, Spine01 and Spine02 takes a third and the chest still turns 6.5 deg.
"""

from __future__ import annotations

import json
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
        const groups = [hip, waist, s1, s2].map((b) => { const g = mk("property var target; property string property: 'rotation'"); g.target = b; return g })
        const tl = mk("property var keyframeGroups; property real startFrame: 0; property real endFrame: 4000; property real currentFrame; property bool enabled; property var animations")
        tl.objectName = "v2_BreathingIdle"; tl.keyframeGroups = groups; tl.animations = [mk("property bool running")]
        const mx = Qt.createQmlObject('import "%s"; Mixer { running: false }', this)
        mx.model = { data: [tl] }; mx.init(); mx.tick(1 / 30)
        const deg = (r) => 2 * Math.atan2(-r.x, r.scalar) * 180 / Math.PI   // backward turn about x
        return JSON.stringify([deg(waist.rotation), deg(s1.rotation), deg(s2.rotation), deg(s2.sceneRotation)])
    }
}
"""


def test_upright_turn_is_spread_over_waist_and_spine(qapp: object, tmp_path: Path) -> None:
    src = tmp_path / "t.qml"
    src.write_text(QML % (PKG.as_uri(), PKG.as_uri()))
    eng = QtQml.QQmlEngine()
    comp = QtQml.QQmlComponent(eng, QtCore.QUrl.fromLocalFile(str(src)))
    obj = comp.create()
    assert obj is not None, [e.toString() for e in comp.errors()]
    waist, s1, s2, chest = json.loads(QtCore.QMetaObject.invokeMethod(obj, "run", QtCore.Q_RETURN_ARG("QVariant")))
    for d in (waist, s1, s2):
        assert d == pytest.approx(6.5 / 3, abs=0.05), (waist, s1, s2)  # no single joint folds
    assert chest == pytest.approx(6.5, abs=0.05)  # she still stands as upright

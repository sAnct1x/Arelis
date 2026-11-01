"""persona_q3d/face.js drives every copy of a morph target (balsam repeats them per submesh).

Runs face.js in a QML engine against a stand-in node tree (two models, each name listed twice), so
the private model is not needed: speech moves the mouth morphs, a blink hold closes both lids, and
every copy of a name carries the same weight.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

QtQml = pytest.importorskip("PySide6.QtQml")
QtCore = pytest.importorskip("PySide6.QtCore")

FACE = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "persona_q3d" / "face.js"

QML = """import QtQml
import "%s" as Face
QtObject {
    function run() {
        const q = Qt.quaternion(1, 0, 0, 0)
        const bone = (n, kids) => ({ objectName: n, rotation: q, sceneRotation: q, position: Qt.vector3d(0, 0, 0), children: kids || [] })
        const names = ["V_Open", "V_Wide", "V_Lip_Open", "V_Tight_O", "Jaw_Open", "Eye_Blink_L", "Eye_Blink_R"]
        const model = (n) => ({ objectName: n, children: [], morphTargets: names.concat(names).map((m) => ({ objectName: m, weight: 0 })) })
        const head = bone("CC_Base_Head", [bone("CC_Base_JawRoot"), bone("CC_Base_L_Eye"), bone("CC_Base_R_Eye")])
        const models = [model("Body"), model("Female_Angled")]
        const root = { objectName: "ellah", sceneRotation: q, children: [bone("CC_Base_NeckTwist01", [head])].concat(models) }
        const link = (n) => n.children.forEach((c) => { c.parent = n; link(c) }); link(root)
        const f = Face.create(root, { seed: 5 })
        f.setState("speaking"); f.setSpeaking(0.9)
        let mouth = 0
        for (let i = 0; i < 40; i++) { f.update(0.05); mouth = Math.max(mouth, f.morph("V_Open") + f.morph("V_Wide") + f.morph("V_Tight_O") + f.morph("V_Lip_Open")) }
        f.holdBlink(1); f.update(0.05)
        const w = {}
        for (const m of models) for (const t of m.morphTargets) (w[t.objectName] = w[t.objectName] || []).push(t.weight)
        return JSON.stringify({ mouth, w, copies: f.stats.copies })
    }
}
"""


def test_speech_and_blink_reach_every_morph_copy(qapp: object, tmp_path: Path) -> None:
    src = tmp_path / "t.qml"
    src.write_text(QML % FACE.as_uri())
    eng = QtQml.QQmlEngine()
    comp = QtQml.QQmlComponent(eng, QtCore.QUrl.fromLocalFile(str(src)))
    obj = comp.create()
    assert obj is not None, [e.toString() for e in comp.errors()]
    ret = QtCore.QMetaObject.invokeMethod(obj, "run", QtCore.Q_RETURN_ARG("QVariant"))
    r = json.loads(ret)
    assert r["copies"] == 28
    assert r["mouth"] > 0.2  # syllables from the level open the mouth
    assert r["w"]["Eye_Blink_L"] == [1, 1, 1, 1] and r["w"]["Eye_Blink_R"] == [1, 1, 1, 1]
    for name, ws in r["w"].items():
        assert len(set(ws)) == 1, name  # every copy of a name carries the same weight

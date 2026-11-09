"""Mixer.qml writes each of her bones once per frame, and her pose is the same as when it sampled on the bones.

Every write to a bone makes Qt recompute the scene transform of that bone and of every bone below it, and notify
each of her 48 Skins, all on the GUI thread. Mixer.tick used to sample its clips on the bones themselves: each bone
went to rest, then took the clip's value, then the blend, then the Hip and spine took settle() and upright() on
top, so one frame walked her skeleton several times (18.7 ms per tick on the box). Now the Timelines write to proxy
objects and every bone takes its final value once.

Two copies of a stand-in skeleton (real Quick 3D Nodes, real Timelines with keyframes): one driven by the reference
(the mixer's previous tick, which sampled on the bones), one by Mixer.qml. Same seed, same frame times, through
idle, a fade into speaking and the fades between speaking clips. Every frame both poses must match, and no bone of
the Mixer's copy may change more than once.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

QtQml = pytest.importorskip("PySide6.QtQml")
QtCore = pytest.importorskip("PySide6.QtCore")
pytest.importorskip("PySide6.QtQuick3D")

PKG = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "persona_q3d"


def _q(deg_x: float, deg_y: float) -> str:
    import math

    ax, ay = math.radians(deg_x) / 2, math.radians(deg_y) / 2
    # Rx * Ry
    w, x, y, z = (
        math.cos(ax) * math.cos(ay),
        math.sin(ax) * math.cos(ay),
        math.cos(ax) * math.sin(ay),
        math.sin(ax) * math.sin(ay),
    )
    return f"Qt.quaternion({w}, {x}, {y}, {z})"


def _group(target: str, keys: list[tuple[int, str]], prop: str = "rotation") -> str:
    kf = " ".join(f"Keyframe {{ frame: {f}; value: {v} }}" for f, v in keys)
    return f'KeyframeGroup {{ target: {target}; property: "{prop}"; {kf} }}'


def _clip(name: str, end: int, groups: list[str]) -> str:
    return (
        f'Timeline {{ objectName: "{name}"; startFrame: 0; endFrame: {end}; enabled: false\n'
        f"    animations: TimelineAnimation {{ duration: {end}; from: 0; to: {end}; running: false }}\n    "
        + "\n    ".join(groups)
        + " }"
    )


def _skeleton(p: str) -> str:
    """Her bone chain from the figure turn down to an arm, a leg, a thumb and an unkeyed jaw."""
    clips = [
        _clip(
            "v2_BreathingIdle",
            3000,
            [
                _group(f"{p}hip", [(0, _q(2, 10)), (1500, _q(-3, 18)), (3000, _q(2, 10))]),
                _group(
                    f"{p}hip",
                    [(0, "Qt.vector3d(0, 0, 107)"), (3000, "Qt.vector3d(1, 0, 106)")],
                    "position",
                ),
                _group(f"{p}waist", [(0, _q(8, 0)), (3000, _q(4, 6))]),
                _group(f"{p}s1", [(0, _q(-5, 2)), (3000, _q(3, -4))]),
                _group(f"{p}s2", [(0, _q(1, 1)), (3000, _q(6, -2))]),
                _group(f"{p}arm", [(0, _q(30, 5)), (3000, _q(10, -20))]),
                _group(f"{p}thigh", [(0, _q(-4, 0)), (3000, _q(6, 3))]),
            ],
        ),
        _clip(
            "Talking",
            2400,
            [  # the thumb is keyed only here; the waist's first key comes late
                _group(f"{p}hip", [(0, _q(-6, -15)), (2400, _q(4, 20))]),
                _group(f"{p}waist", [(600, _q(12, 4)), (2400, _q(-2, -8))]),
                _group(f"{p}s2", [(0, _q(-3, 9)), (2400, _q(2, -9))]),
                _group(f"{p}arm", [(0, _q(-20, 40)), (1200, _q(15, 0)), (2400, _q(-20, 40))]),
                _group(f"{p}thumb", [(0, _q(25, 0)), (2400, _q(40, 10))]),
            ],
        ),
        _clip(
            "Agreeing",
            2000,
            [
                _group(f"{p}hip", [(0, _q(3, 5)), (2000, _q(-2, -5))]),
                _group(f"{p}s1", [(0, _q(4, 4)), (2000, _q(-6, 2))]),
                _group(f"{p}arm", [(0, _q(5, 5)), (2000, _q(-5, 25))]),
            ],
        ),
    ]
    return f"""Node {{ eulerRotation.y: 25
    Node {{ objectName: "Armature"; scale: Qt.vector3d(0.01, 0.01, 0.01)
        Node {{ objectName: "CC_Base_BoneRoot"; rotation: Qt.quaternion(0.707107, -0.707107, 0, 0)
            Node {{ id: {p}hip; objectName: "CC_Base_Hip"; position: Qt.vector3d(0, 0, 107.16); rotation: Qt.quaternion(0.707107, 0.707107, 0, 0)
                Node {{ objectName: "CC_Base_Pelvis"; Node {{ id: {p}thigh; objectName: "CC_Base_L_Thigh"; rotation: {_q(3, 1)} }} }}
                Node {{ id: {p}waist; objectName: "CC_Base_Waist"; position: Qt.vector3d(0, 6.6, 1.8); rotation: {_q(15, 0)}
                    Node {{ id: {p}s1; objectName: "CC_Base_Spine01"; position: Qt.vector3d(0, 3.9, 0); rotation: {_q(-16, 0)}
                        Node {{ id: {p}s2; objectName: "CC_Base_Spine02"; position: Qt.vector3d(0, 12.7, 0); rotation: {_q(2, 0)}
                            Node {{ id: {p}jaw; objectName: "CC_Base_JawRoot"; rotation: {_q(1, 0)} }}
                            Node {{ id: {p}arm; objectName: "CC_Base_L_Upperarm"; rotation: {_q(0, 70)}
                                Node {{ id: {p}thumb; objectName: "CC_Base_L_Thumb2"; rotation: {_q(2, 2)} }} }} }} }} }} }} }} }}
    {chr(10).join(clips)}
}}"""


QML = """import QtQuick
import QtQuick3D
import QtQuick.Timeline
import "%(pkg)s"
import "%(pkg)s/mixer.js" as Logic
Node {
    property Node ref: %(ref)s
    property Node fig: %(fig)s
    Mixer { id: mx; running: false; model: fig }

    // The reference: Mixer.tick as it was before the proxies, sampling on the bones themselves.
    property var r: ({})
    function refInit() {
        var d = ref.data, tl = {}, dur = {}, seen = {}, bones = [], keep = []
        for (var i = 0; i < d.length; i++) {
            var t = d[i]
            if (!t || !t.objectName || t.keyframeGroups === undefined) continue
            tl[t.objectName] = t; dur[t.objectName] = (t.endFrame - t.startFrame) / 1000 / (Logic.RATE[t.objectName] || 1)
            for (var k = 0; k < t.keyframeGroups.length; k++) {
                var g = t.keyframeGroups[k], key = g.target.objectName + "." + g.property
                if (seen[key]) continue
                seen[key] = true
                var b = { node: g.target, prop: g.property, rest: mx.copy(g.target[g.property]) }
                if (mx.keepBase.test(g.target.objectName)) keep.push(b); else bones.push(b)
            }
        }
        var spine = []
        for (var u = 0; u < mx.uprightBones.length; u++)
            for (i = 0; i < bones.length; i++) if (bones[i].node.objectName === mx.uprightBones[u] && bones[i].prop === "rotation") spine.push(bones[i].node)
        var hip = null
        for (i = 0; i < bones.length; i++) if (bones[i].node.objectName === "CC_Base_Hip" && bones[i].prop === "rotation") hip = bones[i].node
        for (var n in tl) tl[n].enabled = true
        r = { tl: tl, bones: bones, keep: keep, spine: spine, hip: hip, hipYaw: 0, logic: Logic.create(dur, mx.seed) }
    }
    function refSample(name, t) {
        for (var i = 0; i < r.bones.length; i++) r.bones[i].node[r.bones[i].prop] = r.bones[i].rest
        var tl = r.tl[name], f = tl.startFrame + t * (Logic.RATE[name] || 1) * 1000
        if (tl.currentFrame === f) tl.currentFrame = f + 0.001
        tl.currentFrame = f
        var out = new Array(r.bones.length)
        for (i = 0; i < r.bones.length; i++) out[i] = mx.copy(r.bones[i].node[r.bones[i].prop])
        return out
    }
    function refUpright() {
        var a = -mx.uprightDeg / r.spine.length * Math.PI / 360
        var f = ref.sceneRotation, fq = Qt.quaternion(f.scalar, f.x, f.y, f.z)
        var rx = fq.times(Qt.quaternion(Math.cos(a), Math.sin(a), 0, 0)).times(fq.inverted())
        for (var i = 0; i < r.spine.length; i++) {
            var b = r.spine[i], p = b.parent.sceneRotation, pq = Qt.quaternion(p.scalar, p.x, p.y, p.z)
            b.rotation = pq.inverted().times(rx).times(pq).times(b.rotation)
        }
    }
    function refSettle(dt) {
        var f = ref.sceneRotation, fq = Qt.quaternion(f.scalar, f.x, f.y, f.z)
        var h = r.hip.sceneRotation, hq = fq.inverted().times(Qt.quaternion(h.scalar, h.x, h.y, h.z))
        var z = hq.times(Qt.quaternion(0, 0, 0, 1)).times(hq.conjugated())
        var yaw = Math.atan2(z.x, z.z) * 180 / Math.PI
        r.hipYaw += (yaw - r.hipYaw) * Math.min(1, dt / 3)
        var a = (mx.restYawDeg - r.hipYaw) * Math.PI / 360, p = r.hip.parent.sceneRotation
        var pq = Qt.quaternion(p.scalar, p.x, p.y, p.z), ry = fq.times(Qt.quaternion(Math.cos(a), 0, Math.sin(a), 0)).times(fq.inverted())
        r.hip.rotation = pq.inverted().times(ry).times(pq).times(r.hip.rotation)
    }
    function refTick(dt) {
        var held = [], i
        for (i = 0; i < r.keep.length; i++) held.push(mx.copy(r.keep[i].node[r.keep[i].prop]))
        var bl = r.logic.step(dt)
        var cur = refSample(bl.cur.name, bl.cur.t)
        if (bl.prev) {
            var prev = refSample(bl.prev.name, bl.prev.t)
            for (i = 0; i < r.bones.length; i++) r.bones[i].node[r.bones[i].prop] = mx.mixValue(prev[i], cur[i], bl.w)
        } else {
            for (i = 0; i < r.bones.length; i++) r.bones[i].node[r.bones[i].prop] = cur[i]
        }
        refSettle(dt); refUpright()
        for (i = 0; i < r.keep.length; i++) r.keep[i].node[r.keep[i].prop] = held[i]
        return !!bl.prev
    }

    function nodes(n, out) { out.push(n); for (var i = 0; i < n.children.length; i++) nodes(n.children[i], out); return out }
    function run() {
        var a = nodes(ref, []), b = nodes(fig, []), changes = [], first = ""
        b.forEach(function (n) {
            var ir = changes.push(0) - 1, ip = changes.push(0) - 1
            n.rotationChanged.connect(function () { changes[ir]++ }); n.positionChanged.connect(function () { changes[ip]++ })
        })
        refInit(); mx.init()
        var dt = 1 / 30, delta = 0, most = 0, fades = 0, ticks = 0
        for (var s = 0; s < 2; s++) {
            r.logic.setState(s ? "speaking" : "idle"); mx.setState(s ? "speaking" : "idle")
            for (var k = 0; k < (s ? 180 : 60); k++) {
                for (var c = 0; c < changes.length; c++) changes[c] = 0
                if (refTick(dt)) fades++
                mx.tick(dt); ticks++
                most = Math.max(most, Math.max.apply(null, changes))
                for (var i = 0; i < a.length; i++) {
                    var qa = a[i].rotation, qb = b[i].rotation, pa = a[i].position, pb = b[i].position
                    var dd = Math.max(Math.abs(qa.scalar - qb.scalar), Math.abs(qa.x - qb.x), Math.abs(qa.y - qb.y),
                                      Math.abs(qa.z - qb.z), Math.abs(pa.x - pb.x) / 100, Math.abs(pa.y - pb.y) / 100, Math.abs(pa.z - pb.z) / 100)
                    if (dd > 1e-5 && !first) first = ticks + " " + a[i].objectName + " " + qa + " " + qb + " " + mx.clip
                    delta = Math.max(delta, dd)
                }
            }
        }
        return JSON.stringify({ ticks: ticks, fades: fades, delta: delta, most: most, first: first })
    }
}
"""


def test_mixer_writes_each_bone_once_and_poses_her_as_before(qapp: object, tmp_path: Path) -> None:
    src = tmp_path / "t.qml"
    src.write_text(
        QML % {"pkg": PKG.as_uri(), "ref": _skeleton("a_"), "fig": _skeleton("b_")},
        encoding="utf-8",
    )
    eng = QtQml.QQmlEngine()
    comp = QtQml.QQmlComponent(eng, QtCore.QUrl.fromLocalFile(str(src)))
    obj = comp.create()
    assert obj is not None, [e.toString() for e in comp.errors()]
    out = json.loads(QtCore.QMetaObject.invokeMethod(obj, "run", QtCore.Q_RETURN_ARG("QVariant")))
    assert out["fades"] >= 30, out  # the run went through crossfades, not only one held clip
    assert out["delta"] < 1e-5, out  # the same pose as sampling on the bones, every frame
    assert out["most"] <= 1, out  # no bone changes twice in one frame

import QtQuick
import QtQuick.Timeline
import "mixer.js" as Logic

// Mixer.qml: body clips for the Quick 3D avatar. Attach to the balsam model root (Ellah_anim) and call setState(name)
// with the anim-mixer.js state names (idle, listening, thinking, speaking, done; talking and rest are aliases).
// Qt Quick 3D Timelines cannot blend, so each frame the mixer samples the one or two weighted clips by setting each
// Timeline's currentFrame (which writes the bones synchronously), reads the bones back, and writes the blend itself.
// Before each sample every clip bone goes back to rest, so a track balsam dropped (the constant Thumb2/3 rotations)
// reads as rest instead of whatever the previous clip left. Head, neck, jaw, eye, tongue and teeth bones are never
// written (KEEP_BASE in anim-mixer.js): the face module drives them.
QtObject {
    id: mix
    property var model: null
    property bool running: true
    property int seed: 1234567
    readonly property string clip: _clip
    readonly property string mode: _mode
    readonly property real weight: _w   // weight of the incoming clip, 1 when no fade is running
    signal ticked(real dt)   // after each frame's clip pose is written: the face drives on top of it here
    property string _clip: ""
    property string _mode: "idle"
    property real _w: 1
    property var _logic: null
    property var _tl: ({})        // clip name -> Timeline
    property var _bones: []       // [{node, prop, rest}] union of every clip's tracks, minus KEEP_BASE
    property var _keep: []        // [{node, prop}] bones a clip touches that the mixer must leave alone

    // The clips (Mixamo, retargeted onto her CC skeleton) carry her trunk ~6 deg further forward than her own rest
    // pose (hip to neck: +1 deg in v2_BreathingIdle against -5.4 at rest). Every frame the blended waist is turned
    // back about the world x axis by this much, so she stands as upright as her rest pose (POSES.md). The turn is
    // spread evenly over Waist, Spine01 and Spine02: all of it on the Waist alone folded her belly at that one joint
    // (Talking: ~16 deg there against ~5 on each spine bone above it).
    property real uprightDeg: 6.5
    readonly property var uprightBones: ["CC_Base_Waist", "CC_Base_Spine01", "CC_Base_Spine02"]
    property var _spine: []
    readonly property var keepBase: /^CC_Base_(NeckTwist0[12]|Head|FacialBone|JawRoot|.*Eye|Tongue.*|Teeth.*|UpperJaw)$/

    function setState(name) { if (_logic) _logic.setState(name); else _pending = name }
    function play(name) { if (_logic) _logic.play(name) }   // test hook: hold one clip
    property string _pending: ""

    function init() {
        var d = model.data, tl = {}, dur = {}, seen = {}, bones = [], keep = []
        for (var i = 0; i < d.length; i++) {
            var t = d[i]
            if (!t || !t.objectName || t.keyframeGroups === undefined) continue
            tl[t.objectName] = t
            dur[t.objectName] = (t.endFrame - t.startFrame) / 1000 / rate(t.objectName)
            t.animations[0].running = false
            for (var k = 0; k < t.keyframeGroups.length; k++) {
                var g = t.keyframeGroups[k], key = g.target.objectName + "." + g.property
                if (seen[key]) continue
                seen[key] = true
                var b = { node: g.target, prop: g.property, rest: copy(g.target[g.property]) }
                if (keepBase.test(g.target.objectName)) keep.push(b); else bones.push(b)
            }
        }
        _tl = tl; _bones = bones; _keep = keep
        var spine = []
        for (var u = 0; u < uprightBones.length; u++)
            for (i = 0; i < bones.length; i++) if (bones[i].node.objectName === uprightBones[u] && bones[i].prop === "rotation") spine.push(bones[i].node)
        _spine = spine
        // dropped constant tracks: the bone still has to be reset, and it is not in any group of most clips, but it
        // is in Talking's, so the union above already holds it. Every Timeline stays enabled and idle; a sample is
        // a currentFrame write.
        for (var n in tl) tl[n].enabled = true
        _logic = Logic.create(dur, seed)
        if (_pending) _logic.setState(_pending)
        _mode = _logic.state().mode
    }

    function rate(name) { return Logic.RATE[name] || 1 }

    function sample(name, t) {
        for (var i = 0; i < _bones.length; i++) _bones[i].node[_bones[i].prop] = _bones[i].rest
        var tl = _tl[name], f = tl.startFrame + t * rate(name) * 1000
        if (tl.currentFrame === f) tl.currentFrame = f + 0.001   // a write only evaluates on change
        tl.currentFrame = f
        var out = new Array(_bones.length)
        for (i = 0; i < _bones.length; i++) out[i] = copy(_bones[i].node[_bones[i].prop])
        return out
    }

    // Qt 6 hands value types to JS as live references that re-read the property, so a sample has to be copied out
    // before the next clip is sampled over the same bones.
    function copy(v) {
        return v.scalar !== undefined ? Qt.quaternion(v.scalar, v.x, v.y, v.z) : Qt.vector3d(v.x, v.y, v.z)
    }

    function mixValue(a, b, w) {   // a at 1 - w, b at w
        if (a.scalar !== undefined) {   // quaternion: nlerp on the short arc
            var sg = (a.scalar * b.scalar + a.x * b.x + a.y * b.y + a.z * b.z) < 0 ? -1 : 1, u = 1 - w, v = w * sg
            return Qt.quaternion(u * a.scalar + v * b.scalar, u * a.x + v * b.x, u * a.y + v * b.y, u * a.z + v * b.z).normalized()
        }
        return Qt.vector3d(a.x + (b.x - a.x) * w, a.y + (b.y - a.y) * w, a.z + (b.z - a.z) * w)
    }

    function upright() {   // each spine bone: local = parent^-1 * Rx(-uprightDeg / n) * parent * local, base first
        if (!_spine.length || !uprightDeg) return
        var a = -uprightDeg / _spine.length * Math.PI / 360, rx = Qt.quaternion(Math.cos(a), Math.sin(a), 0, 0)
        for (var i = 0; i < _spine.length; i++) {
            var b = _spine[i], p = b.parent.sceneRotation, pq = Qt.quaternion(p.scalar, p.x, p.y, p.z)
            b.rotation = pq.inverted().times(rx).times(pq).times(b.rotation)
        }
    }

    function tick(dt) {
        if (!_logic) return
        var held = []
        for (var i = 0; i < _keep.length; i++) held.push(copy(_keep[i].node[_keep[i].prop]))
        var bl = _logic.step(dt)
        if (bl) {
            var cur = sample(bl.cur.name, bl.cur.t)
            if (bl.prev) {
                var prev = sample(bl.prev.name, bl.prev.t)
                for (i = 0; i < _bones.length; i++) _bones[i].node[_bones[i].prop] = mixValue(prev[i], cur[i], bl.w)
            } else {
                for (i = 0; i < _bones.length; i++) _bones[i].node[_bones[i].prop] = cur[i]
            }
            _clip = bl.cur.name; _w = bl.w
            upright()
        }
        for (i = 0; i < _keep.length; i++) _keep[i].node[_keep[i].prop] = held[i]
        _mode = _logic.state().mode
    }

    property FrameAnimation _frames: FrameAnimation {
        running: mix.running && mix.model !== null
        onTriggered: { if (!mix._logic) mix.init(); var dt = Math.min(frameTime, 0.1); mix.tick(dt); mix.ticked(dt) }
    }
}

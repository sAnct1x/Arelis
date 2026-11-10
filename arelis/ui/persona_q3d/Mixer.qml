import QtQuick
import QtQuick.Timeline
import "mixer.js" as Logic

// Mixer.qml: body clips for the Quick 3D avatar. Attach to the balsam model root (Ellah_anim) and call setState(name)
// with the anim-mixer.js state names (idle, listening, thinking, speaking, done; talking and rest are aliases).
// Qt Quick 3D Timelines cannot blend, so each frame the mixer samples the one or two weighted clips by setting each
// Timeline's currentFrame and reading the values back, then writes the blend itself.
// The Timelines write to proxy objects outside her scene, never to her bones. Every write to a bone of hers makes Qt
// recompute the scene transform of that bone and every bone below it at once and notify each of her 48 Skins, so
// sampling on the bones themselves (rest, then clip, then blend, then settle and upright) cost the GUI thread several
// passes over her whole skeleton per frame. Now each bone is written once per frame with its final value, and
// settle() and upright() work on the frame's pose in JS before it is written.
// Before each sample every proxy goes back to rest, so a track balsam dropped (the constant Thumb2/3 rotations)
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
    property var _bones: []       // [{node, prop, rest, proxy}] union of every clip's tracks, minus KEEP_BASE
    property var _keep: []        // [{node, prop, rest, proxy}] bones a clip touches that the mixer must leave alone

    // The clips (Mixamo, retargeted onto her CC skeleton) carry her trunk ~6 deg further forward than her own rest
    // pose (hip to neck: +1 deg in v2_BreathingIdle against -5.4 at rest). Every frame the blended waist is turned
    // back about the world x axis by this much, so she stands as upright as her rest pose (POSES.md). The turn is
    // spread evenly over Waist, Spine01 and Spine02: all of it on the Waist alone folded her belly at that one joint
    // (Talking: ~16 deg there against ~5 on each spine bone above it).
    property real uprightDeg: 6.5
    // The clips swing her hips about the vertical, and some hold a turn for seconds (Talking sits ~17 deg toward
    // viewer's right), so her resting body angle drifted right of the camera. settle() takes the slow part of the
    // Hip's turn (a ~3 s average) off every frame and rests her restYawDeg toward viewer's left; quick sways stay.
    property real restYawDeg: -3
    property real _hipYaw: 0
    property int _hip: -1         // index in _bones of the Hip rotation
    readonly property var uprightBones: ["CC_Base_Waist", "CC_Base_Spine01", "CC_Base_Spine02"]
    property var _spine: []       // indices in _bones of the uprightBones rotations, base first
    property var _proxies: []
    property var _rotIdx: null    // Map: bone node -> index in _bones of its rotation
    readonly property var keepBase: /^CC_Base_(NeckTwist0[12]|Head|FacialBone|JawRoot|.*Eye|Tongue.*|Teeth.*|UpperJaw)$/

    function setState(name) { if (_logic) _logic.setState(name); else _pending = name }
    function play(name) { if (_logic) _logic.play(name) }   // test hook: hold one clip
    property string _pending: ""

    function init() {
        var d = model.data, tl = {}, dur = {}, seen = {}, bones = [], keep = [], proxies = new Map(), held = []
        var proxyType = Qt.createComponent("MixerProxy.qml")   // no parent: nothing is added to this object
        for (var i = 0; i < d.length; i++) {
            var t = d[i]
            if (!t || !t.objectName || t.keyframeGroups === undefined) continue
            tl[t.objectName] = t
            dur[t.objectName] = (t.endFrame - t.startFrame) / 1000 / rate(t.objectName)
            t.animations[0].running = false
            for (var k = 0; k < t.keyframeGroups.length; k++) {
                var g = t.keyframeGroups[k], node = g.target, key = node.objectName + "." + g.property
                var proxy = proxies.get(node)
                if (!proxy) { proxy = proxyType.createObject(null); proxies.set(node, proxy); held.push(proxy) }
                // the group keeps the value its target holds when it is set as the one before the first keyframe,
                // so the proxy takes the bone's value first
                proxy[g.property] = copy(node[g.property])
                g.target = proxy
                if (seen[key]) continue
                seen[key] = true
                var b = { node: node, prop: g.property, rest: copy(node[g.property]), proxy: proxy }
                if (keepBase.test(node.objectName)) keep.push(b); else bones.push(b)
            }
        }
        _tl = tl; _bones = bones; _keep = keep; _proxies = held   // held here so the JS heap keeps every proxy
        var rot = new Map()
        for (i = 0; i < bones.length; i++) if (bones[i].prop === "rotation") rot.set(bones[i].node, i)
        _rotIdx = rot
        var spine = []
        for (var u = 0; u < uprightBones.length; u++)
            for (i = 0; i < bones.length; i++) if (bones[i].node.objectName === uprightBones[u] && bones[i].prop === "rotation") spine.push(i)
        _spine = spine
        for (i = 0; i < bones.length; i++) if (bones[i].node.objectName === "CC_Base_Hip" && bones[i].prop === "rotation") _hip = i
        // dropped constant tracks: the bone still has to be reset, and it is not in any group of most clips, but it
        // is in Talking's, so the union above already holds it. Every Timeline stays enabled and idle; a sample is
        // a currentFrame write.
        for (var n in tl) tl[n].enabled = true
        _logic = Logic.create(dur, seed)
        if (_pending) _logic.setState(_pending)
        _mode = _logic.state().mode
    }

    function rate(name) { return Logic.RATE[name] || 1 }

    function sample(name, t) {   // the clip's pose at t, from the proxies (her bones are not touched)
        for (var i = 0; i < _bones.length; i++) _bones[i].proxy[_bones[i].prop] = _bones[i].rest
        var tl = _tl[name], f = tl.startFrame + t * rate(name) * 1000
        if (tl.currentFrame === f) tl.currentFrame = f + 0.001   // a write only evaluates on change
        tl.currentFrame = f
        var out = new Array(_bones.length)
        for (i = 0; i < _bones.length; i++) out[i] = copy(_bones[i].proxy[_bones[i].prop])
        return out
    }

    // A node's scene rotation with this frame's pose (not yet written): its parent's times its local rotation,
    // from the nearest node whose scene rotation the pose does not move (read from Qt) on down.
    function sceneRot(node, pose) {
        if (!node) return Qt.quaternion(1, 0, 0, 0)
        if (!_movedByPose(node)) { var s = node.sceneRotation; return Qt.quaternion(s.scalar, s.x, s.y, s.z) }
        var i = _rotIdx.get(node)
        return sceneRot(node.parent, pose).times(i === undefined ? node.rotation : pose[i])
    }
    function _movedByPose(node) {
        for (var n = node; n; n = n.parent) if (_rotIdx.has(n)) return true
        return false
    }

    // Qt 6 hands value types to JS as live references that re-read the property, so a sample has to be copied out
    // before the next clip is sampled over the same proxies.
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

    function upright(pose) {   // each spine bone: local = parent^-1 * F Rx(-uprightDeg / n) F^-1 * parent * local, base first
        if (!_spine.length || !uprightDeg) return
        // Lean about her own side-to-side axis (F = her figure turn): Avatar.qml yaws the whole figure to face the
        // camera, and a lean about world x would then roll her sideways.
        var a = -uprightDeg / _spine.length * Math.PI / 360
        var f = model && model.sceneRotation ? model.sceneRotation : Qt.quaternion(1, 0, 0, 0), fq = Qt.quaternion(f.scalar, f.x, f.y, f.z)
        var rx = fq.times(Qt.quaternion(Math.cos(a), Math.sin(a), 0, 0)).times(fq.inverted())
        for (var i = 0; i < _spine.length; i++) {
            var k = _spine[i], pq = sceneRot(_bones[k].node.parent, pose)
            pose[k] = pq.inverted().times(rx).times(pq).times(pose[k])
        }
    }

    function settle(dt, pose) {   // hip local = parent^-1 * F Ry(restYawDeg - slow yaw) F^-1 * parent * hip
        if (_hip < 0) return
        var hip = _bones[_hip].node
        var f = model && model.sceneRotation ? model.sceneRotation : Qt.quaternion(1, 0, 0, 0), fq = Qt.quaternion(f.scalar, f.x, f.y, f.z)
        var hq = fq.inverted().times(sceneRot(hip, pose))
        var z = hq.times(Qt.quaternion(0, 0, 0, 1)).times(hq.conjugated())   // her forward, in her own frame
        var yaw = Math.atan2(z.x, z.z) * 180 / Math.PI
        _hipYaw += (yaw - _hipYaw) * Math.min(1, dt / 3)
        var a = (restYawDeg - _hipYaw) * Math.PI / 360, pq = sceneRot(hip.parent, pose)
        var ry = fq.times(Qt.quaternion(Math.cos(a), 0, Math.sin(a), 0)).times(fq.inverted())
        pose[_hip] = pq.inverted().times(ry).times(pq).times(pose[_hip])
    }

    function tick(dt) {
        if (!_logic) return
        var bl = _logic.step(dt)
        if (bl) {
            var pose = sample(bl.cur.name, bl.cur.t)
            if (bl.prev) {
                var prev = sample(bl.prev.name, bl.prev.t)
                for (var i = 0; i < _bones.length; i++) pose[i] = mixValue(prev[i], pose[i], bl.w)
            }
            _clip = bl.cur.name; _w = bl.w
            settle(dt, pose)
            upright(pose)
            for (i = 0; i < _bones.length; i++) _bones[i].node[_bones[i].prop] = pose[i]   // each bone once, final
        }
        _mode = _logic.state().mode
    }

    property FrameAnimation _frames: FrameAnimation {
        running: mix.running && mix.model !== null
        onTriggered: { if (!mix._logic) mix.init(); var dt = Math.min(frameTime, 0.1); mix.tick(dt); mix.ticked(dt) }
    }
}

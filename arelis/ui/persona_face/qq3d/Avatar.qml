// Her Quick 3D scene: the entry point the host (qq3d_avatar.py) loads.
//
// Contract for the scene tracks (A look, B face, C mixer). The host only
// writes the properties below and calls refit(); it reads sceneStatus and
// sceneError. Plug in by editing this file's marked slots, never the host:
//   avatarState  idle | listening | thinking | speaking | done
//   speaking     true while she talks (lip-sync on)
//   level        0..1 voice level for the mouth
//   tint         hue turn in degrees for the room (0 keeps her violet)
//   accent, bg, text   the room's theme colours
//   backdrop     clear colour under her (transparent unless the opaque arm)
//   modelSource  her converted model (balsam Ellah_anim.qml) in the user data folder
//   figure       the loaded model node (null until loaded), for B to drive
//   clip         the body clip the mixer is playing (read only)
import QtQuick
import QtQuick3D
import "../../persona_q3d"
import "../../persona_q3d/face.js" as Face

Item {
    id: root
    property string avatarState: "idle"
    property bool speaking: false
    property real level: 0
    property real tint: 0
    property color accent: "#8f7cff"
    property color bg: "#14101c"
    property color text: "#e6e0f5"
    property color backdrop: "transparent"
    property real figureX: 0.5   // where her centre stands across the view, 0..1 (Filament: right of centre)
    property url modelSource
    readonly property alias figure: loader.item
    // The camera slides sideways, so she keeps her full height and only moves across the view.
    // Her soles in world metres, about 1 cm under the lowest pixel (box, v14k camera: -0.09).
    readonly property real soleY: -0.10
    // Her width over her height in frame, arms and idle sway in, with margin (box: 0.22 measured).
    // Views narrower than this pull the camera back so she fits head to toe, scaled down.
    readonly property real figureAspect: 0.25
    readonly property real fitScale: view.height > 0 && view.width > 0
        ? Math.max(1, figureAspect * view.height / view.width) : 1
    readonly property real camShift: -(2 * figureX - 1) * Math.tan(15 * Math.PI / 180) * 3.95 * fitScale * view.width / Math.max(1, view.height)
    property string sceneStatus: "loading"   // loading | ready | error
    property string sceneError: ""
    readonly property string clip: mixer.clip
    // Body clips in the loaded model (balsam Timelines); 0 means the clips did not come through.
    readonly property int clipCount: {
        var d = loader.item ? loader.item.data : [], n = 0
        for (var i = 0; i < d.length; i++) if (d[i] && d[i].keyframeGroups !== undefined) n++
        return n
    }
    property var face: null   // Track B (persona_q3d/face.js), created once the model has loaded

    View3D {
        id: view
        objectName: "view"
        anchors.fill: parent
        // The look's own output path, as tools/avatar_lookmatch.py PORT_SCENE renders iter5: no MSAA,
        // linear tonemap (three's OutputPass), and AetherBloom with config.js LOOK.bloom.
        environment: SceneEnvironment {
            backgroundMode: root.backdrop.a > 0 ? SceneEnvironment.Color : SceneEnvironment.Transparent
            clearColor: root.backdrop
            antialiasingMode: SceneEnvironment.NoAA
            tonemapMode: SceneEnvironment.TonemapModeLinear
            effects: [AetherBloom { objectName: "bloom"; strength: 0.85; radius: 0.5; threshold: 0.55; keyAlpha: root.backdrop.a > 0 ? 0 : 1 }]
        }
        // v14k's camera (aether.js): 30 degrees vertical, at (0, 0.9, 3.95) looking at (0, 0.88, 0),
        // head to toe in her full-height band in every room. The scene is in metres, her model's own unit: the look's
        // shaders compare world positions with world-space uniforms (uNeckY, uFace, ...) in metres.
        // On top of it: lifted so the frame bottom meets her soles, and a view narrower than she is
        // backs the camera off by fitScale (lifted to match), so she stays whole, never cropped.
        PerspectiveCamera { id: cam; objectName: "cam"
            readonly property real tilt: 0.02   // v14k: the camera sits 2 cm above the point it looks at
            readonly property real camZ: 3.95 * root.fitScale
            readonly property real lookY: root.soleY + Math.tan(fieldOfView * Math.PI / 360) * camZ
            position: Qt.vector3d(root.camShift, lookY + tilt, camZ)
            eulerRotation.x: -Math.atan2(tilt, camZ) * 180 / Math.PI
            clipNear: 0.05; clipFar: 200; fieldOfView: 30; fieldOfViewOrientation: PerspectiveCamera.Vertical }
        // Track A slot: look (materials, rim, bloom, particles) replaces these lights.
        DirectionalLight { eulerRotation.x: -30; eulerRotation.y: 20; brightness: 1.2 }
        DirectionalLight { eulerRotation.x: -10; eulerRotation.y: 200; brightness: 0.5; color: root.accent }
        PointLight { position: Qt.vector3d(0, 1.5, 2.0); brightness: 0.6 }
        Loader3D {
            id: loader
            objectName: "figure"
            source: root.modelSource
            onStatusChanged: {
                if (status === Loader3D.Ready) { root.startFace(item); root.sceneStatus = "ready" }
                else if (status === Loader3D.Error) { root.sceneError = "model failed to load"; root.sceneStatus = "error" }
            }
        }
    }

    // Track C: body clips, pools and crossfades (persona_q3d/Mixer.qml).
    Mixer { id: mixer; objectName: "mixer"; model: loader.item }
    onAvatarStateChanged: { mixer.setState(avatarState); if (face) face.setState(avatarState) }
    Component.onCompleted: mixer.setState(avatarState)

    // Track B: the face owns the head and neck. Strip those clip tracks before the mixer first samples
    // (its init runs on the first frame), then drive the face after each mixer frame.
    readonly property var faceBones: ["CC_Base_Head", "CC_Base_NeckTwist01"]
    Node { id: strippedTrack; objectName: "" }   // stripped KeyframeGroups write here, off the skeleton
    function stripFaceTracks(model) {
        var d = model.data, n = 0
        for (var i = 0; i < d.length; i++) {
            var gs = d[i] && d[i].keyframeGroups
            if (!gs) continue
            for (var k = 0; k < gs.length; k++)
                if (gs[k].target && faceBones.indexOf(gs[k].target.objectName) >= 0) { gs[k].target = strippedTrack; n++ }
        }
        return n
    }
    function startFace(model) {
        stripFaceTracks(model)
        face = Face.create(model, {})
        face.setState(avatarState)
        face.setSpeaking(speaking ? level : 0)
    }
    onSpeakingChanged: if (face) face.setSpeaking(speaking ? level : 0)
    onLevelChanged: if (face) face.setSpeaking(speaking ? level : 0)
    Connections {
        target: mixer
        function onTicked(dt) {
            if (!root.face) return
            root.face.update(dt)
            var fig = loader.item
            if (fig && fig.speakingLevel !== undefined) fig.speakingLevel = root.face.level   // the look's uAnim/uFX
        }
    }

    // The look sizes its point sprites in framebuffer pixels (persona_q3d/port.py point_sprites).
    readonly property real dpr: view.Window.window ? view.Window.window.effectiveDevicePixelRatio : Screen.devicePixelRatio
    Binding {
        target: loader.item; property: "viewportSize"; when: loader.item && loader.item.viewportSize !== undefined
        value: Qt.vector2d(view.width * root.dpr, view.height * root.dpr)
    }
    Binding { target: loader.item; property: "camera"; when: loader.item && loader.item.camera !== undefined; value: cam }
    Binding { target: loader.item; property: "aetherState"; when: loader.item && loader.item.aetherState !== undefined; value: root.avatarState }
    Binding {
        target: loader.item; property: "devicePixelRatio"; when: loader.item && loader.item.devicePixelRatio !== undefined
        value: root.dpr
    }

    // The layout settled. Quick 3D follows its size by itself; kept for the host API.
    function refit() { view.update() }
}

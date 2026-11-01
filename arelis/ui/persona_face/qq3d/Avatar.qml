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
//   hub          true in Filament's bottom-left hub, false in a full-height band
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
    property bool hub: false
    property url modelSource
    readonly property alias figure: loader.item
    property string sceneStatus: "loading"   // loading | ready | error
    property string sceneError: ""
    readonly property string clip: mixer.clip
    property var face: null   // Track B (persona_q3d/face.js), created once the model has loaded

    View3D {
        id: view
        objectName: "view"
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: root.backdrop.a > 0 ? SceneEnvironment.Color : SceneEnvironment.Transparent
            clearColor: root.backdrop
            antialiasingMode: SceneEnvironment.MSAA
        }
        // Head to toe in a box about half as wide as tall (persona_stage.FIGURE_ASPECT).
        PerspectiveCamera { id: cam; objectName: "cam"; position: Qt.vector3d(0, 88, root.hub ? 330 : 345)
            clipNear: 1; clipFar: 5000; fieldOfView: 35 }
        // Track A slot: look (materials, rim, bloom, particles) replaces these lights.
        DirectionalLight { eulerRotation.x: -30; eulerRotation.y: 20; brightness: 1.2 }
        DirectionalLight { eulerRotation.x: -10; eulerRotation.y: 200; brightness: 0.5; color: root.accent }
        PointLight { position: Qt.vector3d(0, 150, 200); brightness: 0.6 }
        Loader3D {
            id: loader
            objectName: "figure"
            source: root.modelSource
            scale: Qt.vector3d(100, 100, 100)
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

    // The layout settled. Quick 3D follows its size by itself; kept for the host API.
    function refit() { view.update() }
}

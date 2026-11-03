// The window's bottom layer under ARELIS_SURFACE=quick (quick_surface.py): the void, the
// Filament orbit drawn on the GPU (QuickOrbit.qml: ring, strands, dust, hub threads), the
// Python worker's layer of what is not ported yet (beads, stems, tethers, the reality orbit:
// an image, added as the old paint added it, never read back), and the slot her avatar scene
// (Avatar.qml) is parented into at her panel's rect.
import QtQuick

Rectangle {
    id: surface
    property color voidColor: "transparent"
    property string orbitSource: ""
    // Where the worker's image sits (window px): it covers only the beads, stems and tethers.
    property rect orbitRect: Qt.rect(0, 0, width, height)
    // Night and Sodium: the room's atmosphere (the window's own paint would be punched out).
    property string backdropSource: ""
    // True from her scene's attach until she is posed (quick_surface.py): a calm breathing
    // light where she will stand, so a cold start (her model, the pipeline compile) reads as
    // her arriving, not as a frozen window.
    property bool loading: false
    // ARELIS_SURFACE=quickwindow only (quick_surface.WidgetMirror): the window's widgets,
    // drawn on top. The native QQuickView covers them, so they reach the screen through here.
    property string widgetsSource: ""
    color: voidColor

    Image {
        objectName: "backdrop"
        anchors.fill: parent
        source: surface.backdropSource
        visible: surface.backdropSource !== ""
        cache: false
        smooth: false
        fillMode: Image.Stretch
    }

    QuickOrbit {
        objectName: "orbitGpu"
        anchors.fill: parent
        st: orbitState
    }

    Image {
        id: overlayImage
        objectName: "orbit"
        x: surface.orbitRect.x; y: surface.orbitRect.y
        width: surface.orbitRect.width; height: surface.orbitRect.height
        source: surface.orbitSource
        visible: false
        cache: false
        smooth: false
        fillMode: Image.Stretch
    }

    ShaderEffect {
        objectName: "orbitOverlay"
        x: surface.orbitRect.x; y: surface.orbitRect.y
        width: surface.orbitRect.width; height: surface.orbitRect.height
        visible: surface.orbitSource !== "" && overlayImage.status === Image.Ready
        property variant source: overlayImage
        fragmentShader: "orbit/overlay.frag.qsb"
        // The rest of the block overlay.frag shares with the orbit layers (unused there).
        property real time: 0
        property real form: 0
        property real warm: 0
        property real pulseT: 0
        property real words: 0
        property real speakHead: 0
        property real ringScale: 1
        property real fullHalf: 0
        property real listenHalf: 0
        property real fadeMargin: 0
        property real strand: 0
        property real dustClock: 0
        property real speed: 0
        property real hasHub: 0
        property real pad0: 0
        property size view: Qt.size(width, height)
        property point hub: Qt.point(0, 0)
        property vector4d ring: Qt.vector4d(0, 0, 0, 0)
        property color ice: "black"
        property color gold: "black"
        property color coreColor: "black"
        // The rest of common.glsl's block: unbound, each warned "does not have a matching
        // property" at load.
        property vector4d tree: Qt.vector4d(0, 0, 0, 0)
        property point feet: Qt.point(0, 0)
        property real flow: 0
        property real treeOn: 0
        property point reality: Qt.point(-1, -1)
        property real packetFlow: 0
    }

    Item {
        id: slot
        objectName: "avatarSlot"
        visible: false
    }

    Item {
        id: loadingState
        objectName: "loadingState"
        x: slot.x; y: slot.y; width: slot.width; height: slot.height
        opacity: surface.loading ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 900; easing.type: Easing.InOutSine } }
        property real breath: 0
        SequentialAnimation on breath {
            running: loadingState.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0; to: 1; duration: 2400; easing.type: Easing.InOutSine }
            NumberAnimation { from: 1; to: 0; duration: 2400; easing.type: Easing.InOutSine }
        }
        Repeater {
            model: 3
            Rectangle {
                readonly property real r: 26 + index * 22 + loadingState.breath * (10 + index * 8)
                x: loadingState.width * 0.5 - r
                y: loadingState.height * 0.46 - r
                width: r * 2; height: r * 2; radius: r
                color: "transparent"
                border.width: 1.2
                border.color: Qt.rgba(0.66, 0.56, 1.0, (0.42 - index * 0.11) * (0.55 + 0.45 * loadingState.breath))
            }
        }
        Rectangle {
            readonly property real r: 7 + loadingState.breath * 3
            x: loadingState.width * 0.5 - r
            y: loadingState.height * 0.46 - r
            width: r * 2; height: r * 2; radius: r
            color: Qt.rgba(0.86, 0.80, 1.0, 0.55 + 0.4 * loadingState.breath)
        }
        Text {
            objectName: "loadingText"
            anchors.horizontalCenter: parent.horizontalCenter
            y: loadingState.height * 0.46 + 96
            text: "She is waking up"
            color: Qt.rgba(0.80, 0.74, 1.0, 0.45 + 0.35 * loadingState.breath)
            font.pixelSize: 15
            font.letterSpacing: 1.5
        }
    }

    Image {
        objectName: "widgets"
        anchors.fill: parent
        z: 1000
        source: surface.widgetsSource
        visible: surface.widgetsSource !== ""
        cache: false
        smooth: false
        fillMode: Image.Stretch
    }
}

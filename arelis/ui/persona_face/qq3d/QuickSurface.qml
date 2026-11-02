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
    // Night and Sodium: the room's atmosphere (the window's own paint would be punched out).
    property string backdropSource: ""
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
        anchors.fill: parent
        source: surface.orbitSource
        visible: false
        cache: false
        smooth: false
        fillMode: Image.Stretch
    }

    ShaderEffect {
        objectName: "orbitOverlay"
        anchors.fill: parent
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
    }

    Item {
        id: slot
        objectName: "avatarSlot"
        visible: false
    }
}

import QtQuick

// The Sentinels close x, drawn inside the Overseer scene. A widget button sat
// under the scene's native window, which covered it on screen.
Item {
    id: mote
    objectName: "SentinelCloseMote"
    signal activated()
    // 0 at the design mote (lower right), 1 at the top-right corner.
    property real flight: 1
    readonly property real homeX: Math.max(8, (parent ? parent.width : 0) - 46)
    x: 1210 + (homeX - 1210) * flight
    y: 1046 + (48 - 1046) * flight
    width: 28
    height: 28
    z: 6
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: "Close"
    Accessible.description: "Close (Esc)"
    Accessible.focusable: true
    Accessible.onPressAction: mote.activated()
    Keys.onReturnPressed: mote.activated()
    Keys.onEnterPressed: mote.activated()
    Keys.onSpacePressed: mote.activated()

    Rectangle {
        anchors.fill: parent
        radius: 14
        color: "#d9ccff"
        border.width: mote.activeFocus ? 3 : 2
        border.color: mote.activeFocus ? "#ffffff" : "#a78bfa"
        Text {
            anchors.centerIn: parent
            text: "x"
            color: "#1c1430"
            font.pixelSize: 15
        }
    }
    TapHandler { onTapped: mote.activated() }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}

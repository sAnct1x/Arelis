// The window's bottom layer under ARELIS_SURFACE=quick (quick_surface.py): the void, the
// Filament orbit frame (still painted in Python this slice, uploaded as an image, never read
// back), and the slot her avatar scene (Avatar.qml) is parented into at her panel's rect.
import QtQuick

Rectangle {
    id: surface
    property color voidColor: "transparent"
    property string orbitSource: ""
    color: voidColor

    Image {
        objectName: "orbit"
        anchors.fill: parent
        source: surface.orbitSource
        visible: surface.orbitSource !== ""
        cache: false
        smooth: false
        fillMode: Image.Stretch
    }

    Item {
        id: slot
        objectName: "avatarSlot"
        visible: false
    }
}

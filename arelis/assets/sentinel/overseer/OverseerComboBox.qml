import QtQuick
import QtQuick.Controls

ComboBox {
    id: control
    implicitWidth: 220
    implicitHeight: 28
    padding: 4
    leftPadding: 8
    rightPadding: 22

    Accessible.role: Accessible.ComboBox
    Accessible.name: displayText ? ("Mission mode " + displayText) : "Mission mode"
    Accessible.onPressAction: control.openPopup()

    function openPopup() {
        popup.open()
    }

    function closePopup() {
        popup.close()
    }

    background: Rectangle {
        implicitWidth: 220
        implicitHeight: 28
        color: "#1c1430"
        border.color: control.activeFocus || control.down ? "#8b6cf2" : "#6d4ad8"
        radius: 4
    }
    contentItem: Text {
        text: "Mode: " + control.displayText
        color: "#e0d4ff"
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        font.pixelSize: 12
    }
    indicator: Text {
        x: control.width - width - 8
        y: (control.height - implicitHeight) / 2
        text: "▾"
        color: "#9a86d0"
        font.pixelSize: 12
    }
    delegate: ItemDelegate {
        id: del
        width: control.width
        // Names the item for screen readers and UI Automation.
        text: modelData
        implicitHeight: 28
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            text: modelData
            color: "#e0d4ff"
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: 12
            leftPadding: 8
        }
        background: Rectangle {
            color: del.highlighted ? "#2a1a4a" : "#1c1430"
        }
    }
    popup: Popup {
        objectName: control.objectName ? (control.objectName + "Popup") : "OverseerComboPopup"
        y: control.height
        width: control.width
        padding: 1
        background: Rectangle {
            objectName: control.objectName ? (control.objectName + "PopupFill") : "OverseerComboPopupFill"
            color: "#1c1430"
            border.color: "#6d4ad8"
            radius: 4
        }
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
        }
    }
}

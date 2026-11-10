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

    // Choose an option the way a click on its popup row does.
    function pick(i) {
        if (i < 0 || i >= count)
            return
        currentIndex = i
        activated(i)
    }

    // The popup's rows live in the window overlay, not under the combo box,
    // so UI Automation saw no items here. Each option is also an invisible
    // ListItem child of the combo box: Invoke or Select on it picks it.
    Repeater {
        model: control.model
        delegate: Item {
            required property int index
            required property var modelData
            width: control.width
            height: control.height
            Accessible.role: Accessible.ListItem
            Accessible.name: String(modelData)
            Accessible.selectable: true
            Accessible.selected: control.currentIndex === index
            Accessible.onPressAction: control.pick(index)
            Accessible.onToggleAction: control.pick(index)
        }
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

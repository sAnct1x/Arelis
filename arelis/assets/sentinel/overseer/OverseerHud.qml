import QtQuick
import QtQuick.Controls

Item {
    id: hud
    objectName: "OverseerHud"
    anchors.fill: parent

    property var pills: ({})
    property var swarmRows: []
    property var inspector: ({})
    property var logs: []
    property bool inspectorOpen: true
    property string selectedUnitId: ""
    property bool unitFocused: false
    property bool retireArmed: false
    property string groupBy: "caste"
    property string swarmSearch: ""
    property string logFilter: "all"
    property string logQuery: ""
    property string missionMode: "multi"
    property string missionQuery: ""
    property string statusLine: "hive live · all local · sending out blocked"
    property string commandStatus: ""
    property bool logPaused: false
    property bool logRepeats: true

    signal searchEdited(string text)
    signal groupModeChosen(string mode)
    signal headerToggled(string key)
    signal unitChosen(string unitId)
    signal logFilterChosen(string name)
    signal logSearchEdited(string text)
    signal logRepeatsChosen(bool on)
    signal hudCommand(string name, var payload)

    // Palette panel fill #0e0920. The mockup composites this at alpha 0.80
    // over a flattened scene; live View3D punches through any non-opaque
    // fragment (544p list/inspector crops). Opaque designed RGB contains
    // the scene without clipping or hiding unit geometry in the well.
    readonly property color panelFill: "#0e0920"

    readonly property string warrantsTooltip: "Evidence receipts in memory (includes up to 120 from earlier runs)"

    function stripCount(key) {
        var value = pills ? pills[key] : undefined
        return (value === undefined || value === null || value === "unavailable") ? "?" : String(value)
    }

    // -1 while the hive has not reported security events.
    function threatCount() {
        var value = pills ? pills.threats : undefined
        return typeof value === "number" ? value : -1
    }

    function threatValue() {
        return threatCount() < 0 ? "?" : String(threatCount())
    }

    function threatWord() {
        var n = threatCount()
        if (n < 0)
            return "Not reported"
        if (n === 0)
            return "All clear"
        return n === 1 ? "threat" : "threats"
    }

    function defenderWords() {
        var engaged = pills && pills.engaged ? pills.engaged.warden : undefined
        var wardens = stripCount("warden") === "1" ? "Warden" : "Wardens"
        return wardens + " patrolling · " + (engaged === undefined ? "?" : engaged) + " engaged"
    }

    function showLogRow(seq) {
        for (var i = 0; i < logs.length; i++) {
            if (logs[i] && logs[i].seq === seq) {
                logList.positionViewAtIndex(i, ListView.Beginning)
                return
            }
        }
        logList.positionViewAtBeginning()
    }

    // One strip block. A chip (narrow windows) keeps the 56 px block but drops
    // the label and centres a one-line icon plus value; its tooltip carries
    // the full label and detail.
    component StripBlock: Rectangle {
        id: block
        property string label: ""
        property bool chip: false
        property string tip: ""
        default property alias content: body.data
        height: 56
        radius: 12
        color: "#140d2a"
        border.color: "#2f2358"
        border.width: 1
        Accessible.role: Accessible.StaticText
        Accessible.description: tip
        HoverHandler { id: blockHover; enabled: block.tip.length > 0 }
        ToolTip.text: tip
        ToolTip.visible: tip.length > 0 && blockHover.hovered
        ToolTip.delay: 400
        Text {
            x: 16
            y: 6
            visible: !block.chip
            text: block.label.toUpperCase()
            color: "#a99bd6"
            font.pixelSize: 12
            font.weight: Font.Medium
        }
        Item {
            id: body
            x: block.chip ? 10 : 16
            y: block.chip ? 14 : 22
            width: block.width - 2 * x
            height: 28
        }
    }

    // Chip value: one line, vertically centred in the chip body.
    component ChipRow: Row {
        property string value: ""
        property color valueColor: "#e0d4ff"
        property bool mono: false
        default property alias icon: iconBox.data
        spacing: 6
        height: 28
        Item { id: iconBox; width: 12; height: 12; anchors.verticalCenter: parent.verticalCenter }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: parent.value
            color: parent.valueColor
            font.pixelSize: parent.mono ? 14 : 18
            font.weight: parent.mono ? Font.Normal : Font.DemiBold
            font.family: parent.mono ? "monospace" : Qt.application.font.family
        }
    }

    readonly property var casteOrder: [
        ["warden", "Warden", "#a78bfa"],
        ["stalker", "Stalker", "#e879f9"],
        ["harvester", "Harvester", "#8fd3ff"],
        ["sanitizer", "Sanitizer", "#f2c56b"],
        ["tripwire", "Tripwire", "#7ee0c8"]
    ]

    function engagedCastes() {
        var engaged = pills && pills.engaged ? pills.engaged : ({})
        var out = []
        for (var i = 0; i < casteOrder.length; i++) {
            var n = engaged[casteOrder[i][0]]
            if (typeof n === "number" && n > 0)
                out.push(casteOrder[i][1] + " " + n)
        }
        return out
    }

    function threatsTip() {
        var castes = engagedCastes()
        return "Threats: " + threatValue() + " " + threatWord() + ". "
            + (castes.length ? "Engaged castes: " + castes.join(", ") : "No castes engaged")
    }

    function unitsTip() {
        var parts = []
        for (var i = 0; i < casteOrder.length; i++)
            parts.push(casteOrder[i][1] + " " + stripCount(casteOrder[i][0]))
        return "Units by caste: " + stripCount("units") + " total. " + parts.join(", ")
    }

    function lastEventTip(event) {
        return "Last event: " + (event ? event.time + " " + event.summary : "none yet")
            + ". Click to show it in the console."
    }

    function titleCase(word) {
        var s = String(word || "")
        return s.length ? s.charAt(0).toUpperCase() + s.slice(1) : s
    }

    function inspectorHeading() {
        if (!hud.inspector || !hud.inspector.unit_id)
            return "Inspector"
        return String(hud.inspector.unit_id)
    }

    function inspectorCasteLabel() {
        var caste = hud.inspector && hud.inspector.caste ? String(hud.inspector.caste) : ""
        return caste.length ? titleCase(caste) : ""
    }

    function inspectorRoleLine() {
        var caste = inspectorCasteLabel()
        var role = hud.inspector && hud.inspector.role ? String(hud.inspector.role) : ""
        if (caste && role)
            return caste + " \u00b7 " + role
        return caste || role
    }

    function inspectorCasteColor() {
        var caste = hud.inspector && hud.inspector.caste ? String(hud.inspector.caste) : ""
        if (caste === "warden") return "#a78bfa"
        if (caste === "stalker") return "#e879f9"
        if (caste === "harvester") return "#8fd3ff"
        if (caste === "sanitizer") return "#f2c56b"
        if (caste === "tripwire") return "#7ee0c8"
        return "#a99bd6"
    }

    function missingFieldsText() {
        var missing = hud.inspector && hud.inspector.missing ? hud.inspector.missing : []
        if (!missing || !missing.length)
            return ""
        var parts = []
        for (var i = 0; i < missing.length; i++)
            parts.push(String(missing[i]))
        if (parts.length === 1)
            return parts[0]
        if (parts.length === 2)
            return parts[0] + ", " + parts[1]
        return parts.slice(0, parts.length - 1).join(", ") + ", " + parts[parts.length - 1]
    }

    function clearRetireArm() {
        retireArmed = false
        retireArmTimer.stop()
    }

    onSelectedUnitIdChanged: clearRetireArm()

    Rectangle {
        id: topBar
        objectName: "OverseerPillBar"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 86
        color: hud.panelFill
        border.color: "#6d4ad8"
        border.width: 1

        Column {
            id: titleColumn
            objectName: "OverseerTitle"
            anchors.left: parent.left
            anchors.leftMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Text {
                text: "Sentinels"
                color: "#d8c8ff"
                font.pixelSize: 28
            }
            Row {
                spacing: 8
                Rectangle { width: 8; height: 8; radius: 4; color: "#7ee0a8"; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    text: hud.statusLine
                    color: "#a99bd6"
                    font.pixelSize: 13
                }
            }
        }

        // Status strip (Iris FIX-LIST rank 1): five read-only blocks from the
        // snapshot's numbers, updated with the snapshot only (no timers).
        // Narrow windows (Vela): Threats and Defenders stay full size, the other
        // three collapse to chips. Header height never changes; layout is
        // bindings on width only.
        Item {
            id: strip
            objectName: "OverseerStatusStrip"
            readonly property real gap: compact ? 12 : 16
            readonly property real fullNeed: 152 + 288 + 548 + 104 + 240 + 4 * 16
            readonly property real roomAt344: empButton.x - 16 - 344
            readonly property bool compact: roomAt344 < fullNeed
            readonly property real compactNeed: 152 + 288 + unitsBlock.width + warrantsBlock.width
                                                + lastEventBlock.width + 4 * gap
            // Start at the design's x 344; only a chip row that does not fit
            // there moves up to 24 px after the health line.
            anchors.left: parent.left
            anchors.leftMargin: (!compact || roomAt344 >= compactNeed) ? 344
                                : titleColumn.x + titleColumn.width + 24
            anchors.right: empButton.left
            anchors.rightMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            height: 56
            // A block that would not fit whole is left out, from the right.
            function fits(i) {
                var blocks = [threatsBlock, defendersBlock, unitsBlock, warrantsBlock, lastEventBlock]
                var w = 0
                for (var k = 0; k <= i; k++)
                    w += blocks[k].width + (k ? gap : 0)
                return w <= strip.width
            }

            Row {
                spacing: strip.gap
                StripBlock {
                    id: threatsBlock
                    objectName: "OverseerStrip_threats"
                    visible: strip.fits(0)
                    width: 152
                    label: "Threats"
                    tip: hud.threatsTip()
                    border.color: hud.threatCount() > 0 ? "#ff6b9a"
                                  : (hud.threatCount() === 0 ? "#2f6b55" : "#2f2358")
                    Accessible.name: "Threats: " + hud.threatValue() + " " + hud.threatWord()
                    Row {
                        spacing: 8
                        Text {
                            id: threatNum
                            text: hud.threatValue()
                            color: hud.threatCount() > 0 ? "#ff6b9a"
                                   : (hud.threatCount() === 0 ? "#7ee0a8" : "#8a7bbf")
                            font.pixelSize: 24
                            font.weight: Font.Bold
                        }
                        Text {
                            anchors.baseline: threatNum.baseline
                            text: hud.threatWord()
                            color: hud.threatCount() >= 0 ? "#e0d4ff" : "#8a7bbf"
                            font.pixelSize: 14
                            font.weight: Font.Medium
                        }
                    }
                    // "n castes" under the value only when it fits inside the
                    // 56 px block; otherwise the tooltip alone lists them.
                    Text {
                        id: threatCastes
                        objectName: "OverseerStrip_threatCastes"
                        readonly property int n: hud.engagedCastes().length
                        y: threatNum.height
                        visible: hud.threatCount() >= 1 && n > 0
                                 && 22 + y + implicitHeight <= threatsBlock.height - 4
                        text: n + (n === 1 ? " caste" : " castes")
                        color: "#a99bd6"
                        font.pixelSize: 11
                    }
                }
                StripBlock {
                    id: defendersBlock
                    objectName: "OverseerStrip_defenders"
                    visible: strip.fits(1)
                    width: 288
                    label: "Defenders"
                    Accessible.name: "Defenders: " + hud.stripCount("warden") + " " + hud.defenderWords()
                    Row {
                        spacing: 8
                        Text {
                            id: defNum
                            text: hud.stripCount("warden")
                            color: "#a78bfa"
                            font.pixelSize: 24
                            font.weight: Font.Bold
                        }
                        Text {
                            anchors.baseline: defNum.baseline
                            text: hud.defenderWords()
                            color: "#e0d4ff"
                            font.pixelSize: 14
                        }
                    }
                }
                StripBlock {
                    id: unitsBlock
                    objectName: "OverseerStrip_units"
                    visible: strip.fits(2)
                    chip: strip.compact
                    width: chip ? unitsChip.implicitWidth + 20 : 548
                    label: "Units by caste"
                    tip: chip ? hud.unitsTip() : ""
                    Accessible.name: "Units by caste: " + hud.stripCount("units") + " total"
                    Row {
                        visible: !unitsBlock.chip
                        spacing: 16
                        Text {
                            id: unitTotal
                            text: hud.stripCount("units")
                            color: "#e0d4ff"
                            font.pixelSize: 24
                            font.weight: Font.Bold
                        }
                        Repeater {
                            model: hud.casteOrder
                            Row {
                                required property var modelData
                                objectName: "OverseerStrip_caste_" + modelData[0]
                                readonly property string n: hud.stripCount(modelData[0])
                                readonly property bool present: n !== "0" && n !== "?"
                                y: unitTotal.baselineOffset - casteLab.baselineOffset
                                spacing: 6
                                Rectangle {
                                    width: 8; height: 8; radius: 4
                                    anchors.verticalCenter: casteLab.verticalCenter
                                    color: parent.present ? parent.modelData[2] : "#8a7bbf"
                                }
                                Text {
                                    id: casteLab
                                    text: parent.modelData[1] + " " + parent.n
                                    color: parent.present ? "#e0d4ff" : "#8a7bbf"
                                    font.pixelSize: 13
                                }
                            }
                        }
                    }
                    ChipRow {
                        id: unitsChip
                        visible: unitsBlock.chip
                        value: hud.stripCount("units")
                        // Icon: four caste dots.
                        Grid {
                            columns: 2
                            spacing: 2
                            Repeater {
                                model: ["#a78bfa", "#8fd3ff", "#f2c56b", "#7ee0c8"]
                                Rectangle { required property string modelData; width: 5; height: 5; radius: 2.5; color: modelData }
                            }
                        }
                    }
                }
                StripBlock {
                    id: warrantsBlock
                    objectName: "OverseerStrip_warrants"
                    visible: strip.fits(3)
                    chip: strip.compact
                    width: chip ? warrantsChip.implicitWidth + 20 : 104
                    label: "Warrants"
                    tip: chip ? "Warrants: " + hud.stripCount("warrants") + ". " + hud.warrantsTooltip
                              : hud.warrantsTooltip
                    Accessible.name: "Warrants: " + hud.stripCount("warrants")
                    Text {
                        visible: !warrantsBlock.chip
                        text: hud.stripCount("warrants")
                        color: "#e0d4ff"
                        font.pixelSize: 24
                        font.weight: Font.Bold
                    }
                    ChipRow {
                        id: warrantsChip
                        visible: warrantsBlock.chip
                        value: hud.stripCount("warrants")
                        // Icon: a receipt.
                        Rectangle {
                            x: 1; width: 10; height: 12; radius: 2
                            color: "transparent"; border.color: "#a99bd6"; border.width: 1
                            Rectangle { x: 3; y: 4; width: 4; height: 1; color: "#a99bd6" }
                            Rectangle { x: 3; y: 7; width: 4; height: 1; color: "#a99bd6" }
                        }
                    }
                }
                StripBlock {
                    id: lastEventBlock
                    objectName: "OverseerStrip_lastEvent"
                    visible: strip.fits(4)
                    chip: strip.compact
                    width: chip ? lastChip.implicitWidth + 20 : 240
                    label: "Last event"
                    readonly property var event: hud.pills ? hud.pills.lastEvent : null
                    tip: chip ? hud.lastEventTip(event) : ""
                    Accessible.role: Accessible.Button
                    Accessible.name: "Last event: " + (event ? event.time + " " + event.summary : "None yet")
                    Row {
                        visible: !lastEventBlock.chip
                        spacing: 8
                        width: parent.width
                        Text {
                            id: eventTime
                            visible: text.length > 0
                            text: lastEventBlock.event ? String(lastEventBlock.event.time || "") : ""
                            color: "#a99bd6"
                            font.pixelSize: 14
                            font.family: "monospace"
                        }
                        Text {
                            anchors.baseline: eventTime.baseline
                            width: parent.width - (eventTime.visible ? eventTime.width + 8 : 0)
                            elide: Text.ElideRight
                            text: lastEventBlock.event ? String(lastEventBlock.event.summary || "") : "None yet"
                            color: lastEventBlock.event ? "#e0d4ff" : "#8a7bbf"
                            font.pixelSize: 14
                        }
                    }
                    ChipRow {
                        id: lastChip
                        visible: lastEventBlock.chip
                        mono: !!lastEventBlock.event
                        value: lastEventBlock.event ? String(lastEventBlock.event.time || "").slice(0, 5) : "None"
                        valueColor: lastEventBlock.event ? "#e0d4ff" : "#8a7bbf"
                        // Icon: a clock.
                        Rectangle {
                            width: 12; height: 12; radius: 6
                            color: "transparent"; border.color: "#a99bd6"; border.width: 1
                            Rectangle { x: 5.5; y: 2.5; width: 1; height: 4; color: "#a99bd6" }
                            Rectangle { x: 5.5; y: 5.5; width: 3.5; height: 1; color: "#a99bd6" }
                        }
                    }
                    MouseArea {
                        x: lastEventBlock.chip ? -10 : -16
                        y: lastEventBlock.chip ? -14 : -22
                        width: lastEventBlock.width
                        height: lastEventBlock.height
                        cursorShape: Qt.PointingHandCursor
                        onClicked: hud.showLogRow(lastEventBlock.event ? lastEventBlock.event.seq : undefined)
                    }
                }
            }
        }

        Rectangle {
            id: empButton
            objectName: "OverseerEmergencyStop"
            anchors.right: parent.right
            anchors.rightMargin: 64
            anchors.verticalCenter: parent.verticalCenter
            width: empLabel.implicitWidth + 20
            height: 30
            radius: 15
            color: "#d68ab8"
            Text {
                id: empLabel
                anchors.centerIn: parent
                text: "Emergency stop"
                color: "#f0c4dc"
                font.pixelSize: 12
            }
            MouseArea {
                anchors.fill: parent
                onClicked: hud.hudCommand("emp_halt", { reason: "Overseer emergency stop" })
            }
        }
    }

    Rectangle {
        id: swarmPanel
        objectName: "OverseerSwarmPanel"
        anchors.left: parent.left
        anchors.top: topBar.bottom
        anchors.bottom: consolePanel.top
        width: Math.min(440, parent.width * 0.26)
        color: hud.panelFill
        border.color: "#6d4ad8"
        border.width: 1

        Column {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8

            Row {
                spacing: 8
                Text { text: "Swarm"; color: "#d8c8ff"; font.pixelSize: 16 }
                Text { text: hud.titleCase(hud.groupBy); color: "#a99bd6"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
            }

            TextField {
                id: searchField
                objectName: "OverseerSwarmSearch"
                width: parent.width
                height: 28
                placeholderText: "Search units"
                color: "#e0d4ff"
                placeholderTextColor: "#a090d4"
                background: Rectangle { color: "#160f2b"; border.color: "#6d4ad8"; radius: 4 }
                onTextChanged: {
                    hud.swarmSearch = text
                    hud.searchEdited(text)
                }
            }

            Row {
                spacing: 6
                Text { text: "Group"; color: "#9a86d0"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                Repeater {
                    model: ["caste", "task", "ring"]
                    Rectangle {
                        required property string modelData
                        objectName: "OverseerGroup_" + modelData
                        height: 24
                        width: groupLab.implicitWidth + 14
                        radius: 4
                        color: hud.groupBy === modelData ? "#2a1a4a" : "#1c1430"
                        border.color: hud.groupBy === modelData ? "#8b6cf2" : "#6d4ad8"
                        Text {
                            id: groupLab
                            anchors.centerIn: parent
                            text: hud.titleCase(parent.modelData)
                            color: "#e0d4ff"
                            font.pixelSize: 11
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                hud.groupBy = parent.modelData
                                hud.groupModeChosen(parent.modelData)
                            }
                        }
                    }
                }
            }

            Item {
                id: swarmListFrame
                width: parent.width
                height: parent.height - 128

            ListView {
                id: swarmList
                objectName: "OverseerSwarmList"
                anchors.fill: parent
                clip: true
                reuseItems: true
                cacheBuffer: 44 * 6
                model: hud.swarmRows
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.VerticalFlick
                Accessible.role: Accessible.List
                Accessible.name: "Swarm units"
                property var stickyRow: null
                property bool stickyVisible: false
                function updateSticky() {
                    var rows = hud.swarmRows || []
                    var y = contentY
                    var acc = 0
                    var current = null
                    var currentY = 0
                    for (var i = 0; i < rows.length; i++) {
                        if (rows[i] && rows[i].kind === "header") {
                            if (acc <= y + 0.5) {
                                current = rows[i]
                                currentY = acc
                            }
                        }
                        acc += 44
                    }
                    stickyRow = current
                    stickyVisible = !!(current && y > currentY + 1)
                }
                onContentYChanged: updateSticky()
                onModelChanged: updateSticky()
                Component.onCompleted: updateSticky()
                ScrollBar.vertical: ScrollBar {
                    objectName: "OverseerSwarmScrollBar"
                    policy: swarmList.contentHeight > swarmList.height ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
                    Accessible.name: "Swarm list scroll bar"
                    implicitWidth: 8
                    contentItem: Rectangle {
                        objectName: "OverseerSwarmScrollThumb"
                        implicitWidth: 8
                        implicitHeight: 32
                        radius: 4
                        color: "#8b6cf2"
                    }
                    background: Rectangle {
                        objectName: "OverseerSwarmScrollTrack"
                        implicitWidth: 8
                        radius: 4
                        color: "#1c1430"
                    }
                }
                delegate: Rectangle {
                    id: rowBox
                    required property var modelData
                    required property int index
                    width: swarmList.width
                    height: 44
                    readonly property string rowLabel: modelData.kind === "header"
                          ? (modelData.key + " " + modelData.count + " (" + modelData.active + " active)")
                          : (String(modelData.unit_id || "") + "  " + (modelData.role || "") + "  " + (modelData.state || ""))
                    objectName: modelData.kind === "header"
                                ? ("OverseerSwarmHeader_" + String(modelData.key || index))
                                : ("OverseerSwarmRow_" + String(modelData.unit_id || index))
                    Accessible.role: modelData.kind === "header" ? Accessible.Grouping : Accessible.ListItem
                    Accessible.name: rowBox.rowLabel
                    Accessible.description: modelData.kind === "header"
                                            ? "Toggle swarm group"
                                            : "Select this sentinel"
                    Accessible.selectable: modelData.kind === "unit"
                    Accessible.selected: modelData.kind === "unit" && modelData.unit_id === hud.selectedUnitId
                    Accessible.focusable: true
                    Accessible.onPressAction: rowBox.invokeRow()
                    color: {
                        if (modelData.kind === "header")
                            return "#1a1030"
                        if (modelData.unit_id === hud.selectedUnitId)
                            return "#2a1a4a"
                        return hud.panelFill
                    }
                    border.color: modelData.unit_id === hud.selectedUnitId ? "#8b6cf2" : "transparent"
                    border.width: modelData.unit_id === hud.selectedUnitId ? 1 : 0
                    function invokeRow() {
                        if (modelData.kind === "header")
                            hud.headerToggled(modelData.key)
                        else if (modelData.unit_id)
                            hud.unitChosen(modelData.unit_id)
                    }
                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        spacing: 8
                        Rectangle {
                            visible: modelData.kind === "unit"
                            width: 8
                            height: 8
                            radius: 4
                            color: modelData.color || "#e0d4ff"
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            width: parent.width - 24
                            elide: Text.ElideRight
                            color: "#e0d4ff"
                            font.pixelSize: 13
                            anchors.verticalCenter: parent.verticalCenter
                            text: rowBox.rowLabel
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: rowBox.invokeRow()
                    }
                }
            }
            Rectangle {
                id: stickyHeader
                objectName: "OverseerSwarmStickyHeader"
                visible: swarmList.stickyVisible
                width: parent.width
                height: 44
                z: 2
                color: "#1a1030"
                Accessible.role: Accessible.Grouping
                Accessible.name: stickyHeader.rowLabel
                readonly property string rowLabel: (swarmList.stickyRow && swarmList.stickyRow.key)
                      ? (swarmList.stickyRow.key + " " + swarmList.stickyRow.count + " (" + swarmList.stickyRow.active + " active)")
                      : ""
                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    elide: Text.ElideRight
                    color: "#e0d4ff"
                    font.pixelSize: 13
                    verticalAlignment: Text.AlignVCenter
                    text: stickyHeader.rowLabel
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        if (swarmList.stickyRow && swarmList.stickyRow.key)
                            hud.headerToggled(swarmList.stickyRow.key)
                    }
                }
            }
            }
            Row {
                objectName: "OverseerSwarmFooter"
                spacing: 8
                Rectangle {
                    objectName: "OverseerFooter_deploy"
                    height: 28
                    width: deployLab.implicitWidth + 16
                    radius: 4
                    color: "#1c1430"
                    border.color: "#8b6cf2"
                    Accessible.name: "Deploy"
                    Accessible.role: Accessible.Button
                    Accessible.onPressAction: hud.hudCommand("deploy", {
                        unit_id: hud.selectedUnitId,
                        caste: hud.inspector && hud.inspector.caste
                    })
                    Text {
                        id: deployLab
                        anchors.centerIn: parent
                        text: "Deploy"
                        color: "#e0d4ff"
                        font.pixelSize: 12
                    }
                    MouseArea {
                        id: deployArea
                        anchors.fill: parent
                        onClicked: hud.hudCommand("deploy", {
                            unit_id: hud.selectedUnitId,
                            caste: hud.inspector && hud.inspector.caste
                        })
                    }
                }
                Rectangle {
                    objectName: "OverseerFooter_recall"
                    height: 28
                    width: footerRecallLab.implicitWidth + 16
                    radius: 4
                    color: "#1c1430"
                    border.color: "#8b6cf2"
                    enabled: false
                    Accessible.name: "Recall (unavailable)"
                    Accessible.role: Accessible.Button
                    Text {
                        id: footerRecallLab
                        anchors.centerIn: parent
                        text: "Recall (unavailable)"
                        color: "#e0d4ff"
                        font.pixelSize: 12
                    }
                    MouseArea {
                        id: footerRecallArea
                        anchors.fill: parent
                        enabled: false
                    }
                }
            }
        }
    }

    Timer {
        id: retireArmTimer
        interval: 4000
        repeat: false
        onTriggered: hud.retireArmed = false
    }

    Rectangle {
        id: inspectorPanel
        objectName: "OverseerInspector"
        // Rank 3: dock outside the free well, only while a unit is selected.
        visible: hud.inspectorOpen && !!(hud.inspector && hud.inspector.unit_id)
        anchors.right: parent.right
        anchors.rightMargin: 24
        anchors.top: topBar.bottom
        anchors.topMargin: 18
        width: 360
        // Cap: Iris y 1050 (946 below the dock top) and above the 230 px console.
        height: Math.min(
            dockBody.implicitHeight + 32,
            Math.max(0, parent.height - topBar.height - 18 - 230 - 16),
            946
        )
        radius: 12
        color: hud.panelFill
        border.color: "#2f2358"
        border.width: 1
        clip: true
        Accessible.role: Accessible.Pane
        Accessible.name: hud.inspectorHeading()

        Flickable {
            id: dockFlick
            anchors.fill: parent
            anchors.margins: 16
            contentWidth: width
            contentHeight: dockBody.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.VerticalFlick

        Column {
            id: dockBody
            width: dockFlick.width
            spacing: 0

            Item {
                width: parent.width
                height: 28
                Rectangle {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: 10
                    height: 10
                    radius: 5
                    color: hud.inspectorCasteColor()
                }
                Text {
                    id: inspectorTitle
                    objectName: "OverseerInspectorTitle"
                    anchors.left: parent.left
                    anchors.leftMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 18 - 28
                    text: hud.inspectorHeading()
                    color: "#e0d4ff"
                    font.pixelSize: 18
                    font.weight: Font.Medium
                    font.family: "monospace"
                    elide: Text.ElideRight
                    Accessible.role: Accessible.StaticText
                    Accessible.name: text
                }
                Rectangle {
                    objectName: "OverseerInspectorDeselect"
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 24
                    height: 24
                    radius: 12
                    color: "transparent"
                    border.color: "#2f2358"
                    border.width: 1
                    Accessible.role: Accessible.Button
                    Accessible.name: "Deselect"
                    Text {
                        anchors.centerIn: parent
                        text: "\u00d7"
                        color: "#a99bd6"
                        font.pixelSize: 16
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: hud.unitChosen("")
                    }
                }
            }

            Text {
                objectName: "OverseerInspectorRole"
                width: parent.width
                topPadding: 8
                text: hud.inspectorRoleLine()
                color: "#a99bd6"
                font.pixelSize: 14
            }

            Item {
                width: parent.width
                height: (hud.inspector && hud.inspector.state_label) ? 30 : 8
                Rectangle {
                    objectName: "OverseerInspectorStateChip"
                    visible: !!(hud.inspector && hud.inspector.state_label)
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.topMargin: 8
                    height: 22
                    width: stateChipLab.implicitWidth + 20
                    radius: 11
                    color: "#1d1438"
                    Text {
                        id: stateChipLab
                        anchors.centerIn: parent
                        text: hud.inspector && hud.inspector.state_label ? String(hud.inspector.state_label) : ""
                        color: "#c4b5f0"
                        font.pixelSize: 12
                        font.weight: Font.Medium
                    }
                }
            }

            Rectangle {
                width: parent.width
                height: 1
                color: "#2f2358"
            }

            Text {
                width: parent.width
                topPadding: 16
                bottomPadding: 8
                text: "LIVE"
                color: "#a99bd6"
                font.pixelSize: 12
                font.weight: Font.Medium
            }

            Column {
                objectName: "OverseerInspectorLive"
                width: parent.width
                spacing: 0
                Repeater {
                    model: hud.inspector && hud.inspector.live ? hud.inspector.live : []
                    Item {
                        required property var modelData
                        objectName: "OverseerInspectorRow_" + modelData.key
                        width: parent.width
                        height: 28
                        Accessible.role: Accessible.StaticText
                        Accessible.name: modelData.label + ": " + modelData.value
                        Text {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            width: 112
                            text: modelData.label
                            color: "#a99bd6"
                            font.pixelSize: 14
                        }
                        Text {
                            objectName: "OverseerInspector_" + modelData.key
                            anchors.left: parent.left
                            anchors.leftMargin: 112
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            text: String(modelData.value)
                            color: "#e0d4ff"
                            font.pixelSize: 14
                            font.weight: Font.Medium
                            elide: Text.ElideRight
                        }
                    }
                }
            }

            Item {
                width: parent.width
                height: missingBox.visible ? 8 : 0
            }

            Rectangle {
                id: missingBox
                objectName: "OverseerInspectorMissing"
                visible: !!(hud.inspector && hud.inspector.missing && hud.inspector.missing.length)
                width: parent.width
                height: 72
                radius: 8
                color: "transparent"
                border.color: "#3b2d6e"
                border.width: 1
                // Dashed look: short ticks along the top edge.
                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.top: parent.top
                    spacing: 6
                    Repeater {
                        model: 28
                        Rectangle { width: 4; height: 1; color: "#0e0920" }
                    }
                }
                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 4
                    Text {
                        width: parent.width
                        text: "Not reported by the hive yet"
                        color: "#a99bd6"
                        font.pixelSize: 13
                        font.weight: Font.Medium
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        objectName: "OverseerInspectorMissingList"
                        width: parent.width
                        text: hud.missingFieldsText()
                        color: "#8a7bbf"
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Text {
                width: parent.width
                topPadding: 20
                bottomPadding: 8
                text: "CAPABILITIES"
                color: "#a99bd6"
                font.pixelSize: 12
                font.weight: Font.Medium
            }

            Flow {
                objectName: "OverseerInspectorCapabilities"
                width: parent.width
                spacing: 8
                Repeater {
                    model: hud.inspector && hud.inspector.capabilities ? hud.inspector.capabilities : []
                    Rectangle {
                        required property var modelData
                        height: 24
                        width: capLab.implicitWidth + 16
                        radius: 6
                        color: "#1d1438"
                        Text {
                            id: capLab
                            anchors.centerIn: parent
                            text: String(modelData)
                            color: "#c4b5f0"
                            font.pixelSize: 12
                            font.family: "monospace"
                        }
                    }
                }
                Text {
                    visible: !(hud.inspector && hud.inspector.capabilities && hud.inspector.capabilities.length)
                    text: "None listed"
                    color: "#8a7bbf"
                    font.pixelSize: 13
                }
            }

            Text {
                width: parent.width
                topPadding: 20
                bottomPadding: 8
                text: "ACTIONS"
                color: "#a99bd6"
                font.pixelSize: 12
                font.weight: Font.Medium
            }

            Grid {
                id: actionGrid
                objectName: "OverseerInspectorActions"
                width: parent.width
                columns: 2
                columnSpacing: 8
                rowSpacing: 8

                Rectangle {
                    objectName: "OverseerAction_focus"
                    height: 36
                    width: (actionGrid.width - 8) / 2
                    radius: 8
                    color: hud.unitFocused ? "#5b3fc4" : "#160f2b"
                    border.color: hud.unitFocused ? "#5b3fc4" : "#6d4ad8"
                    border.width: 1
                    enabled: !!(hud.inspector && hud.inspector.unit_id)
                    Accessible.role: Accessible.Button
                    Accessible.name: hud.unitFocused ? "Focused" : "Focus"
                    Accessible.onPressAction: hud.hudCommand("focus", {
                        unit_id: hud.selectedUnitId,
                        caste: hud.inspector && hud.inspector.caste
                    })
                    Text {
                        anchors.centerIn: parent
                        text: hud.unitFocused ? "Focused" : "Focus"
                        color: hud.unitFocused ? "#f4efff" : "#e0d4ff"
                        font.pixelSize: 14
                        font.weight: Font.Bold
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: parent.enabled
                        cursorShape: Qt.PointingHandCursor
                        onClicked: hud.hudCommand("focus", {
                            unit_id: hud.selectedUnitId,
                            caste: hud.inspector && hud.inspector.caste
                        })
                    }
                }

                Rectangle {
                    objectName: "OverseerAction_fitSwarm"
                    height: 36
                    width: (actionGrid.width - 8) / 2
                    radius: 8
                    color: "#160f2b"
                    border.color: "#6d4ad8"
                    border.width: 1
                    enabled: true
                    Accessible.role: Accessible.Button
                    Accessible.name: "Fit swarm"
                    Accessible.onPressAction: hud.hudCommand("fit_swarm", {})
                    Text {
                        anchors.centerIn: parent
                        text: "Fit swarm"
                        color: "#e0d4ff"
                        font.pixelSize: 14
                        font.weight: Font.Medium
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: parent.enabled
                        cursorShape: Qt.PointingHandCursor
                        onClicked: hud.hudCommand("fit_swarm", {})
                    }
                }

                Rectangle {
                    objectName: "OverseerAction_retask"
                    height: 36
                    width: (actionGrid.width - 8) / 2
                    radius: 8
                    color: "transparent"
                    border.color: "#2f2358"
                    border.width: 1
                    enabled: false
                    Accessible.role: Accessible.Button
                    Accessible.name: "Retask"
                    Accessible.description: "Not available: the hive cannot give one unit a new job."
                    HoverHandler { id: retaskHover }
                    ToolTip.visible: retaskHover.hovered
                    ToolTip.delay: 400
                    ToolTip.text: "Not available: the hive cannot give one unit a new job."
                    Row {
                        anchors.centerIn: parent
                        spacing: 6
                        Text {
                            text: "Retask"
                            color: "#8a7bbf"
                            font.pixelSize: 14
                            font.weight: Font.Medium
                        }
                        Text {
                            text: "\u24d8"
                            color: "#8a7bbf"
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    MouseArea { anchors.fill: parent; enabled: false }
                }

                Rectangle {
                    objectName: "OverseerAction_recall"
                    height: 36
                    width: (actionGrid.width - 8) / 2
                    radius: 8
                    color: "transparent"
                    border.color: "#2f2358"
                    border.width: 1
                    enabled: false
                    Accessible.role: Accessible.Button
                    Accessible.name: "Recall"
                    Accessible.description: "Not available: Recall would shrink the whole caste, not just this unit."
                    HoverHandler { id: recallHover }
                    ToolTip.visible: recallHover.hovered
                    ToolTip.delay: 400
                    ToolTip.text: "Not available: Recall would shrink the whole caste, not just this unit."
                    Row {
                        anchors.centerIn: parent
                        spacing: 6
                        Text {
                            text: "Recall"
                            color: "#8a7bbf"
                            font.pixelSize: 14
                            font.weight: Font.Medium
                        }
                        Text {
                            text: "\u24d8"
                            color: "#8a7bbf"
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    MouseArea { anchors.fill: parent; enabled: false }
                }

                Rectangle {
                    objectName: "OverseerAction_retire"
                    height: 36
                    width: (actionGrid.width - 8) / 2
                    radius: 8
                    color: "transparent"
                    border.color: "#ff6b9a"
                    border.width: 1
                    Accessible.role: Accessible.Button
                    Accessible.name: hud.retireArmed ? "Confirm retire" : "Retire"
                    Text {
                        anchors.centerIn: parent
                        text: hud.retireArmed ? "Confirm retire" : "Retire"
                        color: "#ff6b9a"
                        font.pixelSize: 14
                        font.weight: Font.Medium
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (!hud.retireArmed) {
                                hud.retireArmed = true
                                retireArmTimer.restart()
                                return
                            }
                            hud.clearRetireArm()
                            hud.hudCommand("retire", {
                                unit_id: hud.selectedUnitId,
                                caste: hud.inspector && hud.inspector.caste,
                                query: hud.missionQuery
                            })
                        }
                    }
                }
            }

            Text {
                width: parent.width
                topPadding: 20
                bottomPadding: 8
                text: "RECENT EVENTS"
                color: "#a99bd6"
                font.pixelSize: 12
                font.weight: Font.Medium
            }

            Column {
                objectName: "OverseerInspectorRecent"
                width: parent.width
                spacing: 4
                visible: !!(hud.inspector && hud.inspector.recent && hud.inspector.recent.length)
                Repeater {
                    model: hud.inspector && hud.inspector.recent ? hud.inspector.recent : []
                    Text {
                        required property var modelData
                        width: parent.width
                        text: (modelData.time ? modelData.time + "  " : "") + String(modelData.message || "")
                        color: "#a99bd6"
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Text {
                objectName: "OverseerInspectorRecentEmpty"
                width: parent.width
                visible: !(hud.inspector && hud.inspector.recent && hud.inspector.recent.length)
                text: "None from this unit this session."
                color: "#8a7bbf"
                font.pixelSize: 13
                bottomPadding: 0
            }
        }
        } // dockFlick
    }

    Rectangle {
        id: consolePanel
        objectName: "OverseerConsole"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 230
        color: hud.panelFill
        border.color: "#6d4ad8"
        border.width: 1

        Column {
            id: consoleControls
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            spacing: 6

            Row {
                spacing: 8
                OverseerComboBox {
                    id: modeBox
                    objectName: "OverseerMissionMode"
                    width: 220
                    height: 28
                    model: ["multi", "arxiv", "horizons", "wikipedia", "security_audit"]
                    onActivated: hud.missionMode = currentText
                }
                TextField {
                    id: queryField
                    objectName: "OverseerMissionQuery"
                    width: 420
                    height: 28
                    placeholderText: "Research query, planet, or topic"
                    color: "#e0d4ff"
                    placeholderTextColor: "#a090d4"
                    background: Rectangle { color: "#160f2b"; border.color: "#6d4ad8"; radius: 4 }
                    onTextChanged: hud.missionQuery = text
                }
                Rectangle {
                    objectName: "OverseerDispatch"
                    height: 28
                    width: 90
                    radius: 4
                    color: "#2a1a4a"
                    border.color: "#8b6cf2"
                    Text { anchors.centerIn: parent; text: "Dispatch"; color: "#e0d4ff" }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: hud.hudCommand("dispatch", { mode: hud.missionMode, query: hud.missionQuery })
                    }
                }
                Text {
                    objectName: "OverseerCommandStatus"
                    text: hud.commandStatus
                    color: "#9a86d0"
                    font.pixelSize: 12
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            Row {
                spacing: 6
                Repeater {
                    model: [
                        ["all", "All"],
                        ["threat", "Threats"],
                        ["sanitize", "Quarantine"],
                        ["harvest", "Gather"],
                        ["tripwire", "Tripwire"]
                    ]
                    Rectangle {
                        required property var modelData
                        objectName: "OverseerLogFilter_" + modelData[0]
                        height: 24
                        width: filtLab.implicitWidth + 14
                        radius: 4
                        color: hud.logFilter === modelData[0] ? "#2a1a4a" : "#1c1430"
                        border.color: hud.logFilter === modelData[0] ? "#8b6cf2" : "#6d4ad8"
                        Text {
                            id: filtLab
                            anchors.centerIn: parent
                            text: parent.modelData[1]
                            color: "#e0d4ff"
                            font.pixelSize: 11
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                hud.logFilter = parent.modelData[0]
                                hud.logFilterChosen(parent.modelData[0])
                            }
                        }
                    }
                }
                TextField {
                    objectName: "OverseerLogSearch"
                    width: 180
                    height: 24
                    placeholderText: "Filter by unit or keyword"
                    color: "#e0d4ff"
                    placeholderTextColor: "#a090d4"
                    background: Rectangle { color: "#160f2b"; border.color: "#6d4ad8"; radius: 4 }
                    onTextChanged: {
                        hud.logQuery = text
                        hud.logSearchEdited(text)
                    }
                }
                Rectangle {
                    objectName: "OverseerLogRepeats"
                    height: 24
                    width: repeatsLab.implicitWidth + 14
                    radius: 4
                    color: hud.logRepeats ? "#2a1a4a" : "#1c1430"
                    border.color: hud.logRepeats ? "#8b6cf2" : "#6d4ad8"
                    Accessible.role: Accessible.CheckBox
                    Accessible.name: "Collapse repeats"
                    Accessible.checked: hud.logRepeats
                    Text {
                        id: repeatsLab
                        anchors.centerIn: parent
                        text: "Repeats \u00d7N"
                        color: "#e0d4ff"
                        font.pixelSize: 11
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            hud.logRepeats = !hud.logRepeats
                            hud.logRepeatsChosen(hud.logRepeats)
                        }
                    }
                }
            }
        }

        // Full text of the hovered row (Iris rank 2): one shared tooltip.
        ToolTip {
            id: logTip
            objectName: "OverseerLogTip"
            delay: 400
            padding: 8
            contentItem: Text {
                text: logTip.text
                color: "#e0d4ff"
                font.pixelSize: 13
                wrapMode: Text.Wrap
                width: Math.min(720, implicitWidth)
            }
            background: Rectangle { color: "#140d2a"; border.color: "#8b6cf2"; radius: 4 }
        }

        // Root cause of the cut-off bottom line: wrapped rows of varying
        // height in a viewport of arbitrary height with no bottom padding.
        // Rows are now single-line, 24 px, and the viewport is always a whole
        // number of rows, 16 px above the panel's bottom edge.

        ListView {
            id: logList
            objectName: "OverseerLogList"
            readonly property int rowHeight: 24
            readonly property int rows: Math.max(1, Math.floor(
                (consolePanel.height - consoleControls.y - consoleControls.height - 12 - 16) / rowHeight))
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 16
            height: rows * rowHeight
            clip: true
            reuseItems: true
            snapMode: ListView.SnapToItem
            cacheBuffer: rowHeight * 6
            model: hud.logs
            delegate: Item {
                id: logRow
                required property var modelData
                readonly property int count: Number(modelData.count || 1)
                width: logList.width
                height: logList.rowHeight
                HoverHandler {
                    onHoveredChanged: {
                        if (hovered) {
                            logTip.parent = logRow
                            logTip.text = String(logRow.modelData.raw || logRow.modelData.message || "")
                            logTip.open()
                        } else if (logTip.parent === logRow) {
                            logTip.close()
                        }
                    }
                }
                Text {
                    x: 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: String(logRow.modelData.time || "")
                    color: "#a99bd6"
                    font.pixelSize: 13
                    font.family: "monospace"
                }
                Rectangle {
                    objectName: "OverseerLogCount"
                    x: 112
                    anchors.verticalCenter: parent.verticalCenter
                    visible: logRow.count > 1
                    height: 20
                    radius: 10
                    width: countLab.implicitWidth + 12
                    color: "#1d1438"
                    Text {
                        id: countLab
                        anchors.centerIn: parent
                        text: "\u00d7" + logRow.count
                        color: "#c4b5f0"
                        font.pixelSize: 12
                        font.weight: Font.Medium
                        font.family: "monospace"
                    }
                }
                Text {
                    x: 176
                    width: 104
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                    text: String(logRow.modelData.unit_id || "")
                    color: {
                        var caste = String(logRow.modelData.caste || "")
                        if (caste === "warden") return "#a78bfa"
                        if (caste === "stalker") return "#e879f9"
                        if (caste === "harvester") return "#8fd3ff"
                        if (caste === "sanitizer") return "#f2c56b"
                        if (caste === "tripwire") return "#7ee0c8"
                        return "#a99bd6"
                    }
                    font.pixelSize: 13
                    font.weight: Font.Medium
                    font.family: "monospace"
                }
                Rectangle {
                    x: 280
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !!logRow.modelData.failed
                    width: 6; height: 6; radius: 3
                    color: "#ff6b9a"
                }
                Text {
                    objectName: "OverseerLogMessage"
                    x: 288
                    width: Math.max(0, rangeText.x - 16 - x)
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                    text: String(logRow.modelData.message || "")
                    color: "#e0d4ff"
                    font.pixelSize: 14
                }
                Text {
                    id: rangeText
                    x: parent.width - 16 - implicitWidth
                    anchors.verticalCenter: parent.verticalCenter
                    text: String(logRow.modelData.range || "")
                    color: "#8a7bbf"
                    font.pixelSize: 12
                    font.family: "monospace"
                }
            }
        }
    }
}

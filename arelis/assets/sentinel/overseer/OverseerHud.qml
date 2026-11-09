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
    property string groupBy: "caste"
    property string swarmSearch: ""
    property string logFilter: "all"
    property string logQuery: ""
    property string missionMode: "multi"
    property string missionQuery: ""
    property string statusLine: "hive live · all local · sending out blocked"
    property string commandStatus: ""
    property bool logPaused: false

    signal searchEdited(string text)
    signal groupModeChosen(string mode)
    signal headerToggled(string key)
    signal unitChosen(string unitId)
    signal logFilterChosen(string name)
    signal logSearchEdited(string text)
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

    component StripBlock: Rectangle {
        property string label: ""
        default property alias content: body.data
        height: 56
        radius: 12
        color: "#140d2a"
        border.color: "#2f2358"
        border.width: 1
        Accessible.role: Accessible.StaticText
        Text {
            x: 16
            y: 6
            text: parent.label.toUpperCase()
            color: "#a99bd6"
            font.pixelSize: 12
            font.weight: Font.Medium
        }
        Item {
            id: body
            x: 16
            y: 22
            width: parent.width - 32
            height: 28
        }
    }

    function titleCase(word) {
        var s = String(word || "")
        return s.length ? s.charAt(0).toUpperCase() + s.slice(1) : s
    }

    function inspectorHeading() {
        if (!hud.inspector || !hud.inspector.unit_id)
            return "Inspector"
        var caste = hud.inspector.caste ? String(hud.inspector.caste) : ""
        if (caste.length)
            caste = caste.charAt(0).toUpperCase() + caste.slice(1)
        return String(hud.inspector.unit_id) + "  " + caste
    }

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
        Item {
            id: strip
            objectName: "OverseerStatusStrip"
            anchors.left: parent.left
            anchors.leftMargin: 344
            anchors.right: empButton.left
            anchors.rightMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            height: 56
            readonly property var widths: [152, 288, 548, 104, 240]
            // A block that would not fit whole is left out, from the right.
            function fits(i) {
                var w = 0
                for (var k = 0; k <= i; k++)
                    w += widths[k] + (k ? 16 : 0)
                return w <= strip.width
            }

            Row {
                spacing: 16
                StripBlock {
                    objectName: "OverseerStrip_threats"
                    visible: strip.fits(0)
                    width: strip.widths[0]
                    label: "Threats"
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
                            font.weight: Font.DemiBold
                        }
                        Text {
                            anchors.baseline: threatNum.baseline
                            text: hud.threatWord()
                            color: hud.threatCount() >= 0 ? "#e0d4ff" : "#8a7bbf"
                            font.pixelSize: 14
                            font.weight: Font.Medium
                        }
                    }
                }
                StripBlock {
                    objectName: "OverseerStrip_defenders"
                    visible: strip.fits(1)
                    width: strip.widths[1]
                    label: "Defenders"
                    Accessible.name: "Defenders: " + hud.stripCount("warden") + " " + hud.defenderWords()
                    Row {
                        spacing: 8
                        Text {
                            id: defNum
                            text: hud.stripCount("warden")
                            color: "#a78bfa"
                            font.pixelSize: 24
                            font.weight: Font.DemiBold
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
                    objectName: "OverseerStrip_units"
                    visible: strip.fits(2)
                    width: strip.widths[2]
                    label: "Units by caste"
                    Accessible.name: "Units by caste: " + hud.stripCount("units") + " total"
                    Row {
                        spacing: 16
                        Text {
                            id: unitTotal
                            text: hud.stripCount("units")
                            color: "#e0d4ff"
                            font.pixelSize: 24
                            font.weight: Font.DemiBold
                        }
                        Repeater {
                            model: [
                                ["warden", "Warden", "#a78bfa"],
                                ["stalker", "Stalker", "#e879f9"],
                                ["harvester", "Harvester", "#8fd3ff"],
                                ["sanitizer", "Sanitizer", "#f2c56b"],
                                ["tripwire", "Tripwire", "#7ee0c8"]
                            ]
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
                }
                StripBlock {
                    objectName: "OverseerStrip_warrants"
                    visible: strip.fits(3)
                    width: strip.widths[3]
                    label: "Warrants"
                    Accessible.name: "Warrants: " + hud.stripCount("warrants")
                    Accessible.description: hud.warrantsTooltip
                    HoverHandler { id: warrantsHover }
                    ToolTip.text: hud.warrantsTooltip
                    ToolTip.visible: warrantsHover.hovered
                    ToolTip.delay: 400
                    Text {
                        text: hud.stripCount("warrants")
                        color: "#e0d4ff"
                        font.pixelSize: 24
                        font.weight: Font.DemiBold
                    }
                }
                StripBlock {
                    id: lastEventBlock
                    objectName: "OverseerStrip_lastEvent"
                    visible: strip.fits(4)
                    width: strip.widths[4]
                    label: "Last event"
                    readonly property var event: hud.pills ? hud.pills.lastEvent : null
                    Accessible.role: Accessible.Button
                    Accessible.name: "Last event: " + (event ? event.time + " " + event.summary : "None yet")
                    Row {
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
                    MouseArea {
                        x: -16
                        y: -22
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

    Rectangle {
        id: inspectorPanel
        objectName: "OverseerInspector"
        visible: hud.inspectorOpen
        anchors.right: parent.right
        anchors.top: topBar.bottom
        width: Math.min(460, parent.width * 0.28)
        height: Math.min(536, Math.max(0, parent.height - topBar.height - consolePanel.height))
        color: hud.panelFill
        border.color: "#6d4ad8"
        border.width: 1
        Accessible.role: Accessible.Pane
        Accessible.name: hud.inspectorHeading()

        Column {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8
            Text {
                objectName: "OverseerInspectorTitle"
                text: hud.inspectorHeading()
                color: "#d8c8ff"
                font.pixelSize: 16
                Accessible.role: Accessible.StaticText
                Accessible.name: text
            }
            Text {
                objectName: "OverseerInspectorEmpty"
                visible: !hud.inspector || !hud.inspector.unit_id
                text: "Select a unit to see its live state."
                color: "#6f5fa0"
                font.pixelSize: 12
                width: parent.width
                wrapMode: Text.WordWrap
            }
            Column {
                visible: !!(hud.inspector && hud.inspector.unit_id)
                spacing: 6
                width: parent.width
                Repeater {
                    model: [
                        ["state", "State"],
                        ["target", "Target"],
                        ["last_action", "Last action"],
                        ["time_on_task", "Time on task"],
                        ["eyes", "Eyes"],
                        ["tentacles", "Tentacles"],
                        ["capabilities", "Capabilities"],
                        ["warrant_hash", "Warrant hash"],
                        ["sparkline", "2 min sparkline"]
                    ]
                    Row {
                        required property var modelData
                        objectName: "OverseerInspectorRow_" + modelData[0]
                        width: parent.width
                        spacing: 8
                        readonly property string fieldValue: (hud.inspector && hud.inspector[modelData[0]] !== undefined)
                              ? String(hud.inspector[modelData[0]])
                              : "unavailable"
                        Accessible.role: Accessible.StaticText
                        Accessible.name: modelData[1] + ": " + fieldValue
                        Text {
                            width: 110
                            text: modelData[1]
                            color: "#9a86d0"
                            font.pixelSize: 12
                        }
                        Text {
                            objectName: "OverseerInspector_" + modelData[0]
                            width: parent.width - 118
                            wrapMode: Text.Wrap
                            text: parent.fieldValue
                            color: "#e0d4ff"
                            font.pixelSize: 12
                            Accessible.role: Accessible.StaticText
                            Accessible.name: parent.Accessible.name
                        }
                    }
                }
                Flow {
                    width: parent.width
                    spacing: 8

                    Rectangle {
                        objectName: "OverseerAction_focus"
                        height: 28
                        width: focusLab.implicitWidth + 16
                        radius: 4
                        color: "#1c1430"
                        border.color: "#8b6cf2"
                        enabled: !!(hud.inspector && hud.inspector.unit_id)
                        Accessible.role: Accessible.Button
                        Accessible.name: "Focus"
                        Accessible.onPressAction: hud.hudCommand("focus", {
                            unit_id: hud.selectedUnitId,
                            caste: hud.inspector && hud.inspector.caste
                        })
                        Text {
                            id: focusLab
                            anchors.centerIn: parent
                            text: "Focus"
                            color: "#e0d4ff"
                            font.pixelSize: 12
                        }
                        MouseArea {
                            anchors.fill: parent
                            enabled: parent.enabled
                            onClicked: hud.hudCommand("focus", {
                                unit_id: hud.selectedUnitId,
                                caste: hud.inspector && hud.inspector.caste
                            })
                        }
                    }
                    Rectangle {
                        objectName: "OverseerAction_fitSwarm"
                        height: 28
                        width: fitLab.implicitWidth + 16
                        radius: 4
                        color: "#1c1430"
                        border.color: "#8b6cf2"
                        enabled: true
                        Accessible.role: Accessible.Button
                        Accessible.name: "Fit swarm"
                        Accessible.onPressAction: hud.hudCommand("fit_swarm", {})
                        Text {
                            id: fitLab
                            anchors.centerIn: parent
                            text: "Fit swarm"
                            color: "#e0d4ff"
                            font.pixelSize: 12
                        }
                        MouseArea {
                            anchors.fill: parent
                            enabled: parent.enabled
                            onClicked: hud.hudCommand("fit_swarm", {})
                        }
                    }
                    Rectangle {
                        objectName: "OverseerAction_retask"
                        height: 28
                        width: retaskLab.implicitWidth + 16
                        radius: 4
                        color: "#1c1430"
                        border.color: "#8b6cf2"
                        enabled: false
                        Accessible.role: Accessible.Button
                        Accessible.name: "Retask (unavailable)"
                            Text {
                            id: retaskLab
                            anchors.centerIn: parent
                            text: "Retask (unavailable)"
                            color: "#e0d4ff"
                            font.pixelSize: 12
                        }
                        MouseArea {
                            anchors.fill: parent
                            enabled: false
                        }
                    }
                    Rectangle {
                        objectName: "OverseerAction_recall"
                        height: 28
                        width: recallLab.implicitWidth + 16
                        radius: 4
                        color: "#1c1430"
                        border.color: "#8b6cf2"
                        enabled: false
                        Accessible.role: Accessible.Button
                        Accessible.name: "Recall (unavailable)"
                            Text {
                            id: recallLab
                            anchors.centerIn: parent
                            text: "Recall (unavailable)"
                            color: "#e0d4ff"
                            font.pixelSize: 12
                        }
                        MouseArea {
                            anchors.fill: parent
                            enabled: false
                        }
                    }
                    Rectangle {
                        objectName: "OverseerAction_retire"
                        height: 28
                        width: retireLab.implicitWidth + 16
                        radius: 4
                        color: "#1c1430"
                        border.color: "#8b6cf2"
                        Accessible.role: Accessible.Button
                        Accessible.name: "Retire"
                        Text {
                            id: retireLab
                            anchors.centerIn: parent
                            text: "Retire"
                            color: "#e0d4ff"
                            font.pixelSize: 12
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: hud.hudCommand("retire", {
                                unit_id: hud.selectedUnitId,
                                caste: hud.inspector && hud.inspector.caste,
                                query: hud.missionQuery
                            })
                        }
                    }
                }
            }
        }
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
            anchors.fill: parent
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
            }

            ListView {
                id: logList
                objectName: "OverseerLogList"
                width: parent.width
                height: parent.height - 72
                clip: true
                reuseItems: true
                cacheBuffer: 24 * 6
                model: hud.logs
                delegate: Text {
                    required property var modelData
                    width: logList.width
                    wrapMode: Text.Wrap
                    font.pixelSize: 12
                    font.family: "monospace"
                    color: {
                        var caste = String(modelData.caste || "")
                        if (caste === "warden") return "#a78bfa"
                        if (caste === "stalker") return "#e879f9"
                        if (caste === "harvester") return "#8fd3ff"
                        if (caste === "sanitizer") return "#f2c56b"
                        if (caste === "tripwire") return "#7ee0c8"
                        return "#e0d4ff"
                    }
                    text: "[" + (modelData.unit_id || "") + "] " + (modelData.message || "")
                }
            }
        }
    }
}

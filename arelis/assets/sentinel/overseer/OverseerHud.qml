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
    // Full-window layout (Christopher, Nov 9 10:28 PM): the scene runs edge to
    // edge under every control. The unit list and the event list are overlay
    // drawers, closed by default, so opening one never resizes the scene.
    property bool drawerOpen: false
    property bool eventsOpen: false
    // Overlays keep a 2 percent margin from the window edge at any size.
    readonly property real marginX: Math.round(width * 0.02)
    readonly property real marginY: Math.round(height * 0.02)

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
    // Overlay plate (GAP.md chat-off layout): #140b20 at about 85 percent.
    readonly property color plateFill: Qt.rgba(0x14 / 255, 0x0b / 255, 0x20 / 255, 0.85)
    readonly property color plateEdge: Qt.rgba(0xa4 / 255, 0x73 / 255, 0xf0 / 255, 0.4)

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

    // One summary piece: borderless text, a dot separator before all but the first.
    component Piece: Text {
        property int index: 0
        property string body: ""
        color: "#cdb2f7"
        font.family: "Zen Kaku Gothic New"
        font.pixelSize: 14
        text: (index === 0 ? "" : "·  ") + body
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

    // Header (GAP item 10): overlay text, no plates. "Sentinels" and one
    // summary line that carries every number the old status strip showed.
    // Pieces drop from the right when the line would run into Emergency stop;
    // the tooltip and Accessible description always carry the full line.
    readonly property string titleFamily: "Zen Kaku Gothic New"
    readonly property string monoFamily: "Space Mono"
    // Tokens per second from the local model; 0 while nothing streams.
    property int tokRate: 0
    property bool coreMode: false
    // Replay strip: [seq, t, kind] per event, t in epoch seconds.
    property var replayTicks: []

    function casteCountsText() {
        var parts = []
        for (var i = 0; i < casteOrder.length; i++) {
            var n = stripCount(casteOrder[i][0])
            if (n !== "0")
                parts.push(casteOrder[i][1] + " " + n)
        }
        return parts.join(", ")
    }

    function fetchingCount() {
        var engaged = pills && pills.engaged ? pills.engaged.harvester : undefined
        return engaged === undefined ? "?" : String(engaged)
    }

    function threatPiece() {
        var n = threatCount()
        if (n < 0)
            return "threats not reported"
        if (n === 0)
            return "0 threats"
        return n + (n === 1 ? " threat" : " threats")
    }

    function lastEventText(event) {
        return event ? "last " + String(event.time || "").slice(0, 8) + " " + String(event.summary || "")
                     : "no events yet"
    }

    function summaryText() {
        return stripCount("units") + " units (" + casteCountsText() + ") · "
            + fetchingCount() + " fetching · " + threatPiece() + " · "
            + defenderWords() + " · " + stripCount("warrants") + " warrants · "
            + lastEventText(pills ? pills.lastEvent : null) + " · " + statusLine
    }

    Item {
        id: topBar
        objectName: "OverseerPillBar"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: hud.marginX
        anchors.rightMargin: hud.marginX
        anchors.topMargin: hud.marginY
        height: 72

        Column {
            id: titleColumn
            objectName: "OverseerTitle"
            anchors.left: parent.left
            anchors.top: parent.top
            spacing: 2
            Text {
                text: "Sentinels"
                color: "#e8dcfb"
                font.family: hud.titleFamily
                font.pixelSize: 28
                font.weight: Font.Medium
            }
            // Summary line: borderless text pieces in #cdb2f7.
            Row {
                id: summary
                objectName: "OverseerSummary"
                readonly property real room: coreButton.x - 24
                readonly property var pieces: [unitsPiece, fetchPiece, threatsPiece, defendersPiece,
                                               warrantsPiece, lastEventPiece, healthPiece]
                function fits(i) {
                    var w = 0
                    for (var k = 0; k <= i; k++)
                        w += pieces[k].implicitWidth + (k ? spacing : 0)
                    return w <= room
                }
                spacing: 6
                Accessible.role: Accessible.StaticText
                Accessible.name: "Summary"
                Accessible.description: hud.summaryText()
                HoverHandler { id: summaryHover }
                ToolTip.text: hud.summaryText()
                ToolTip.visible: summaryHover.hovered && !warrantsHover.hovered && !lastEventHover.hovered
                ToolTip.delay: 400

                Piece {
                    id: unitsPiece
                    objectName: "OverseerStrip_units"
                    index: 0
                    visible: summary.fits(0)
                    body: hud.stripCount("units") + " units"
                    Accessible.role: Accessible.StaticText
                    Accessible.name: "Units by caste: " + hud.stripCount("units") + " total. " + hud.casteCountsText()
                }
                Piece {
                    id: fetchPiece
                    objectName: "OverseerStrip_fetching"
                    index: 1
                    visible: summary.fits(1)
                    body: hud.fetchingCount() + " fetching"
                }
                Piece {
                    id: threatsPiece
                    objectName: "OverseerStrip_threats"
                    index: 2
                    visible: summary.fits(2)
                    body: hud.threatPiece()
                    color: hud.threatCount() > 0 ? "#ff6b9a" : "#cdb2f7"
                    Accessible.role: Accessible.StaticText
                    Accessible.name: "Threats: " + hud.threatValue() + " " + hud.threatWord()
                }
                Piece {
                    id: defendersPiece
                    objectName: "OverseerStrip_defenders"
                    index: 3
                    visible: summary.fits(3)
                    body: hud.stripCount("warden") + " " + hud.defenderWords()
                }
                Piece {
                    id: warrantsPiece
                    objectName: "OverseerStrip_warrants"
                    index: 4
                    visible: summary.fits(4)
                    body: hud.stripCount("warrants") + " warrants"
                    Accessible.role: Accessible.StaticText
                    Accessible.name: "Warrants: " + hud.stripCount("warrants")
                    Accessible.description: hud.warrantsTooltip
                    HoverHandler { id: warrantsHover }
                    ToolTip.text: hud.warrantsTooltip
                    ToolTip.visible: warrantsHover.hovered
                    ToolTip.delay: 400
                }
                Piece {
                    id: lastEventPiece
                    objectName: "OverseerStrip_lastEvent"
                    index: 5
                    visible: summary.fits(5)
                    readonly property var event: hud.pills ? hud.pills.lastEvent : null
                    body: hud.lastEventText(event)
                    Accessible.role: Accessible.Button
                    Accessible.name: "Last event: " + (event ? event.time + " " + event.summary : "None yet")
                    Accessible.onPressAction: lastEventArea.open()
                    HoverHandler { id: lastEventHover }
                    ToolTip.text: hud.lastEventTip(event)
                    ToolTip.visible: lastEventHover.hovered
                    ToolTip.delay: 400
                    MouseArea {
                        id: lastEventArea
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        function open() {
                            hud.eventsOpen = true
                            hud.showLogRow(lastEventPiece.event ? lastEventPiece.event.seq : undefined)
                        }
                        onClicked: open()
                    }
                }
                Piece {
                    id: healthPiece
                    objectName: "OverseerStrip_health"
                    index: 6
                    visible: summary.fits(6)
                    body: hud.statusLine
                }
            }
        }

        Item {
            id: coreButton
            objectName: "OverseerCoreButton"
            anchors.right: empButton.left
            anchors.rightMargin: 12
            anchors.verticalCenter: empButton.verticalCenter
            width: coreLab.implicitWidth + 16
            height: 28
            z: 5
            Accessible.role: Accessible.Button
            Accessible.name: hud.coreMode ? "Leave core view" : "Core"
            Accessible.description: "Frame the orb close-up, or return to the overview"
            Accessible.onPressAction: hud.hudCommand(hud.coreMode ? "exit_core" : "core_focus", {})
            Text {
                id: coreLab
                anchors.centerIn: parent
                text: "Core"
                color: hud.coreMode ? "#f4efff" : "#cdb2f7"
                font.pixelSize: 14
                font.weight: hud.coreMode ? Font.DemiBold : Font.Medium
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: hud.hudCommand(hud.coreMode ? "exit_core" : "core_focus", {})
            }
        }

        Rectangle {
            id: empButton
            objectName: "OverseerEmergencyStop"
            // 64 px keeps it clear of the close mote in the window corner.
            anchors.right: parent.right
            anchors.rightMargin: 64
            anchors.top: parent.top
            anchors.topMargin: 4
            width: empLabel.implicitWidth + 20
            height: 30
            radius: 15
            color: "#d68ab8"
            z: 5
            Accessible.role: Accessible.Button
            Accessible.name: "Emergency stop"
            Accessible.onPressAction: hud.hudCommand("emp_halt", { reason: "Overseer emergency stop" })
            Text {
                id: empLabel
                anchors.centerIn: parent
                text: "Emergency stop"
                color: "#2a0d1e"
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
            MouseArea {
                anchors.fill: parent
                onClicked: hud.hudCommand("emp_halt", { reason: "Overseer emergency stop" })
            }
        }

        // Shown only while tokens arrive: the host sets tokRate to 0 one
        // second after the last token, so it never reads "0 tok/s" or
        // freezes on a stalled stream.
        // The string is "38 tok/s" with no period. On the 1028 px header a
        // star in the gap after "8" (the text is overlay, the scene shows
        // through) reads as "38. tok/s". An opaque plate in the scene clear
        // colour covers that gap. QtRendering + no hinting also stops a
        // hinted "8" from leaving its own baseline blob.
        Item {
            id: tokReadoutWrap
            objectName: "OverseerTokRatePlate"
            anchors.right: empButton.right
            anchors.top: empButton.bottom
            anchors.topMargin: 6
            width: tokReadout.implicitWidth + 4
            height: tokReadout.implicitHeight + 2
            visible: hud.tokRate > 0
            Rectangle {
                anchors.fill: parent
                color: "#010103"
            }
            Text {
                id: tokReadout
                objectName: "OverseerTokRate"
                anchors.centerIn: parent
                text: hud.tokRate + " tok/s"
                color: "#cdb2f7"
                font.family: hud.monoFamily
                font.pixelSize: 13
                renderType: Text.QtRendering
                font.hintingPreference: Font.PreferNoHinting
                Accessible.role: Accessible.StaticText
                Accessible.name: "Model speed " + text
            }
        }
    }

    // Small borderless text button that opens the unit drawer.
    Item {
        id: unitsButton
        objectName: "OverseerUnitsButton"
        x: hud.marginX
        y: topBar.y + topBar.height
        width: unitsLab.implicitWidth + 16
        height: 28
        Accessible.role: Accessible.Button
        Accessible.name: hud.drawerOpen ? "Hide units" : "Units"
        Accessible.description: "Open or close the unit list"
        Accessible.onPressAction: hud.drawerOpen = !hud.drawerOpen
        Text {
            id: unitsLab
            anchors.verticalCenter: parent.verticalCenter
            text: hud.drawerOpen ? "Units ‹" : "Units ›"
            color: hud.drawerOpen ? "#e8dcfb" : "#cdb2f7"
            font.pixelSize: 14
            font.weight: Font.Medium
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: hud.drawerOpen = !hud.drawerOpen
        }
    }

    Rectangle {
        id: swarmPanel
        objectName: "OverseerSwarmPanel"
        // Overlay drawer from the left, over the scene. Closed by default.
        visible: hud.drawerOpen
        x: hud.marginX
        anchors.top: unitsButton.bottom
        anchors.topMargin: 6
        anchors.bottom: legend.top
        anchors.bottomMargin: 12
        width: Math.min(440, parent.width * 0.26)
        radius: 10
        color: hud.plateFill
        border.color: hud.plateEdge
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
                        return "transparent"
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
        anchors.rightMargin: hud.marginX
        anchors.top: topBar.bottom
        anchors.topMargin: 18
        width: 360
        // Cap: Iris y 1050 (946 below the dock top) and above the dispatch bar.
        height: Math.min(
            dockBody.implicitHeight + 32,
            Math.max(0, dispatchBar.y - 16 - y),
            946
        )
        radius: 12
        color: hud.plateFill
        border.color: hud.plateEdge
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

            // Footer: where this unit's task came from, when that is known.
            Text {
                objectName: "OverseerInspectorOrigin"
                width: parent.width
                visible: text.length > 0
                topPadding: 12
                text: hud.inspector && hud.inspector.origin ? String(hud.inspector.origin) : ""
                color: "#cdb2f7"
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }
        }
        } // dockFlick
    }

    // Dispatch is the only way to give Arelis a job while chat is off (chat is
    // disabled while the Overseer is open). An overlay bar at bottom centre,
    // styled like the chat composer: one rounded plate, a borderless field,
    // Enter or the button sends.
    Rectangle {
        id: dispatchBar
        objectName: "OverseerDispatchBar"
        // Above the replay strip, centred, clear of the legend and Events.
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: replay.top
        anchors.bottomMargin: 20
        width: Math.max(320, Math.min(820, parent.width - 2 * hud.marginX
                                       - 2 * (Math.max(legend.width, eventsButton.width) + 12)))
        height: 48
        radius: 24
        color: hud.plateFill
        border.color: queryField.activeFocus ? "#a473f0" : hud.plateEdge
        border.width: 1
        Accessible.role: Accessible.Grouping
        Accessible.name: "Dispatch"

        Row {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: 10
            spacing: 8
            OverseerComboBox {
                id: modeBox
                objectName: "OverseerMissionMode"
                anchors.verticalCenter: parent.verticalCenter
                width: dispatchBar.width < 560 ? 140 : 176
                height: 32
                model: ["multi", "arxiv", "horizons", "wikipedia", "security_audit"]
                onActivated: hud.missionMode = currentText
            }
            TextField {
                id: queryField
                objectName: "OverseerMissionQuery"
                Accessible.name: "Mission query"
                anchors.verticalCenter: parent.verticalCenter
                width: dispatchBar.width - modeBox.width - dispatchButton.width - 10 - 8 - 8 - 8
                height: 36
                placeholderText: width < 200 ? "Research query"
                                 : width < 300 ? "Give the sentinels a job"
                                             : "Give the sentinels a job: research query, planet, or topic"
                color: "#e8dcfb"
                placeholderTextColor: "#a090d4"
                font.pixelSize: 16
                background: Item {}
                onTextChanged: hud.missionQuery = text
                onAccepted: dispatchButton.dispatch()
            }
            Rectangle {
                id: dispatchButton
                objectName: "OverseerDispatch"
                anchors.verticalCenter: parent.verticalCenter
                height: 34
                width: 100
                radius: 17
                color: "transparent"  // outline only: Emergency stop is the one filled control
                border.color: "#8b6cf2"
                function dispatch() {
                    hud.hudCommand("dispatch", { mode: hud.missionMode, query: hud.missionQuery })
                }
                Accessible.role: Accessible.Button
                Accessible.name: "Dispatch"
                Accessible.description: "Send the mission in Mode with the query"
                Accessible.onPressAction: dispatchButton.dispatch()
                Text { anchors.centerIn: parent; text: "Dispatch"; color: "#e8dcfb"; font.pixelSize: 14 }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: dispatchButton.dispatch()
                }
            }
        }
    }

    Text {
        objectName: "OverseerCommandStatus"
        anchors.horizontalCenter: dispatchBar.horizontalCenter
        anchors.top: dispatchBar.bottom
        anchors.topMargin: 2
        text: hud.commandStatus
        color: "#cdb2f7"
        font.pixelSize: 12
    }

    // The event list folds into an overlay opened from this text button.
    Item {
        id: eventsButton
        objectName: "OverseerEventsButton"
        x: parent.width - hud.marginX - width
        anchors.verticalCenter: dispatchBar.verticalCenter
        width: eventsLab.implicitWidth + 16
        height: 28
        Accessible.role: Accessible.Button
        Accessible.name: hud.eventsOpen ? "Hide events" : "Events"
        Accessible.description: "Open or close the event list"
        Accessible.onPressAction: hud.eventsOpen = !hud.eventsOpen
        Text {
            id: eventsLab
            anchors.verticalCenter: parent.verticalCenter
            text: hud.eventsOpen ? "Events ˅" : "Events ˄"
            color: hud.eventsOpen ? "#e8dcfb" : "#cdb2f7"
            font.pixelSize: 14
            font.weight: Font.Medium
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: hud.eventsOpen = !hud.eventsOpen
        }
    }

    Rectangle {
        id: consolePanel
        objectName: "OverseerConsole"
        visible: hud.eventsOpen
        x: hud.marginX
        width: parent.width - 2 * hud.marginX
        anchors.bottom: dispatchBar.top
        anchors.bottomMargin: 12
        height: 230
        radius: 10
        color: hud.plateFill
        border.color: hud.plateEdge
        border.width: 1

        Column {
            id: consoleControls
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            spacing: 6

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

    // Legend (GAP item 11): bottom left, above the replay strip. One row per
    // caste: dot, name, live count, role.
    readonly property var legendRows: [
        ["warden", "Warden", "#a473f0", "guards the core"],
        ["harvester", "Harvester", "#8fd3ff", "fetches sources"],
        ["sanitizer", "Sanitizer", "#f2c56b", "checks results"],
        ["tripwire", "Tripwire", "#7ee0c8", "watches the edge"],
        ["stalker", "Stalker", "#e879f9", "hunts threats"]
    ]

    Rectangle {
        id: legend
        objectName: "OverseerLegend"
        x: hud.marginX
        anchors.bottom: replay.top
        anchors.bottomMargin: 12
        width: legendColumn.implicitWidth + 24
        height: legendColumn.implicitHeight + 20
        radius: 8
        color: hud.plateFill
        border.color: hud.plateEdge
        border.width: 1
        Accessible.role: Accessible.Grouping
        Accessible.name: "Legend"

        Column {
            id: legendColumn
            x: 12
            y: 10
            spacing: 4
            Repeater {
                model: hud.legendRows
                Row {
                    required property var modelData
                    objectName: "OverseerLegend_" + modelData[0]
                    spacing: 8
                    Accessible.role: Accessible.StaticText
                    Accessible.name: modelData[1] + " " + hud.stripCount(modelData[0]) + ", " + modelData[3]
                    Rectangle {
                        width: 8; height: 8; radius: 4
                        anchors.verticalCenter: parent.verticalCenter
                        color: parent.modelData[2]
                    }
                    Text {
                        width: 70
                        text: parent.modelData[1]
                        color: "#e8dcfb"
                        font.family: hud.titleFamily
                        font.pixelSize: 13
                        font.weight: Font.Medium
                    }
                    Text {
                        width: 28
                        text: hud.stripCount(parent.modelData[0])
                        color: "#e8dcfb"
                        font.family: hud.monoFamily
                        font.pixelSize: 13
                    }
                    Text {
                        text: parent.modelData[3]
                        color: "#cdb2f7"
                        font.family: hud.titleFamily
                        font.pixelSize: 13
                    }
                }
            }
            Text {
                objectName: "OverseerLegendFooter"
                topPadding: 2
                text: "Red eyes appear only on a real threat."
                color: "#cdb2f7"
                font.family: hud.titleFamily
                font.pixelSize: 12
            }
        }
    }

    // Replay strip (GAP item 12): the last 10 minutes, one tick per event,
    // coloured by type, the playhead at now on the right. Ticks are plain
    // Rectangles placed once at their own time inside a track that slides
    // left on a 4 Hz clock, so the scene graph batches them into one draw and
    // nothing is rebuilt per poll. Clicking a tick opens the event list at
    // that event. There is no scrubbing.
    readonly property real replayWindow: 600
    readonly property var replayColors: ({
        "fetch": "#8fd3ff",
        "result": "#cdb2f7",
        "tripwire": "#7ee0c8",
        "threat": "#ff6b9a",
        "other": "#6f5a9e"
    })
    property real replayNow: Date.now() / 1000
    property int replayLastSeq: -1

    ListModel { id: replayModel }

    function syncReplay() {
        var rows = replayTicks || []
        var newest = rows.length ? rows[rows.length - 1].seq : -1
        // A new hive (seq restarted) or a reset log: start over.
        if (newest < replayLastSeq) {
            replayModel.clear()
            replayLastSeq = -1
        }
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i]
            if (r.seq > replayLastSeq) {
                replayModel.append({ seq: r.seq, t: r.t, kind: String(r.kind || "other") })
                replayLastSeq = r.seq
            }
        }
        pruneReplay()
    }

    function pruneReplay() {
        var start = replayNow - replayWindow
        var n = 0
        while (n < replayModel.count && replayModel.get(n).t < start)
            n++
        if (n > 0)
            replayModel.remove(0, n)
    }

    function nearestReplayTick(px) {
        var best = -1
        var bestDist = 8
        for (var i = 0; i < replayModel.count; i++) {
            var d = Math.abs(replayTrack.x + replayTrack.xFor(replayModel.get(i).t) - px)
            if (d <= bestDist) {
                bestDist = d
                best = replayModel.get(i).seq
            }
        }
        return best
    }

    function openReplayTick(seq) {
        eventsOpen = true
        showLogRow(seq)
    }

    onReplayTicksChanged: syncReplay()

    Timer {
        interval: 250
        running: hud.visible
        repeat: true
        onTriggered: {
            hud.replayNow = Date.now() / 1000
            hud.pruneReplay()
        }
    }

    Item {
        id: replay
        objectName: "OverseerReplay"
        x: hud.marginX
        width: parent.width - 2 * hud.marginX
        anchors.bottom: parent.bottom
        anchors.bottomMargin: hud.marginY
        height: 48
        Accessible.role: Accessible.Button
        Accessible.name: "Replay, last 10 minutes, " + replayModel.count + " events"
        Accessible.description: "Open the event list at the newest event"
        Accessible.onPressAction: hud.openReplayTick(replayModel.count ? replayModel.get(replayModel.count - 1).seq : -1)

        Row {
            id: replayKey
            spacing: 14
            height: 14
            Text {
                text: "Replay · last 10 min"
                color: "#cdb2f7"
                font.family: hud.titleFamily
                font.pixelSize: 12
            }
            Repeater {
                model: [["fetch", "fetch"], ["result", "result in"], ["tripwire", "tripwire check"], ["threat", "threat"]]
                Row {
                    required property var modelData
                    spacing: 4
                    Rectangle { width: 2; height: 10; anchors.verticalCenter: parent.verticalCenter; color: hud.replayColors[parent.modelData[0]] }
                    Text { text: parent.modelData[1]; color: "#cdb2f7"; font.family: hud.titleFamily; font.pixelSize: 11 }
                }
            }
        }

        Item {
            id: replayBand
            y: 18
            width: parent.width
            height: 16
            clip: true
            Rectangle { y: parent.height - 1; width: parent.width; height: 1; color: hud.plateEdge }
            Item {
                id: replayTrack
                objectName: "OverseerReplayTrack"
                readonly property real pxPerSec: replayBand.width / hud.replayWindow
                // Ticks keep their x for life; only this offset moves.
                readonly property real origin: Math.floor(hud.replayNow / 3600) * 3600 - 3600
                function xFor(t) { return (t - origin) * pxPerSec }
                x: -(hud.replayNow - hud.replayWindow - origin) * pxPerSec
                height: parent.height
                Repeater {
                    model: replayModel
                    Rectangle {
                        required property real t
                        required property string kind
                        x: replayTrack.xFor(t)
                        y: kind === "threat" ? 0 : 5
                        width: 2
                        height: parent.height - y
                        color: hud.replayColors[kind] || hud.replayColors.other
                    }
                }
            }
            Rectangle {
                objectName: "OverseerReplayPlayhead"
                x: parent.width - 2
                width: 2
                height: parent.height
                color: "#e8dcfb"
            }
        }

        MouseArea {
            x: replayBand.x
            y: replayBand.y - 4
            width: replayBand.width
            height: replayBand.height + 8
            cursorShape: Qt.PointingHandCursor
            onClicked: (mouse) => {
                var seq = hud.nearestReplayTick(mouse.x)
                if (seq >= 0)
                    hud.openReplayTick(seq)
            }
        }

        Text {
            y: 36
            text: "-10 min"
            color: "#cdb2f7"
            font.family: hud.monoFamily
            font.pixelSize: 11
        }
        Text {
            y: 36
            x: (parent.width - width) / 2
            text: "-5"
            color: "#cdb2f7"
            font.family: hud.monoFamily
            font.pixelSize: 11
        }
        Text {
            y: 36
            x: parent.width - width
            text: "now"
            color: "#cdb2f7"
            font.family: hud.monoFamily
            font.pixelSize: 11
        }
    }
}

import QtQuick
import QtQuick3D
import QtQuick3D.Helpers
import Arelis.Overseer

Item {
    id: root
    objectName: "OverseerView"
    focus: true
    Keys.onEscapePressed: function (event) {
        if (root.coreMode || root.cameraMode === "core" || root.coreTransitioning) {
            root.exitCoreFocus()
            event.accepted = true
        }
    }
    // Default view is Iris's wide frame (BAND-SPEC.md "Camera framing"): the
    // camera sits at k * (0, -78, 44) and looks at k * (0, 3, -6) in spec space,
    // k = perimeter / 35. In scene space that is a look target k * (0, -6, -3),
    // 95.19 * k m away along a 31.68 deg pitch (89.6 m and 29.4 deg from the
    // hive centre). The distance only grows past that when the free scene
    // area is too small to hold the perimeter and every source with its label.
    readonly property real specPitchDeg: 31.6864
    readonly property real specDistance: 95.1893
    property real overviewDistance: 95.1893
    property string overviewKey: ""
    // Wheel position in notches from the default frame. The first
    // easeNotches notches ease distance and pitch from the default frame onto
    // the approved curve at its 55 deg wide mark; past that the curve applies.
    readonly property real easeNotches: 3
    readonly property real easeJoinDistance: 96.0
    property real zoomZ: 0
    property real cameraDistance: 95.1893
    property real cameraPitch: 31.6864
    property real cameraTargetX: 0
    property real cameraTargetY: -6
    property real cameraTargetZ: -3
    property real wheelPivotX: 0
    property real wheelPivotY: 0
    property real wheelPivotZ: 0
    property bool wheelPivotLive: false
    property var unitPositions: ({})
    property int particleBudget: 520
    property real sceneTime: 0
    property var entryPool: []
    property var liveByKey: ({})
    property int liveEntryCount: 0
    property int pooledEntryCount: 0
    property int totalEntryCount: 0
    property real entryMs: 0
    property bool entryPlaying: false
    property bool reducedMotion: false
    property bool reversing: false
    property real edge: 0
    property real fill: 0
    property real reveal: 0
    property real moteFlight: 0
    property bool inputLive: false
    property int budgetTris: 0
    property int budgetDrawCalls: 0
    property int unitDrawCalls: 0
    property var lodCounts: [0, 0, 0]
    property var meshTris: ({ "0": 47140, "1": 14480, "2": 1852 })
    readonly property var strandsByLod: [19, 13, 10]
    property var lists: ({})
    property var descriptors: []
    property var mergedLists: ({})
    property var mergedDescriptors: []
    property var mergedCounts: ({})
    property var particleList: null
    property var conduitList: null
    property var conduitSpecs: []
    property var unitAnimSpecs: []
    // Idle lane units: one spec per unit (its entries, orbit, apply time). The
    // view moves them along their lane, so the host sends a frame only when
    // something else changes.
    property var unitOrbitSpecs: []
    property var orbitEntries: ({})
    property var liveCounts: ({})
    onSceneTimeChanged: root.stepConduits()
    property var hudPills: ({})
    property var swarmRows: []
    property var inspectorCard: ({})
    property var hudLogs: []
    property var replayTicks: []
    // Set by the host each poll from token_meter; 0 hides the readout.
    property int tokRate: 0
    onTokRateChanged: orbEnergy = Math.max(0.3, Math.min(1.0, 0.3 + 0.7 * tokRate / 60.0))
    property var collapsedGroups: []
    property string selectedUnitId: ""
    property string cameraMode: "overview"
    property int placementFrameId: 0
    property var instanceRecords: ({})
    // Per unit: open-fetch reach pairs now and before, and the sceneTime the
    // count changed, so the vertex shader eases the reach with no CPU per frame.
    property var reachState: ({})
    property var reachNext: ({})
    // Glyph trails: one instance per glyph, rebuilt only when the set of live
    // trails changes. Births are sceneTime so the shader runs the flow.
    property var glyphList: null
    property var glyphTrailBirth: ({})
    property string glyphTrailKey: ""
    property int glyphCount: 0
    property string glyphFontFamily: "Space Mono"
    property int orbLabelComputeCount: 0
    property var orbOrnamentPositions: []
    property var orbOrnamentNormals: []
    property var orbOrnamentColors: []
    property var orbOrnamentUvs: []
    property var orbOrnamentIndexes: []
    property string orbOrnamentKey: ""
    property var starPositions: []
    property var starColors: []
    property var starUv0s: []
    property var starUv1s: []
    property var starIndexes: []
    // Caste bands (BAND-SPEC.md): lane guides rebuild only when a band's
    // lane count or radius changes; the perimeter follows the Harvester band.
    property var bandSpecs: []
    property string bandKey: ""
    property var bandGuidePositions: []
    property var bandGuideColors: []
    property real perimeterRadius: 35.0
    property string swarmGroupBy: "caste"
    property string swarmSearch: ""
    property string logFilter: "all"
    property string logQuery: ""
    property bool logRepeats: true
    property string missionMode: "multi"
    property string missionQuery: ""
    property string hudStatusLine: "hive live · all local · sending out blocked"
    property var sourceLabelSpecs: []
    property var sourceLabelScreen: []
    property string sourceLabelKey: ""
    onWidthChanged: {
        updateOverview()
        projectSourceLabels()
    }
    onHeightChanged: {
        updateOverview()
        projectSourceLabels()
    }
    onShowInspectorChanged: updateOverview()
    onCoreModeChanged: {
        bandKey = ""
        applyBands(bandSpecs, perimeterRadius)
        projectOrbLabels()
    }
    onLaneCoreMulChanged: {
        bandKey = ""
        applyBands(bandSpecs, perimeterRadius)
    }
    property string hudCommandStatus: ""
    property string lastHudCommand: ""
    property var lastHudPayload: ({})
    readonly property var casteIds: ["warden", "stalker", "harvester", "sanitizer", "tripwire"]
    readonly property var casteColors: ({
        warden: "#a78bfa", stalker: "#e879f9", harvester: "#8fd3ff",
        sanitizer: "#f2c56b", tripwire: "#7ee0c8"
    })
    // Eye lenses in caste colour (GAP.md item 1). A fetching Harvester's eyes
    // (#2fc4ff) and red engaged eyes come per instance from the runtime.
    readonly property var lensColors: ({
        warden: "#a473f0", stalker: "#e879f9", harvester: "#8fd3ff",
        sanitizer: "#f2c56b", tripwire: "#7ee0c8"
    })
    // Pass A look constants (GAP.md items 1, 4, 8, 9). Each is one number so
    // Babbage can trace alternatives on Atria without touching anything else.
    // No AA (1 sample): see passA/RESULT.md. On the box MSAA 2x added about
    // 14 ms p95 at 128 units, FXAA about 5 and TAA about 4.
    readonly property int msaaSamples: 1
    readonly property int glowLevels: 3
    readonly property real glowThreshold: 1.0
    readonly property real eyeEmission: 2.4
    // Smallest on-screen eye radius in px, so every eye feeds the bloom.
    readonly property real eyeMinPx: 2.0
    // Lane guides stay soft: edge lanes 0.28, middle lanes 0.16 of caste colour.
    // In coreFocus the lanes crossing the orb are dimmed to 0.35 of those.
    readonly property real laneEdgeEmission: 0.28
    readonly property real laneMidEmission: 0.16
    readonly property real laneCoreMul: coreMode ? 0.35 : 1.0
    readonly property color skyColor: "#010103"
    readonly property color fogColor: "#120a1d"
    readonly property real fogNear: 40
    readonly property real fogFar: 110
    readonly property color hullColor: "#40345f"
    // Perimeter #7ee0c8 at about 60 percent on screen so the eyes, not the
    // ring, lead. The Filmic tonemap lifts it by about 1.16, so the material
    // runs at 0.52 to land near #5b9286 in the frame.
    readonly property real perimeterLevel: 0.52
    readonly property color perimeterColor: Qt.rgba(0x7e / 255 * perimeterLevel, 0xe0 / 255 * perimeterLevel, 0xc8 / 255 * perimeterLevel, 1)
    // Stars: 3 parallax layers, 1,000 points in all. Drift follows hive
    // activity (open requests), never tok/s: with chat off tok/s is mostly 0.
    readonly property var starLayers: [
        { count: 450, from: Qt.vector3d(-260, -70, -260), to: Qt.vector3d(260, -18, 120), px0: 1.0, px1: 1.8, rate: 0.35, seed: 11 },
        { count: 400, from: Qt.vector3d(-320, -20, -330), to: Qt.vector3d(320, 120, -150), px0: 1.0, px1: 2.4, rate: 0.6, seed: 23 },
        { count: 150, from: Qt.vector3d(-120, 18, -40), to: Qt.vector3d(120, 60, 60), px0: 1.8, px1: 3.0, rate: 1.0, seed: 37 }
    ]
    // The host sets paused when the Sentinels window is hidden or closed so
    // FrameAnimation does not keep running under generation with no view.
    property bool paused: true
    readonly property bool viewOnScreen: visible && !paused
    property real hiveActivity: 0
    property real hiveActivityShown: 0
    property real starDrift: 0
    // Orb energy follows real tok/s (idle floor 0.3, 1.0 at 60). Unchanged.
    property real orbEnergy: 0.3
    property real orbEnergyShown: 0.3
    // Pass D visual values. Bloom stays 3 levels, threshold 1.0.
    readonly property real orbRadius: 2.6
    readonly property vector3d orbCentre: Qt.vector3d(0, 1.6, 0)
    readonly property real orbCoreGain: 0.78
    readonly property real orbCoreFloor: 0.5
    readonly property real orbCoreSoftPow: 1.6
    readonly property real orbCoreTightPow: 16.0
    readonly property real orbCoreTightMix: 0.7
    readonly property real orbFilamentGain: 0.85
    readonly property real orbShellGain: 0.75
    readonly property real orbShellBody: 0.06
    readonly property real orbPulseShellGain: 0.6
    readonly property real orbShellPower: 3.0
    readonly property real memoryRingRadius: 4.03
    readonly property real toolsRingRadius: 4.68
    readonly property real resultsRingAuthored: 5.98
    readonly property real memoryBeadRadius: 0.05
    readonly property real toolsBeadRadius: 0.10
    readonly property real memPhase: 0.1
    readonly property real toolPhase: 0.35
    readonly property real ringMinPx: 1.25
    readonly property real ringBackGain: 0.5
    readonly property real filTube: 0.0065
    readonly property real filMinPx: 1.0
    property real orbSpinAngle: 0
    property int memoryCount: 0
    property string memoryLabel: "Memory · 0 from last chat"
    property int toolsCount: 0
    property string toolsLabel: "Tools 0 running"
    property var orbTools: []
    property var orbResults: []
    property real resultsRadius: 5.98
    property real resultsFade: 1.0
    property var toolsLitArc: Qt.vector3d(0, 0, 2)
    property var orbImpact: Qt.vector4d(0, 1, 0, -1)
    property real pulseScale: 1.0
    property real pulseGain: 0
    property real memorySpin: 0
    property real toolsSpin: 0
    // coreFocus: a separate camera preset on the orb centre. The overview
    // scale and the 24 m unit focus stay as they are.
    property bool coreMode: false
    property bool coreTransitioning: false
    property real coreEaseU: 0
    property real coreEaseFromD: 95.1893
    property real coreEaseFromPitch: 31.6864
    property real coreEaseFromX: 0
    property real coreEaseFromY: -6
    property real coreEaseFromZ: -3
    property real coreEaseToD: 15
    property real coreEaseToPitch: 22
    property real coreEaseToX: 0
    property real coreEaseToY: 1.6
    property real coreEaseToZ: 0
    property string coreEaseIntent: ""
    readonly property real coreFocusPitch: 22.0
    readonly property real coreFocusMinDistance: 10.0
    readonly property real coreFocusMaxDistance: 24.0
    // Direction toward each directional light (Lambert L vector).
    // Lights: euler (-40, 30) brightness 1.0 and (-15, -120) brightness 0.35.
    readonly property vector3d lightKeyDir: {
        var x = -40 * Math.PI / 180, y = 30 * Math.PI / 180
        var vy = Math.sin(x), vz = -Math.cos(x)
        var d = Qt.vector3d(vz * Math.sin(y), vy, vz * Math.cos(y))
        return Qt.vector3d(-d.x, -d.y, -d.z)
    }
    readonly property vector3d lightFillDir: {
        var x = -15 * Math.PI / 180, y = -120 * Math.PI / 180
        var vy = Math.sin(x), vz = -Math.cos(x)
        var d = Qt.vector3d(vz * Math.sin(y), vy, vz * Math.cos(y))
        return Qt.vector3d(-d.x, -d.y, -d.z)
    }
    property string hudSansFamily: "Zen Kaku Gothic New"
    property var sourceNodeSpecs: []
    property var sourceList: sourceInstanceList
    property var memoryBeadList: memoryBeadInstanceList
    property var toolBeadList: toolBeadInstanceList
    property var tentacleLists: ({
        "0": tentacleLod0List,
        "1": tentacleLod1List,
        "2": tentacleLod2List
    })
    property var tentacleCounts: ({})
    InstanceList { id: sourceInstanceList }
    InstanceList { id: memoryBeadInstanceList }
    InstanceList { id: toolBeadInstanceList }
    InstanceList { id: tentacleLod0List }
    InstanceList { id: tentacleLod1List }
    InstanceList { id: tentacleLod2List }
    InstanceList { id: mergedHead0List }
    InstanceList { id: mergedHead1List }
    InstanceList { id: mergedHead2List }

    function startEntry(reduced) {
        reducedMotion = !!reduced
        reversing = false
        entryMs = 0
        entryPlaying = true
        entryAnim.duration = reducedMotion ? 200 : 1600
        entryAnim.from = 0
        entryAnim.to = entryAnim.duration
        entryAnim.restart()
    }

    function startExit(reduced) {
        reversing = true
        reducedMotion = !!reduced
        entryPlaying = true
        entryAnim.duration = reducedMotion ? 200 : 500
        entryAnim.from = entryMs
        entryAnim.to = 0
        entryAnim.restart()
    }

    function applyFrame(frame) {
        if (!frame || !frame.buckets)
            return
        placementFrameId += 1
        var recs = ({})
        reachNext = ({})
        var tstate = ({})
        ensureLists()
        releaseAllLists()
        var buckets = frame.buckets
        var counts = ({})
        var used = 0
        var tris = 0
        var lods = [0, 0, 0]
        var live = 0
        var animSpecs = []
        var orbitSpecs = []
        var orbitBy = ({})
        for (var ci = 0; ci < casteIds.length; ci++) {
            var caste = casteIds[ci]
            for (var lod = 0; lod < 3; lod++) {
                var rows = buckets[caste + ":" + lod] || []
                lods[lod] += rows.length
                var partsThisLod = ["head"]
                for (var pi = 0; pi < partsThisLod.length; pi++) {
                    var part = partsThisLod[pi]
                    var key = caste + ":" + lod + ":" + part
                    var lst = lists[key]
                    if (!lst)
                        continue
                    var entries = []
                    for (var i = 0; i < rows.length; i++) {
                        var row = rows[i]
                        var uEntry = fillUnitEntry(row, caste, key, recs)
                        entries.push(uEntry)
                        if (row && row.unit_id && !tstate[row.unit_id]) {
                            var prev = tentacleUnitState[row.unit_id] || ({})
                            tstate[row.unit_id] = {
                                speed: (row.speed === undefined || row.speed === null) ? 0.55 : row.speed,
                                limp: row.limp ? 1 : 0,
                                reach: finiteNum(row.reach, 0),
                                phase: finiteNum(row.phase, 0),
                                target: row.target || null,
                                lenMul: finiteNum(row.lenMul, 1.0),
                                kappa: finiteNum(row.kappa, 0),
                                state: String(row.state || ""),
                                open_fetches: finiteNum(row.open_fetches, 0),
                                eyeMul: finiteNum(row.eyeMul, 1.0),
                                index: finiteNum(row.index, 0),
                                caste: caste,
                                color: row.color || casteColors[caste],
                                eye: row.eye || casteColors[caste],
                                wIdle: finiteNum(prev.wIdle, 0),
                                wReach: finiteNum(prev.wReach, 0),
                                wHold: finiteNum(prev.wHold, 0),
                                wCoil: finiteNum(prev.wCoil, 0),
                                wStrike: finiteNum(prev.wStrike, 0),
                                wLimp: finiteNum(prev.wLimp, 0),
                                clawOpen: finiteNum(prev.clawOpen, 0.10),
                                clawOpenArm: finiteNum(prev.clawOpenArm, 0.10),
                                time0: (prev.time0 === undefined) ? sceneTime : prev.time0,
                                mode: prev.mode || "cruise",
                                kHold: finiteNum(prev.kHold, 0.4),
                                grabClock: finiteNum(prev.grabClock, -1),
                                strikeClock: finiteNum(prev.strikeClock, -1)
                            }
                        }
                        var orb = row ? row.orbit : null
                        if (orb && orb.length >= 7) {
                            var os = orbitBy[row.unit_id]
                            if (!os) {
                                os = {
                                    o: orb, t0: sceneTime, entries: [],
                                    cx: Math.cos(orb[0]), sx: Math.sin(orb[0]),
                                    cy: Math.cos(orb[1]), sy: Math.sin(orb[1])
                                }
                                orbitBy[row.unit_id] = os
                                orbitSpecs.push(os)
                            }
                            os.entries.push(uEntry)
                            continue
                        }
                        var rvx = finiteNum(row ? row.vx : 0, 0)
                        var rvy = finiteNum(row ? row.vy : 0, 0)
                        var rvz = finiteNum(row ? row.vz : 0, 0)
                        if (rvx !== 0 || rvy !== 0 || rvz !== 0) {
                            animSpecs.push({
                                entry: uEntry,
                                vx: rvx,
                                vy: rvy,
                                vz: rvz
                            })
                        }
                    }
                    lst.instances = entries
                    liveByKey[key] = entries
                    counts[key] = entries.length
                    live += entries.length
                    if (entries.length > 0) {
                        used += 1
                        tris += (meshTris[String(lod)] || 0) * entries.length
                    }
                }
            }
        }
        unitAnimSpecs = animSpecs
        unitOrbitSpecs = orbitSpecs
        orbitEntries = orbitBy
        reachState = reachNext
        tentacleUnitState = tstate
        counts["__particles"] = 0
        var cEntries = fillConduitEntries(frame.conduits || [])
        counts["__conduits"] = cEntries.length
        live += cEntries.length
        applyGlyphTrails(frame.glyphTrails || [])
        applyBands(frame.bands || [], frame.perimeter)
        hiveActivity = Math.max(0, Math.min(1, finiteNum(frame.hiveActivity, 0)))
        applyOrb(frame.orb || ({}))
        sourceNodeSpecs = frame.sourceNodes || []
        fillSourceEntries(sourceNodeSpecs)
        fillBeadEntries()
        rebuildOrbOrnaments()
        counts["__glyphs"] = glyphCount
        live += glyphCount
        fillTentacleEntries(recs)
        liveCounts = counts
        budgetTris = tris
        unitDrawCalls = mergeUnitDraws()
        budgetDrawCalls = unitDrawCalls + 16  // SCENE_FIXED_DRAW: orb (one ornament draw), sources, tentacles, lanes, stars
        lodCounts = lods
        recountEntries(live)
        instanceRecords = recs
        rememberUnitPositions(buckets)
        sourceLabelSpecs = frame.sourceLabels || []
        updateOverview()
        projectSourceLabels()
        refreshUnitTex()
        var b = frame.budget
        if (b) {
            if (b.unitTris !== undefined && b.unitTris !== tris)
                root.budgetFileTris = b.unitTris
        }
    }

    property int budgetFileTris: 0

    function applyUnits(units) {
        // Fallback when the host sends a raw unit list (tests / snapshot).
        applyFrame({ buckets: _bucketize(units || []) })
    }

    function applyHud(hud) {
        if (!hud)
            return
        if (hud.pills !== undefined)
            hudPills = hud.pills
        if (hud.swarmRows !== undefined)
            swarmRows = hud.swarmRows
        if (hud.inspector !== undefined)
            inspectorCard = hud.inspector
        if (hud.logs !== undefined)
            hudLogs = hud.logs
        if (hud.ticks !== undefined)
            replayTicks = hud.ticks
        if (hud.statusLine)
            hudStatusLine = hud.statusLine
        if (hud.commandStatus !== undefined)
            hudCommandStatus = hud.commandStatus
    }

    // Rank 3: the dock exists only while a unit is selected. No empty inspector.
    function inspectorShouldHide() {
        return !selectedUnitId
    }

    readonly property bool showInspector: !inspectorShouldHide()
    property bool unitFocused: false

    function selectUnit(unitId) {
        selectedUnitId = unitId || ""
        if (cameraMode === "ease")
            cameraMode = "follow"
        if (!selectedUnitId)
            unitFocused = false
        syncCameraTargetFromSelection()
    }

    function pitchDeg(distance) {
        var lo = 6.0
        var hi = 110.0
        var d = Math.max(lo, Math.min(hi, distance))
        var marks = [[6.0, 22.0], [9.0, 22.0], [32.0, 36.0], [96.0, 55.0], [110.0, 55.0]]
        if (d <= marks[0][0])
            return marks[0][1]
        for (var i = 1; i < marks.length; i++) {
            if (d <= marks[i][0]) {
                var d0 = marks[i - 1][0]
                var p0 = marks[i - 1][1]
                var d1 = marks[i][0]
                var p1 = marks[i][1]
                if (d0 <= 0 || d1 <= 0 || d0 === d1)
                    return p1
                var u = Math.log(d / d0) / Math.log(d1 / d0)
                return p0 + u * (p1 - p0)
            }
        }
        return marks[marks.length - 1][1]
    }

    function framingName() {
        if (cameraMode === "core" || coreMode)
            return "core"
        var d = cameraDistance
        if (d >= 6.0 && d <= 9.0)
            return "close"
        if (d >= 18.0 && d <= 40.0)
            return "mid"
        if (d > 40.0)
            return "wide"
        return "unclassified"
    }

    function cameraEvidence() {
        return {
            cameraDistance: cameraDistance,
            cameraPitch: cameraPitch,
            cameraTargetX: cameraTargetX,
            cameraTargetY: cameraTargetY,
            cameraTargetZ: cameraTargetZ,
            selectedUnitId: selectedUnitId,
            framing: framingName(),
            cameraMode: cameraMode,
            coreMode: coreMode
        }
    }

    function setCameraTarget(x, y, z) {
        cameraTargetX = x
        cameraTargetY = y
        cameraTargetZ = z
    }

    function setWheelPivot(x, y, z) {
        wheelPivotX = x
        wheelPivotY = y
        wheelPivotZ = z
        wheelPivotLive = true
    }

    function clearWheelPivot() {
        wheelPivotLive = false
    }

    function readRowPos(row) {
        if (!row)
            return null
        var x = row.x, y = row.y, z = row.z
        if ((x === undefined || x === null) && row.position)
            x = row.position[0]
        if ((y === undefined || y === null) && row.position)
            y = row.position[1]
        if ((z === undefined || z === null) && row.position && row.position.length > 2)
            z = row.position[2]
        if (x === undefined || x === null || y === undefined || y === null)
            return null
        if (z === undefined || z === null)
            z = 0
        x = finiteNum(x, Number.NaN)
        y = finiteNum(y, Number.NaN)
        z = finiteNum(z, Number.NaN)
        if (x !== x || y !== y || z !== z)
            return null
        return { x: x, y: y, z: z }
    }

    function unitPositionOf(unitId) {
        if (!unitId || !unitPositions)
            return null
        // A lane unit is where the view has moved it, not where the last frame put it.
        var os = orbitEntries ? orbitEntries[unitId] : null
        if (os && os.entries.length) {
            var p = os.entries[0].position
            return { x: p.x, y: p.y, z: p.z }
        }
        return unitPositions[unitId] || null
    }

    function syncCameraTargetFromSelection() {
        if (cameraMode === "fit" || cameraMode === "ease" || cameraMode === "core" || coreMode)
            return false
        var pos = unitPositionOf(selectedUnitId)
        if (!pos)
            return false
        // Selecting a unit leaves the overview and follows it, as before.
        cameraMode = "follow"
        setCameraTarget(pos.x, pos.y, pos.z)
        return true
    }

    // Spec look direction, distance fitted to the free scene area.
    function applyOverview() {
        var s = overviewDistance / specDistance
        setCameraTarget(0, -6 * s, -3 * s)
        cameraDistance = overviewDistance
        cameraPitch = specPitchDeg
    }

    function showOverview() {
        root.snapOutOfCore()
        cameraMode = "overview"
        unitFocused = false
        applyOverview()
    }

    // Everything the default view must hold: the perimeter ring, the outer
    // band lanes, and each edge source with room for its name under it.
    function overviewPoints() {
        var pts = []
        var r = finiteNum(perimeterRadius, 35)
        for (var i = 0; i < 24; i++) {
            var a = i / 24 * Math.PI * 2
            pts.push({ p: Qt.vector3d(r * Math.cos(a), 0.02, r * Math.sin(a)), label: false })
        }
        var bands = bandSpecs || []
        for (var bi = 0; bi < bands.length; bi++) {
            var lanes = bands[bi].lanes || []
            if (!lanes.length)
                continue
            var outer = lanes[lanes.length - 1]
            for (var j = 0; j < 12; j++)
                pts.push({ p: bandPoint(bands[bi], outer, j / 12 * Math.PI * 2), label: false })
        }
        var specs = sourceLabelSpecs || []
        for (var si = 0; si < specs.length; si++) {
            var sp = specs[si]
            if (sp)
                pts.push({ p: Qt.vector3d(finiteNum(sp.x), finiteNum(sp.y), finiteNum(sp.z)), label: true })
        }
        return pts
    }

    // Screen position of a scene point for a camera at distance d and pitch
    // pitchDegValue on the overview target, with the HUD lens shift. Same
    // maths as the PerspectiveCamera binding (35 deg vertical FOV).
    function overviewProject(world, d, pitchDegValue) {
        var w = Math.max(1, width)
        var h = Math.max(1, height)
        var p = pitchDegValue * Math.PI / 180
        var s = d / specDistance
        var sh = lensShiftFor(d, pitchDegValue)
        var cx = sh.x
        var cy = -6 * s + Math.sin(p) * d + sh.y
        var cz = -3 * s + Math.cos(p) * d + sh.z
        var vx = world.x - cx
        var vy = world.y - cy
        var vz = world.z - cz
        var depth = -(vy * Math.sin(p) + vz * Math.cos(p))
        var up = vy * Math.cos(p) - vz * Math.sin(p)
        if (depth <= 0.1)
            return null
        var t = Math.tan(35 * Math.PI / 360)
        return {
            x: w / 2 + vx / (depth * t * (w / h)) * (w / 2),
            y: h / 2 - up / (depth * t) * (h / 2)
        }
    }

    function overviewFits(d, pts, free) {
        for (var i = 0; i < pts.length; i++) {
            var m = overviewProject(pts[i].p, d, specPitchDeg)
            if (!m)
                return false
            // A source needs its name (about 120 x 50 px) under it; a ring
            // point needs a small margin.
            var hx = pts[i].label ? 64 : 8
            var top = pts[i].label ? 14 : 8
            var below = pts[i].label ? 64 : 8
            if (m.x - hx < free.x || m.x + hx > free.x + free.width)
                return false
            if (m.y - top < free.y || m.y + below > free.y + free.height)
                return false
        }
        return true
    }

    function updateOverview() {
        var free = freeViewportRect()
        var pts = overviewPoints()
        var key = Math.round(width) + "x" + Math.round(height) + ":" + free.x + ":" + free.width
            + ":" + free.height + ":" + perimeterRadius + ":" + bandKey + ":" + sourceSpecKey()
        if (key === overviewKey)
            return
        overviewKey = key
        var k = Math.max(1, finiteNum(perimeterRadius, 35) / 35)
        var lo = specDistance * k
        var d = lo
        // A window too small to hold the hive keeps the farthest sane frame.
        var far = lo * 3
        if (free.width < 1 || free.height < 1)
            d = lo
        else if (!overviewFits(far, pts, free))
            d = far
        else if (!overviewFits(lo, pts, free)) {
            var hi = far
            for (var it = 0; it < 30; it++) {
                var mid = (lo + hi) / 2
                if (overviewFits(mid, pts, free))
                    hi = mid
                else
                    lo = mid
            }
            d = hi
        }
        overviewDistance = d
        if (coreMode || cameraMode === "core" || coreTransitioning)
            return
        if (cameraMode === "overview" || cameraMode === "fit")
            applyOverview()
        else if (cameraMode === "ease") {
            var pose = zoomPose(zoomZ)
            cameraDistance = pose.d
            cameraPitch = pose.pitch
        }
    }

    function easeJoin() {
        return Math.min(easeJoinDistance, overviewDistance)
    }

    // Distance and pitch z notches in from the default frame. Pitch moves
    // linearly with z on the ease, so every notch turns it by the same amount.
    function zoomPose(z) {
        var d0 = overviewDistance
        var j = easeJoin()
        if (z <= 0)
            return { d: d0, pitch: specPitchDeg }
        if (z < easeNotches) {
            var u = z / easeNotches
            return {
                d: d0 * Math.pow(j / d0, u),
                pitch: specPitchDeg + (pitchDeg(j) - specPitchDeg) * u
            }
        }
        var d = j / Math.pow(1.18, z - easeNotches)
        return { d: d, pitch: pitchDeg(d) }
    }

    function zoomZFor(d) {
        var d0 = overviewDistance
        var j = easeJoin()
        if (d <= j)
            return easeNotches + Math.log(j / d) / Math.log(1.18)
        if (d0 <= j)
            return 0
        var u = Math.log(d0 / d) / Math.log(d0 / j)
        return easeNotches * Math.max(0, Math.min(1, u))
    }

    function sourceSpecKey() {
        var specs = sourceLabelSpecs || []
        var key = ""
        for (var i = 0; i < specs.length; i++) {
            var sp = specs[i]
            if (sp)
                key += sp.id + ":" + finiteNum(sp.x) + ":" + finiteNum(sp.y) + ":" + finiteNum(sp.z) + "|"
        }
        return key
    }

    function focusSelectedUnit() {
        var pos = unitPositionOf(selectedUnitId)
        if (!pos)
            return false
        root.snapOutOfCore()
        cameraMode = "follow"
        unitFocused = true
        setCameraTarget(pos.x, pos.y, pos.z)
        cameraDistance = 24.0
        cameraPitch = pitchDeg(cameraDistance)
        return true
    }

    // Fit swarm frames the whole hive like the default view (perimeter and
    // every source), but stays put when a unit is selected.
    function fitSwarm() {
        root.snapOutOfCore()
        cameraMode = "fit"
        unitFocused = false
        applyOverview()
    }

    // The scene runs full bleed under the HUD (chat-off layout). The area the
    // default frame must keep clear: the 2 percent margin, the header text on
    // top, the Dispatch bar at the bottom, and the Inspector dock on the right
    // while a unit is selected. The Units and Events drawers are overlays and
    // never change it, so opening one never moves the camera.
    readonly property real hudHeaderH: 72
    readonly property real hudDispatchH: 48 + 20 + 12
    function freeViewportRect() {
        var w = Math.max(1, width)
        var h = Math.max(1, height)
        var mx = Math.round(w * 0.02)
        var my = Math.round(h * 0.02)
        var left = mx
        var top = my + hudHeaderH
        // Rank 3 dock: margin + 360 width + 16 gap when open.
        var right = w - (showInspector ? (mx + 360 + 16) : mx)
        if (right <= left)
            right = w
        var bottom = Math.max(top + 1, h - my - hudDispatchH)
        return Qt.rect(left, top, right - left, bottom - top)
    }

    function freeViewportShift() {
        var w = Math.max(1, width)
        var h = Math.max(1, height)
        var r = freeViewportRect()
        var cx = r.x + r.width / 2
        var cy = r.y + r.height / 2
        return Qt.vector2d(-(cx - w / 2) / w, (cy - h / 2) / h)
    }

    function lensShiftOffset() {
        return lensShiftFor(cameraDistance, cameraPitch)
    }

    function lensShiftFor(d, pitchDegValue) {
        var sh = freeViewportShift()
        var pitch = pitchDegValue * Math.PI / 180
        var visH = 2 * d * Math.tan(35 * Math.PI / 360)
        var aspect = (height > 1 && width > 1) ? (width / height) : (2110 / 1306)
        var visW = visH * aspect
        return Qt.vector3d(sh.x * visW, sh.y * visH * Math.cos(pitch), -sh.y * visH * Math.sin(pitch))
    }

    function pxAngle() {
        return 0.6306 / Math.max(1, view.height)
    }

    function cameraDirection() {
        var p = cameraPitch * Math.PI / 180
        return Qt.vector3d(0, -Math.sin(p), -Math.cos(p))
    }

    function cameraWorldPos() {
        var d = cameraDistance
        var pitch = cameraPitch * Math.PI / 180
        var sh = lensShiftOffset()
        return Qt.vector3d(
            cameraTargetX + sh.x,
            cameraTargetY + Math.sin(pitch) * d + sh.y,
            cameraTargetZ + Math.cos(pitch) * d + sh.z
        )
    }

    // Qt Quick 3D applies eulerRotation as Z, then X, then Y.
    function eulerRotate(tilt, spinYDeg, local) {
        var rx = tilt.x * Math.PI / 180
        var ry = (tilt.y + spinYDeg) * Math.PI / 180
        var rz = tilt.z * Math.PI / 180
        var x = local.x, y = local.y, z = local.z
        var c = Math.cos(rz), s = Math.sin(rz)
        var x0 = x * c - y * s, y0 = x * s + y * c
        x = x0; y = y0
        c = Math.cos(rx); s = Math.sin(rx)
        var y1 = y * c - z * s, z1 = y * s + z * c
        y = y1; z = z1
        c = Math.cos(ry); s = Math.sin(ry)
        var x2 = x * c + z * s, z2 = -x * s + z * c
        return Qt.vector3d(x2, y, z2)
    }

    function memoryTiltEuler() { return Qt.vector3d(6.62, 0, -28.75) }
    function toolsTiltEuler() { return Qt.vector3d(-0.22, 0, 13.97) }
    function resultsTiltEuler() { return Qt.vector3d(-4.52, 0, 2.86) }

    function ringWorld(tilt, spinYDeg, radius, angle) {
        var local = Qt.vector3d(radius * Math.cos(angle), 0, radius * Math.sin(angle))
        var r = eulerRotate(tilt, spinYDeg, local)
        return Qt.vector3d(root.orbCentre.x + r.x, root.orbCentre.y + r.y, root.orbCentre.z + r.z)
    }

    function updateResultsOrbit() {
        var cap = root.resultsRingAuthored
        var inner = Number.POSITIVE_INFINITY
        var bands = bandSpecs || []
        for (var i = 0; i < bands.length; i++) {
            if (bands[i].caste !== "sanitizer")
                continue
            var lanes = bands[i].lanes || []
            for (var j = 0; j < lanes.length; j++)
                inner = Math.min(inner, finiteNum(lanes[j].r, inner))
        }
        var r = cap
        if (inner !== Number.POSITIVE_INFINITY)
            r = Math.min(cap, inner - 1.0)
        resultsRadius = r
        // Fade the results orbit out under 5.0 m so it does not collide
        // with a tight sanitizer band (about 50 units).
        if (r >= 5.0)
            resultsFade = 1.0
        else if (r <= 4.0)
            resultsFade = 0.0
        else
            resultsFade = (r - 4.0) / 1.0
        rebuildOrbOrnaments()
    }

    function _orbPushTorus(pos, nrm, col, uv, idx, radius, tube, partId) {
        var segs = 128
        var tubeSegs = 10
        var base = pos.length
        var i, j
        for (i = 0; i < segs; i++) {
            var theta = i / segs * Math.PI * 2
            var ct = Math.cos(theta)
            var st = Math.sin(theta)
            for (j = 0; j < tubeSegs; j++) {
                var phi = j / tubeSegs * Math.PI * 2
                var cp = Math.cos(phi)
                var sp = Math.sin(phi)
                var rr = radius + tube * cp
                pos.push(Qt.vector3d(rr * ct, tube * sp, rr * st))
                nrm.push(Qt.vector3d(cp * ct, sp, cp * st))
                col.push(Qt.vector4d(1, 1, 1, partId))
                uv.push(Qt.vector2d(i / segs, 0))
            }
        }
        for (i = 0; i < segs; i++) {
            var i0 = base + i * tubeSegs
            var i1 = base + ((i + 1) % segs) * tubeSegs
            for (j = 0; j < tubeSegs; j++) {
                var j1 = (j + 1) % tubeSegs
                idx.push(i0 + j, i1 + j, i1 + j1)
                idx.push(i0 + j, i1 + j1, i0 + j1)
            }
        }
    }

    function _orbPushSphere(pos, nrm, col, uv, idx, cx, cy, cz, radius, partId) {
        var slices = 8
        var stacks = 6
        var base = pos.length
        var i, j
        for (i = 0; i <= stacks; i++) {
            var v = i / stacks
            var phi = v * Math.PI
            var sp = Math.sin(phi), cp = Math.cos(phi)
            for (j = 0; j <= slices; j++) {
                var u = j / slices
                var th = u * Math.PI * 2
                var ct = Math.cos(th), st = Math.sin(th)
                var nx = sp * ct, ny = cp, nz = sp * st
                pos.push(Qt.vector3d(cx + radius * nx, cy + radius * ny, cz + radius * nz))
                nrm.push(Qt.vector3d(nx, ny, nz))
                col.push(Qt.vector4d(1, 1, 1, partId))
                uv.push(Qt.vector2d(u, 0))
            }
        }
        var stride = slices + 1
        for (i = 0; i < stacks; i++) {
            for (j = 0; j < slices; j++) {
                var a = base + i * stride + j
                var b = a + stride
                idx.push(a, b, a + 1)
                idx.push(a + 1, b, b + 1)
            }
        }
    }

    function rebuildOrbOrnaments() {
        var key = memoryCount + "|" + toolsCount + "|" + resultsRadius.toFixed(3) + "|" + (resultsFade > 0.001 ? "1" : "0")
        if (key === orbOrnamentKey && orbOrnamentPositions && orbOrnamentPositions.length)
            return
        orbOrnamentKey = key
        var pos = [], nrm = [], col = [], uv = [], idx = []
        _orbPushTorus(pos, nrm, col, uv, idx, memoryRingRadius, 0.016, 0)
        _orbPushTorus(pos, nrm, col, uv, idx, toolsRingRadius, 0.020, 1)
        if (resultsFade > 0.001)
            _orbPushTorus(pos, nrm, col, uv, idx, resultsRingAuthored, 0.011, 2)
        var i, a, n
        n = memoryCount
        for (i = 0; i < n; i++) {
            a = memPhase + i * 2 * Math.PI / Math.max(n, 1)
            _orbPushSphere(pos, nrm, col, uv, idx,
                           memoryRingRadius * Math.cos(a), 0, memoryRingRadius * Math.sin(a),
                           memoryBeadRadius, 3)
        }
        n = Math.min(toolsCount, 8)
        for (i = 0; i < n; i++) {
            a = toolPhase + i * 2 * Math.PI / Math.max(toolsCount, 1)
            _orbPushSphere(pos, nrm, col, uv, idx,
                           toolsRingRadius * Math.cos(a), 0, toolsRingRadius * Math.sin(a),
                           toolsBeadRadius, 4)
        }
        orbOrnamentPositions = pos
        orbOrnamentNormals = nrm
        orbOrnamentColors = col
        orbOrnamentUvs = uv
        orbOrnamentIndexes = idx
    }

    function buildStarMesh() {
        if (starPositions && starPositions.length)
            return
        // One ProceduralMesh draw for all three parallax layers. A small
        // LCG (same seed per layer) places the 1,000 stars in the authored
        // ranges; the vertex shader applies starDrift * rate. Built as a
        // mesh instead of an InstanceList so the shader can compile
        // without instancing built-ins.
        function lcg(state) {
            // Numerical Recipes LCG, 32-bit.
            state[0] = (state[0] * 1664525 + 1013904223) >>> 0
            return state[0] / 4294967296
        }
        var pos = []
        var col = []
        var uv0 = []
        var uv1 = []
        var idx = []
        var layers = starLayers
        var base = 0
        var corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]]
        for (var li = 0; li < layers.length; li++) {
            var layer = layers[li]
            var state = [layer.seed >>> 0]
            var from = layer.from, to = layer.to
            for (var i = 0; i < layer.count; i++) {
                var ux = lcg(state), uy = lcg(state), uz = lcg(state), uc = lcg(state), up = lcg(state)
                var ox = from.x + (to.x - from.x) * ux
                var oy = from.y + (to.y - from.y) * uy
                var oz = from.z + (to.z - from.z) * uz
                var r0 = 0xa4 / 255, g0 = 0x73 / 255, b0 = 0xf0 / 255
                var r1 = 0xd2 / 255, g1 = 0xb9 / 255, b1 = 0xf8 / 255
                var tint = Qt.rgba(r0 + (r1 - r0) * uc, g0 + (g1 - g0) * uc, b0 + (b1 - b0) * uc, 1)
                var px = layer.px0 + (layer.px1 - layer.px0) * up
                for (var c = 0; c < 4; c++) {
                    var cx = corners[c][0], cy = corners[c][1]
                    pos.push(Qt.vector3d(ox + cx * 0.01, oy + cy * 0.01, oz))
                    col.push(tint)
                    uv0.push(Qt.vector2d(cx, cy))
                    uv1.push(Qt.vector2d(px, layer.rate))
                }
                idx.push(base, base + 1, base + 2, base, base + 2, base + 3)
                base += 4
            }
        }
        starPositions = pos
        starColors = col
        starUv0s = uv0
        starUv1s = uv1
        starIndexes = idx
    }

    function updateBeadScales() {
        var cam = cameraWorldPos()
        var dir = cameraDirection()
        var ang = pxAngle()
        function pushList(list, radius, minPx) {
            var rows = list || []
            for (var i = 0; i < rows.length; i++) {
                var e = rows[i]
                if (!e)
                    continue
                var w = ringWorld(
                    (list === memoryBeadList.instances || list === liveByKey["__memBeads"]) ? memoryTiltEuler() : toolsTiltEuler(),
                    (list === memoryBeadList.instances || list === liveByKey["__memBeads"]) ? memorySpin : toolsSpin,
                    Math.sqrt(e.position.x * e.position.x + e.position.z * e.position.z),
                    Math.atan2(e.position.z, e.position.x)
                )
                var depth = Math.max((w.x - cam.x) * dir.x + (w.y - cam.y) * dir.y + (w.z - cam.z) * dir.z, 0.1)
                var s = Math.max(radius, minPx * ang * depth)
                e.scale = Qt.vector3d(s, s, s)
                var comp = (radius / s) * (radius / s)
                e.customData = Qt.vector4d(comp, 0, 0, 0)
            }
        }
        pushList(liveByKey["__memBeads"] || [], root.memoryBeadRadius, 2.0)
        pushList(liveByKey["__toolBeads"] || [], root.toolsBeadRadius, 2.5)
    }

    function coreFocusDistance() {
        var free = freeViewportRect()
        return Math.max(15.0, 20.0 * Math.max(1, height) / Math.max(1, free.width))
    }

    function applyCorePose(d) {
        setCameraTarget(root.orbCentre.x, root.orbCentre.y, root.orbCentre.z)
        cameraDistance = d
        cameraPitch = root.coreFocusPitch
    }

    function snapOutOfCore() {
        if (typeof coreEaseAnim !== "undefined")
            coreEaseAnim.stop()
        coreTransitioning = false
        coreEaseIntent = ""
        coreMode = false
        if (cameraMode === "core")
            cameraMode = "follow"
    }

    function finishCoreEase() {
        if (!coreTransitioning)
            return
        coreEaseU = 1
        applyCoreEase(1)
        coreTransitioning = false
        if (typeof coreEaseAnim !== "undefined")
            coreEaseAnim.stop()
        if (coreEaseIntent === "enter") {
            cameraMode = "core"
            coreMode = true
        } else {
            coreMode = false
            cameraMode = "overview"
            applyOverview()
        }
        coreEaseIntent = ""
    }

    function applyCoreEase(u) {
        var aD = coreEaseFromD, bD = coreEaseToD
        if (aD > 0.0001 && bD > 0.0001)
            cameraDistance = aD * Math.pow(bD / aD, u)
        else
            cameraDistance = aD + (bD - aD) * u
        cameraPitch = coreEaseFromPitch + (coreEaseToPitch - coreEaseFromPitch) * u
        cameraTargetX = coreEaseFromX + (coreEaseToX - coreEaseFromX) * u
        cameraTargetY = coreEaseFromY + (coreEaseToY - coreEaseFromY) * u
        cameraTargetZ = coreEaseFromZ + (coreEaseToZ - coreEaseFromZ) * u
    }

    function beginCoreEase(intent, toD, toPitch, toX, toY, toZ, immediate) {
        coreEaseFromD = cameraDistance
        coreEaseFromPitch = cameraPitch
        coreEaseFromX = cameraTargetX
        coreEaseFromY = cameraTargetY
        coreEaseFromZ = cameraTargetZ
        coreEaseToD = toD
        coreEaseToPitch = toPitch
        coreEaseToX = toX
        coreEaseToY = toY
        coreEaseToZ = toZ
        coreEaseIntent = intent
        if (immediate || reducedMotion) {
            applyCoreEase(1)
            coreTransitioning = false
            if (intent === "enter") {
                cameraMode = "core"
                coreMode = true
            } else {
                coreMode = false
                cameraMode = "overview"
                applyOverview()
            }
            coreEaseIntent = ""
            projectOrbLabels()
            return
        }
        coreTransitioning = true
        if (intent === "enter")
            coreMode = true
        coreEaseU = 0
        coreEaseAnim.stop()
        coreEaseAnim.start()
    }

    function enterCoreFocus(immediate) {
        var d = coreFocusDistance()
        unitFocused = false
        beginCoreEase("enter", d, root.coreFocusPitch, root.orbCentre.x, root.orbCentre.y, root.orbCentre.z, !!immediate)
        if (!!immediate)
            applyCorePose(d)
        projectOrbLabels()
        return true
    }

    function exitCoreFocus(immediate) {
        if (!coreMode && cameraMode !== "core" && !coreTransitioning)
            return false
        var s = overviewDistance / specDistance
        beginCoreEase("exit", overviewDistance, specPitchDeg, 0, -6 * s, -3 * s, !!immediate)
        return true
    }

    function orbPickHitsCore(hit) {
        var n = hit
        while (n) {
            if (n.objectName === "hiveCore" || n.objectName === "orbBody"
                    || n.objectName === "orbCore" || n.objectName === "orbNucleus"
                    || n.objectName === "orbFilaments" || n.objectName === "orbShell"
                    || n.objectName === "orbPulseShell" || n.objectName === "memoryTilt"
                    || n.objectName === "toolsTilt" || n.objectName === "resultsTilt"
                    || n.objectName === "orbRingMemory" || n.objectName === "orbRingTools"
                    || n.objectName === "orbRingResults")
                return true
            n = n.parent
        }
        return false
    }

    function rememberUnitPositions(buckets) {
        var next = ({})
        if (!buckets)
            return
        var keys = Object.keys(buckets)
        for (var i = 0; i < keys.length; i++) {
            var rows = buckets[keys[i]] || []
            for (var r = 0; r < rows.length; r++) {
                var row = rows[r]
                if (row && row.unit_id) {
                    var pos = readRowPos(row)
                    if (pos)
                        next[row.unit_id] = pos
                }
            }
        }
        unitPositions = next
        syncCameraTargetFromSelection()
    }

    function _bucketize(units) {
        var buckets = {}
        var ci, lod
        for (ci = 0; ci < casteIds.length; ci++) {
            for (lod = 0; lod < 3; lod++)
                buckets[casteIds[ci] + ":" + lod] = []
        }
        for (var i = 0; i < units.length; i++) {
            var u = units[i]
            var caste = (u.caste || "warden").toLowerCase()
            if (casteIds.indexOf(caste) < 0)
                caste = "warden"
            lod = u.lod === undefined ? 1 : Math.max(0, Math.min(2, u.lod))
            var pos = u.position || [u.x || 0, u.y || 0, u.z || 0]
            var vel = u.velocity || [u.vx || 0, u.vy || 0, u.vz || 0]
            buckets[caste + ":" + lod].push({
                unit_id: u.unit_id || "",
                x: pos[0], y: pos[1], z: pos.length > 2 ? pos[2] : 0,
                vx: vel[0] || 0, vy: vel[1] || 0, vz: vel.length > 2 ? (vel[2] || 0) : 0,
                heading_deg: u.heading_deg || 0,
                scale: u.scale === undefined ? 0.36 : u.scale,
                color: casteColors[caste],
                phase: u.phase || i * 1.7,
                claw: u.claw || 0.45,
                limp: u.limp || 0,
                speed: (u.speed === undefined || u.speed === null) ? 1.0 : u.speed
            })
        }
        return buckets
    }

    function acquireEntry() {
        var pool = entryPool || []
        if (pool.length > 0) {
            var reused = pool.pop()
            entryPool = pool
            return reused
        }
        return Qt.createQmlObject("import QtQuick3D; InstanceListEntry {}", root)
    }

    function releaseEntry(entry) {
        if (!entry)
            return
        entry.scale = Qt.vector3d(0, 0, 0)
        var pool = entryPool || []
        pool.push(entry)
        entryPool = pool
    }

    function releaseList(key, lst) {
        var old = (liveByKey && liveByKey[key]) ? liveByKey[key] : []
        if (liveByKey)
            liveByKey[key] = []
        if (lst)
            lst.instances = []
        for (var i = 0; i < old.length; i++)
            releaseEntry(old[i])
    }

    function releaseAllLists() {
        ensureLists()
        var keys = Object.keys(lists)
        for (var i = 0; i < keys.length; i++)
            releaseList(keys[i], lists[keys[i]])
        releaseList("__particles", particleList)
        releaseList("__conduits", conduitList)
        releaseList("__sources", sourceList)
        releaseList("__memBeads", memoryBeadList)
        releaseList("__toolBeads", toolBeadList)
        releaseList("__tentacle_0", tentacleLists["0"])
        releaseList("__tentacle_1", tentacleLists["1"])
        releaseList("__tentacle_2", tentacleLists["2"])
        conduitSpecs = []
        unitAnimSpecs = []
        unitOrbitSpecs = []
        orbitEntries = ({})
    }

    function finiteNum(v, fallback) {
        var n = Number(v)
        var fb = (fallback === undefined) ? 0 : fallback
        if (n !== n || n === Infinity || n === -Infinity)
            return fb
        return n
    }

    function finiteCoord(v, fallback) {
        var n = finiteNum(v, fallback)
        var fb = (fallback === undefined) ? 0 : fallback
        if (Math.abs(n) > 48)
            return fb
        return n
    }

    function fillUnitEntry(row, caste, key, recs) {
        var e = acquireEntry()
        e.position = Qt.vector3d(finiteCoord(row.x), finiteCoord(row.y), finiteCoord(row.z))
        e.eulerRotation = Qt.vector3d(0, -finiteNum(row.heading_deg), 0)
        var sc = finiteNum(row.scale, 1.0)
        if (sc < 0.20)
            sc = 0.20
        if (sc > 3.0)
            sc = 3.0
        e.scale = Qt.vector3d(sc, sc, sc)
        // Qt multiplies COLOR by the instance colour and BASE_COLOR by COLOR: keep it white (fix-c05bb78 #1).
        e.color = "#ffffff"
        var uid = row && row.unit_id ? row.unit_id : ""
        var rs = reachSlot(uid, row.reach)
        var dim = finiteNum(row.dim, 1.0)
        if (dim <= 0)
            dim = 1.0
        // INSTANCE_DATA = (eye colour rgb linear, eyeMul); rim and seam use the eye colour too.
        e.customData = eyeData(row.eye || row.color || casteColors[caste], finiteNum(row.eyeMul, 1.0))
        if (uid && recs) {
            if (!recs[uid] || String(key).indexOf(":head") >= 0) {
                recs[uid] = {
                    unit_id: uid,
                    caste: caste,
                    modelKey: key || "",
                    index: finiteNum(row.index, 0),
                    x: e.position.x,
                    y: e.position.y,
                    z: e.position.z,
                    scale: sc,
                    color: row.color || casteColors[caste],
                    eye: row.eye || casteColors[caste],
                    heading: -finiteNum(row.heading_deg),
                    dim: dim
                }
            }
        }
        return e
    }

    function applyGlyphTrails(trails) {
        var list = trails || []
        var key = ""
        var births = ({})
        for (var i = 0; i < list.length; i++) {
            var tr = list[i]
            key += String(tr.id) + "|"
            var had = glyphTrailBirth[tr.id]
            births[tr.id] = (had !== undefined) ? had : sceneTime - finiteNum(tr.age_s, 0)
        }
        glyphTrailBirth = births
        if (key === glyphTrailKey && glyphList !== null)
            return
        glyphTrailKey = key
        if (glyphList === null)
            glyphList = Qt.createQmlObject("import QtQuick3D; InstanceList {}", root)
        releaseList("__glyphs", glyphList)
        var entries = []
        for (var ti = 0; ti < list.length; ti++) {
            var t = list[ti]
            var lanes = t.lanes || []
            for (var li = 0; li < lanes.length && li < 2; li++) {
                var text = String(lanes[li] || "")
                for (var ci = 0; ci < text.length && ci < 60; ci++) {
                    var code = text.charCodeAt(ci)
                    if (code < 33 || code > 126)
                        continue
                    var e = acquireEntry()
                    e.position = Qt.vector3d(finiteCoord(t.x), finiteNum(t.y), finiteCoord(t.z))
                    e.eulerRotation = Qt.vector3d(0, 0, 0)
                    e.scale = Qt.vector3d(1, 1, 1)
                    e.color = t.color
                    e.customData = Qt.vector4d(ci, births[t.id], code - 32, li + 2 * Math.min(text.length, 60))
                    entries.push(e)
                }
            }
        }
        glyphList.instances = entries
        liveByKey["__glyphs"] = entries
        glyphCount = entries.length
    }

    function bandPoint(band, lane, theta) {
        // Spec space is +Z up: Rx(tilt_x) * Ry(tilt_y), lift by height, draw at (x, z, -y).
        var x = Math.cos(theta) * lane.r
        var y = Math.sin(theta) * lane.r
        var z = lane.z
        var cy = Math.cos(band.tilt_y), sy = Math.sin(band.tilt_y)
        var x1 = x * cy + z * sy
        var z1 = -x * sy + z * cy
        var cx = Math.cos(band.tilt_x), sx = Math.sin(band.tilt_x)
        var y2 = y * cx - z1 * sx
        var z2 = y * sx + z1 * cx
        return Qt.vector3d(x1, z2 + band.height, -y2)
    }

    function applyBands(bands, perimeter) {
        var list = bands || []
        var key = String(finiteNum(perimeter, 35)) + "|core:" + root.laneCoreMul
        for (var i = 0; i < list.length; i++) {
            var lanes = list[i].lanes || []
            for (var li = 0; li < lanes.length; li++)
                key += "|" + list[i].caste + ":" + lanes[li].r
        }
        bandSpecs = list
        perimeterRadius = finiteNum(perimeter, 35)
        root.updateResultsOrbit()
        if (key === bandKey)
            return
        bandKey = key
        // All lane guides in one line mesh with per-vertex caste colour:
        // edge lanes brighter than middle lanes.
        var pos = []
        var col = []
        var segs = 128
        for (var bi = 0; bi < list.length; bi++) {
            var band = list[bi]
            var c = Qt.color(casteColors[band.caste] || casteColors.warden)
            var bl = band.lanes || []
            for (var lj = 0; lj < bl.length; lj++) {
                var edge = (lj === 0 || lj === bl.length - 1)
                var k = (edge ? root.laneEdgeEmission : root.laneMidEmission) * root.laneCoreMul
                // Vertex colours reach the shader as linear light, so convert
                // the sRGB target (caste colour times k) or the guides render
                // at about twice the intended brightness.
                var cv = Qt.vector4d(Math.pow(c.r * k, 2.2), Math.pow(c.g * k, 2.2),
                                     Math.pow(c.b * k, 2.2), 1.0)
                var prev = bandPoint(band, bl[lj], 0)
                for (var sI = 1; sI <= segs; sI++) {
                    var next = bandPoint(band, bl[lj], sI * 2 * Math.PI / segs)
                    pos.push(prev, next)
                    col.push(cv, cv)
                    prev = next
                }
            }
        }
        bandGuideColors = col
        bandGuidePositions = pos
    }

    function reachSlot(uid, reach) {
        var n = Math.max(0, Math.min(3, Math.floor(finiteNum(reach, 0))))
        if (!uid)
            return { n: n, prev: n, t: -10 }
        var done = reachNext[uid]
        if (done)
            return done
        var old = reachState[uid]
        var st
        if (!old)
            st = { n: n, prev: 0, t: n > 0 ? sceneTime : -10 }
        else if (old.n !== n)
            st = { n: n, prev: old.n, t: sceneTime }
        else
            st = old
        reachNext[uid] = st
        return st
    }

    function linearVec(hex) {
        var c = Qt.color(hex)
        return Qt.vector3d(Math.pow(c.r, 2.2), Math.pow(c.g, 2.2), Math.pow(c.b, 2.2))
    }

    function blenderTilt(tx, ty) {
        // BAND-SPEC Rx(tx)*Ry(ty) in Blender axes (Y first). Blender Y is Qt -Z.
        // Qt Quick 3D applies eulerRotation as z, then x, then y.
        return Qt.vector3d(tx * 180 / Math.PI, 0, -ty * 180 / Math.PI)
    }

    function applyOrb(orb) {
        memoryCount = Math.max(0, Math.floor(finiteNum(orb.memoryCount, 0)))
        memoryLabel = orb.memoryLabel || ("Memory · " + memoryCount + " from last chat")
        toolsCount = Math.max(0, Math.floor(finiteNum(orb.toolsCount, 0)))
        toolsLabel = orb.toolsLabel || ("Tools " + toolsCount + " running")
        var arc = orb.toolsLitArc
        if (arc && arc.length >= 3)
            toolsLitArc = Qt.vector3d(finiteNum(arc[0], 0), finiteNum(arc[1], 0), finiteNum(arc[2], 2))
        else
            toolsLitArc = Qt.vector3d(0, 0, 2)
        orbEnergy = finiteNum(orb.energy, 0.3)
        if (orbEnergy < 0.3)
            orbEnergy = 0.3
        if (orbEnergy > 1.0)
            orbEnergy = 1.0
        var tools = []
        var src = orb.tools || []
        for (var ti = 0; ti < src.length; ti++) {
            if (typeof src[ti] === "string")
                tools.push({ id: src[ti] })
            else if (src[ti])
                tools.push({ id: String(src[ti].id || src[ti].name || ("tool-" + ti)) })
        }
        orbTools = tools
        var results = []
        var rs = orb.results || []
        for (var ri = 0; ri < rs.length; ri++) {
            if (rs[ri])
                results.push(String(rs[ri]))
        }
        orbResults = results
        root.updateResultsOrbit()
    }

    function fillSourceEntries(rows) {
        ensureLists()
        releaseList("__sources", sourceList)
        var entries = []
        for (var i = 0; i < (rows || []).length; i++) {
            var row = rows[i]
            var e = acquireEntry()
            e.position = Qt.vector3d(finiteNum(row.x), finiteNum(row.y), finiteNum(row.z))
            e.eulerRotation = Qt.vector3d(0, 0, 0)
            var sc = finiteNum(row.scale, 1.0)
            e.scale = Qt.vector3d(sc, sc, sc)
            e.color = row.color || "#8fd3ff"
            e.customData = Qt.vector4d(finiteNum(row.lit, 0.15), finiteNum(row.open, 0), 0, i)
            entries.push(e)
        }
        sourceList.instances = entries
        liveByKey["__sources"] = entries
    }

    function fillBeadEntries() {
        ensureLists()
        releaseList("__memBeads", memoryBeadList)
        releaseList("__toolBeads", toolBeadList)
        var mem = [], tools = []
        var memR = root.memoryRingRadius, toolR = root.toolsRingRadius
        var i
        for (i = 0; i < memoryCount; i++) {
            var a = root.memPhase + i * 2 * Math.PI / Math.max(memoryCount, 1)
            var e = acquireEntry()
            e.position = Qt.vector3d(memR * Math.cos(a), 0, memR * Math.sin(a))
            var s = root.memoryBeadRadius
            e.scale = Qt.vector3d(s, s, s)
            e.color = "#d2b9f8"
            e.customData = Qt.vector4d(1, 0, 0, 0)
            mem.push(e)
        }
        for (i = 0; i < Math.min(toolsCount, 8); i++) {
            var b = root.toolPhase + i * 2 * Math.PI / Math.max(toolsCount, 1)
            var f = acquireEntry()
            f.position = Qt.vector3d(toolR * Math.cos(b), 0, toolR * Math.sin(b))
            var ts = root.toolsBeadRadius
            f.scale = Qt.vector3d(ts, ts, ts)
            f.color = "#ffffff"
            f.customData = Qt.vector4d(1, 0, 0, 0)
            tools.push(f)
        }
        memoryBeadList.instances = mem
        toolBeadList.instances = tools
        liveByKey["__memBeads"] = mem
        liveByKey["__toolBeads"] = tools
        root.updateBeadScales()
    }

    function eyeData(color, eyeMul) {
        var c = Qt.color(color)
        return Qt.vector4d(Math.pow(c.r, 2.2), Math.pow(c.g, 2.2), Math.pow(c.b, 2.2), finiteNum(eyeMul, 1.0))
    }

    function casteData(caste, eyeMul) {
        var c = Qt.color(casteColors[caste] || casteColors.warden)
        return Qt.vector4d(Math.pow(c.r, 2.2), Math.pow(c.g, 2.2), Math.pow(c.b, 2.2), finiteNum(eyeMul, 1.0))
    }

    function fillTentacleEntries(recs) {
        ensureLists()
        var buckets = { "0": [], "1": [], "2": [] }
        var recKeys = recs ? Object.keys(recs) : []
        for (var i = 0; i < recKeys.length; i++) {
            var rec = recs[recKeys[i]]
            if (!rec || String(rec.modelKey).indexOf(":head") < 0)
                continue
            var lod = 2
            if (String(rec.modelKey).indexOf(":0:") >= 0)
                lod = 0
            else if (String(rec.modelKey).indexOf(":1:") >= 0)
                lod = 1
            var idx = Math.floor(finiteNum(rec.index, -1) + 0.5)
            if (idx < 0)
                continue
            var extra = tentacleUnitState[rec.unit_id] || ({})
            var dim = finiteNum(extra.eyeMul, finiteNum(rec.dim, 1.0))
            if (extra.wLimp > 0.5)
                dim = 0.35
            var color = rec.color || casteColors[rec.caste]
            var c = Qt.color(color)
            var n = strandsByLod[lod]
            for (var slot = 0; slot < n; slot++) {
                var e = acquireEntry()
                e.position = Qt.vector3d(0, 0, 0)
                e.eulerRotation = Qt.vector3d(0, 0, 0)
                e.scale = Qt.vector3d(1, 1, 1)
                // White instance colour (fix #1); dim rides in INSTANCE_DATA.w, caste in unitTex T7.yzw.
                e.color = "#ffffff"
                e.customData = Qt.vector4d(idx, slot, lod, dim)
                buckets[String(lod)].push(e)
            }
        }
        var counts = ({})
        var kinds = ["0", "1", "2"]
        for (var ci = 0; ci < kinds.length; ci++) {
            var key = kinds[ci]
            releaseList("__tentacle_" + key, tentacleLists[key])
            tentacleLists[key].instances = buckets[key]
            liveByKey["__tentacle_" + key] = buckets[key]
            counts[key] = buckets[key].length
        }
        tentacleCounts = counts
    }

    function qFromYaw(deg) {
        var a = finiteNum(deg, 0) * Math.PI / 360.0
        return Qt.vector4d(0, Math.sin(a), 0, Math.cos(a))
    }

    function qrot(q, v) {
        var cx = q.y * v.z - q.z * v.y
        var cy = q.z * v.x - q.x * v.z
        var cz = q.x * v.y - q.y * v.x
        var dx = cx + q.w * v.x, dy = cy + q.w * v.y, dz = cz + q.w * v.z
        return Qt.vector3d(
            v.x + 2.0 * (q.y * dz - q.z * dy),
            v.y + 2.0 * (q.z * dx - q.x * dz),
            v.z + 2.0 * (q.x * dy - q.y * dx)
        )
    }

    function qinv(q) {
        return Qt.vector4d(-q.x, -q.y, -q.z, q.w)
    }

    function worldToLocal(world, pos, q, scale) {
        var d = Qt.vector3d(world.x - pos.x, world.y - pos.y, world.z - pos.z)
        var loc = qrot(qinv(q), d)
        var s = Math.max(scale, 1e-4)
        return Qt.vector3d(loc.x / s, loc.y / s, loc.z / s)
    }

    function inOutCubic(t) {
        t = Math.max(0, Math.min(1, t))
        return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
    }

    function easeToward(cur, target, dt, duration) {
        if (duration <= 1e-4)
            return target
        var k = Math.min(1, dt / duration)
        k = inOutCubic(k)
        return cur + (target - cur) * k
    }

    function stepTentacleWeights(dt) {
        var st = tentacleUnitState || ({})
        var keys = Object.keys(st)
        for (var i = 0; i < keys.length; i++) {
            var s = st[keys[i]]
            if (!s)
                continue
            var state = String(s.state || "").toUpperCase()
            var speed = finiteNum(s.speed, 0.55)
            var fetching = s.open_fetches > 0 || state.indexOf("ENGAGED_HARVEST") >= 0
            var defense = state.indexOf("ENGAGED_DEFENSE") >= 0
            var sanitize = state.indexOf("ENGAGED_SANITIZE") >= 0
            var emp = s.limp || state.indexOf("EMP") >= 0 || state.indexOf("HALT") >= 0
            var docked = state.indexOf("DOCKED") >= 0
            var returning = state.indexOf("RETURNING") >= 0
            var mode = "cruise"
            var tIdle = 0, tReach = 0, tHold = 0, tCoil = 0, tLimp = 0
            if (emp)
                mode = "limp", tLimp = 1
            else if (defense)
                mode = "strike"
            else if (sanitize)
                mode = "sanitize", tHold = 1
            else if (s.grabClock >= 0)
                mode = "grab"
            else if (fetching && s.target)
                mode = "reach", tReach = 1
            else if (returning || s.wCoil > 0.2)
                mode = "carry", tCoil = 1
            else if (docked || speed < 0.2)
                mode = "idle", tIdle = 1
            else if (fetching && !s.target)
                mode = "idle", tIdle = 0.6
            if (mode !== s.mode) {
                s.time0 = sceneTime
                s.mode = mode
                if (mode === "grab")
                    s.grabClock = 0
                if (mode === "strike")
                    s.strikeClock = 0
            }
            // Detect a fetch closing: start the grab / coil choreography.
            if (!emp && s.prevFetches > 0 && s.open_fetches <= 0 && s.grabClock < 0 && (s.wReach > 0.2 || fetching || returning)) {
                s.grabClock = 0
                s.mode = "grab"
                s.time0 = sceneTime
            }
            s.prevFetches = s.open_fetches
            if (s.grabClock >= 0) {
                s.grabClock += dt
                var g = s.grabClock
                // SPEC: close claws 0.25 s, hold 0.6 s, coil from +0.3 s over 0.7 s.
                // Release hook arms once coil reaches 0.3 (section 6 contact fix).
                s.clawOpenArm = (g < 0.25) ? (0.75 - 0.70 * Math.min(1, g / 0.25)) : 0.05
                tHold = (g < 0.25) ? 0 : ((g < 0.85) ? inOutCubic((g - 0.25) / 0.6) : 1)
                tCoil = (g < 0.3) ? 0 : inOutCubic(Math.min(1, (g - 0.3) / 0.7))
                if (tCoil > 0.3)
                    tHold = Math.min(tHold, Math.max(0, 1 - (tCoil - 0.3) / 0.4))
                if (g > 2.0 && returning)
                    tHold = 0, tCoil = 1
                if (g > 4.5)
                    s.grabClock = -1, tCoil = 0, tHold = 0
            }
            if (mode === "strike") {
                s.strikeClock = finiteNum(s.strikeClock, 0) + dt
                var cyc = s.strikeClock % 1.4
                if (cyc < 0.35)
                    s.wStrike = -inOutCubic(cyc / 0.35)
                else if (cyc < 0.53)
                    s.wStrike = Math.min(1, 1 - Math.pow(2, -10 * (cyc - 0.35) / 0.18))
                else if (cyc < 0.78)
                    s.wStrike = 1
                else
                    s.wStrike = 1 - inOutCubic((cyc - 0.78) / 0.62)
                s.clawOpen = 0.85
            } else {
                s.wStrike = easeToward(finiteNum(s.wStrike, 0), 0, dt, 0.4)
                s.clawOpen = easeToward(finiteNum(s.clawOpen, 0.10), 0.10, dt, 0.3)
            }
            s.wIdle = easeToward(finiteNum(s.wIdle, 0), tIdle, dt, 0.8)
            s.wReach = easeToward(finiteNum(s.wReach, 0), tReach, dt, 0.9)
            s.wHold = easeToward(finiteNum(s.wHold, 0), tHold, dt, 0.4)
            s.wCoil = easeToward(finiteNum(s.wCoil, 0), tCoil, dt, 0.5)
            s.wLimp = easeToward(finiteNum(s.wLimp, 0), tLimp, dt, tLimp > 0.5 ? 1.2 : 0.8)
            if (mode === "reach")
                s.clawOpenArm = easeToward(finiteNum(s.clawOpenArm, 0.10), 0.75, dt, 0.4)
            else if (s.grabClock < 0)
                s.clawOpenArm = easeToward(finiteNum(s.clawOpenArm, 0.10), 0.10, dt, 0.4)
            st[keys[i]] = s
        }
        tentacleUnitState = st
    }

    // Per-frame unit poses for the unit texture (Pass E).
    function unitTexRows() {
        var out = []
        var recs = instanceRecords || ({})
        var keys = Object.keys(recs)
        for (var i = 0; i < keys.length; i++) {
            var rec = recs[keys[i]]
            if (!rec || String(rec.modelKey).indexOf(":head") < 0)
                continue
            var pos = unitPositionOf(rec.unit_id) || { x: rec.x, y: rec.y, z: rec.z }
            var yaw = rec.heading
            var os = orbitEntries ? orbitEntries[rec.unit_id] : null
            if (os && os.entries.length)
                yaw = os.entries[0].eulerRotation.y
            var extra = tentacleUnitState[rec.unit_id] || ({})
            var q = qFromYaw(yaw)
            var targetL = Qt.vector3d(2.45, 0, 0)
            if (extra.target && extra.target.length >= 3)
                targetL = worldToLocal(
                    Qt.vector3d(extra.target[0], extra.target[1], extra.target[2]),
                    Qt.vector3d(pos.x, pos.y, pos.z), q, rec.scale
                )
            var holdL = Qt.vector3d(1.05, -0.72, 0)
            var wCoil = finiteNum(extra.wCoil, 0)
            // Raise wPart so the bundle parts earlier (SPEC section 6, wCoil 0.2 contact).
            var wPart = Math.min(1.0, 8.0 * wCoil * (1.0 - wCoil) + 0.35 * Math.min(1, wCoil / 0.2))
            out.push({
                index: Math.floor(finiteNum(rec.index, extra.index) + 0.5),
                x: pos.x, y: pos.y, z: pos.z,
                scale: rec.scale,
                qx: q.x, qy: q.y, qz: q.z, qw: q.w,
                speed: finiteNum(extra.speed, 0.55),
                kappa: finiteNum(extra.kappa, 0),
                phase: finiteNum(extra.phase, 0),
                lenMul: finiteNum(extra.lenMul, 1.0),
                wIdle: finiteNum(extra.wIdle, 0),
                wReach: finiteNum(extra.wReach, 0),
                wHold: finiteNum(extra.wHold, 0),
                wCoil: wCoil,
                wStrike: finiteNum(extra.wStrike, 0),
                wLimp: finiteNum(extra.wLimp, 0),
                clawOpen: finiteNum(extra.clawOpen, 0.10),
                clawOpenArm: finiteNum(extra.clawOpenArm, 0.10),
                txx: targetL.x, txy: targetL.y, txz: targetL.z, wPart: wPart,
                hx: holdL.x, hy: holdL.y, hz: holdL.z,
                time0: finiteNum(extra.time0, 0),
                kHold: finiteNum(extra.kHold, 0.4),
                casteLin: eyeData(rec.color || casteColors[rec.caste], 1.0)
            })
        }
        return out
    }

    property var tentacleUnitState: ({})

    function refreshUnitTex() {
        if (!unitTexData)
            return
        var rows = unitTexRows()
        var flat = []
        // Pre-size 128 * 32 with zeros, then write each unit into its index row.
        for (var z = 0; z < 128 * 32; z++)
            flat.push(0)
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i]
            var idx = r.index
            if (idx < 0 || idx >= 128)
                continue
            var o = idx * 32
            flat[o+0] = r.x; flat[o+1] = r.y; flat[o+2] = r.z; flat[o+3] = r.scale
            flat[o+4] = r.qx; flat[o+5] = r.qy; flat[o+6] = r.qz; flat[o+7] = r.qw
            flat[o+8] = r.speed; flat[o+9] = r.kappa; flat[o+10] = r.phase; flat[o+11] = r.lenMul
            flat[o+12] = r.wIdle; flat[o+13] = r.wReach; flat[o+14] = r.wHold; flat[o+15] = r.wCoil
            flat[o+16] = r.wStrike; flat[o+17] = r.wLimp; flat[o+18] = r.clawOpen; flat[o+19] = r.clawOpenArm
            flat[o+20] = r.txx; flat[o+21] = r.txy; flat[o+22] = r.txz; flat[o+23] = r.wPart
            flat[o+24] = r.hx; flat[o+25] = r.hy; flat[o+26] = r.hz; flat[o+27] = r.time0
            flat[o+28] = r.kHold; flat[o+29] = r.casteLin.x; flat[o+30] = r.casteLin.y; flat[o+31] = r.casteLin.z
        }
        unitTexData.refreshFlat(flat)
    }

    function refreshCurves() {
        // Kept as a synonym so older call sites still compile; Pass E writes unitTex.
        refreshUnitTex()
    }

    function recountEntries(live) {
        liveEntryCount = live
        pooledEntryCount = entryPool ? entryPool.length : 0
        totalEntryCount = liveEntryCount + pooledEntryCount
    }

    function applyWheel(notches) {
        if (coreMode || cameraMode === "core" || (coreTransitioning && coreEaseIntent === "enter")) {
            if (coreTransitioning && coreEaseIntent === "enter")
                root.finishCoreEase()
            var step = Math.pow(1.18, -notches)
            var next = cameraDistance * step
            if (next > root.coreFocusMaxDistance) {
                // Wheel out past 24 m: leave core and let the overview ease take over.
                root.snapOutOfCore()
                zoomZ = zoomZFor(cameraDistance)
                // Fall through to the normal wheel path below.
            } else {
                cameraDistance = Math.max(root.coreFocusMinDistance, Math.min(root.coreFocusMaxDistance, next))
                cameraPitch = root.coreFocusPitch
                cameraMode = "core"
                coreMode = true
                setCameraTarget(root.orbCentre.x, root.orbCentre.y, root.orbCentre.z)
                projectOrbLabels()
                return cameraDistance
            }
        }
        var home = cameraMode === "overview" || cameraMode === "fit"
        var z0 = home ? 0 : zoomZ
        if (!home && Math.abs(zoomPose(z0).d - cameraDistance) > 1e-4)
            z0 = zoomZFor(cameraDistance)
        var n = easeNotches
        var zmax = n + Math.log(easeJoin() / (6 * 0.92)) / Math.log(1.18)
        var z1 = Math.max(0, Math.min(zmax, z0 - notches))
        var pos = unitPositionOf(selectedUnitId)
        if (z1 <= 0) {
            // Back out to the default frame; a selected unit is kept, not followed.
            zoomZ = 0
            cameraMode = pos ? "fit" : "overview"
            applyOverview()
            return cameraDistance
        }
        var pose = zoomPose(z1)
        var old = cameraDistance
        var u0 = Math.min(1, z0 / n)
        var u1 = Math.min(1, z1 / n)
        if (u0 < 1 || u1 < 1) {
            // On the ease the target slides between the default frame's look
            // point and the hive (or the selected unit) in step with the zoom.
            var s = overviewDistance / specDistance
            var hx = 0, hy = -6 * s, hz = -3 * s
            var bx = pos ? pos.x : 0, by = pos ? pos.y : 0, bz = pos ? pos.z : 0
            if (u1 > u0) {
                var fin = u0 >= 1 ? 1 : (1 - u1) / (1 - u0)
                setCameraTarget(bx + (cameraTargetX - bx) * fin, by + (cameraTargetY - by) * fin,
                    bz + (cameraTargetZ - bz) * fin)
            } else if (u1 < u0) {
                var fout = u1 / u0
                setCameraTarget(hx + (cameraTargetX - hx) * fout, hy + (cameraTargetY - hy) * fout,
                    hz + (cameraTargetZ - hz) * fout)
            }
            cameraMode = u1 < 1 ? "ease" : "follow"
        } else {
            cameraMode = "follow"
            if (wheelPivotLive && old) {
                var k = pose.d / old
                setCameraTarget(
                    wheelPivotX + (cameraTargetX - wheelPivotX) * k,
                    wheelPivotY + (cameraTargetY - wheelPivotY) * k,
                    wheelPivotZ + (cameraTargetZ - wheelPivotZ) * k
                )
            } else {
                syncCameraTargetFromSelection()
            }
        }
        zoomZ = z1
        cameraDistance = pose.d
        cameraPitch = pose.pitch
        return cameraDistance
    }

    function ensureLists() {
        if (particleList === null) {
            particleList = Qt.createQmlObject("import QtQuick3D; InstanceList {}", root)
        }
        if (conduitList === null) {
            conduitList = Qt.createQmlObject("import QtQuick3D; InstanceList {}", root)
        }
        if (descriptors.length)
            return
        var desc = []
        var next = ({})
        for (var ci = 0; ci < casteIds.length; ci++) {
            for (var lod = 0; lod < 3; lod++) {
                var key = casteIds[ci] + ":" + lod + ":head"
                next[key] = Qt.createQmlObject("import QtQuick3D; InstanceList {}", root)
                desc.push({
                    key: key,
                    caste: casteIds[ci],
                    lod: lod,
                    part: "head",
                    source: "meshes/sentinel_head_lod" + lod + "_mesh.mesh"
                })
            }
        }
        lists = next
        descriptors = desc
        var mdesc = []
        var mlists = ({
            "0": mergedHead0List,
            "1": mergedHead1List,
            "2": mergedHead2List
        })
        for (var mlod = 0; mlod < 3; mlod++) {
            mdesc.push({
                key: String(mlod),
                lod: mlod,
                part: "head",
                source: "meshes/sentinel_head_lod" + mlod + "_mesh.mesh"
            })
        }
        mergedLists = mlists
        mergedDescriptors = mdesc
    }

    function mergeUnitDraws() {
        // One instanced draw per lod, across every caste. Eyes and seams
        // live in the head mesh; only the instance colour changes.
        var mc = ({})
        var used = 0
        var mkeys = Object.keys(mergedLists)
        for (var i = 0; i < mkeys.length; i++) {
            var mkey = mkeys[i]
            var entries = []
            for (var ci = 0; ci < casteIds.length; ci++) {
                var ck = casteIds[ci] + ":" + mkey + ":head"
                var insts = (lists[ck] && lists[ck].instances) ? lists[ck].instances : []
                for (var j = 0; j < insts.length; j++)
                    entries.push(insts[j])
            }
            mergedLists[mkey].instances = entries
            mc[mkey] = entries.length
            if (entries.length > 0)
                used += 1
        }
        mergedCounts = mc
        return used
    }

    function setParticles(rows) {
        ensureLists()
        if (!particleList)
            return
        releaseList("__particles", particleList)
        var entries = []
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i]
            var vis = row.visible
            if (vis === undefined || vis === null)
                vis = 1
            if (vis <= 0)
                continue
            var e = acquireEntry()
            e.position = Qt.vector3d(finiteCoord(row.x), finiteCoord(row.y), finiteCoord(row.z))
            var sc = vis
            if (sc > 1)
                sc = 1
            e.scale = Qt.vector3d(sc, sc, sc)
            e.color = "#d9ccff"
            entries.push(e)
        }
        particleList.instances = entries
        liveByKey["__particles"] = entries
        var nextCounts = ({})
        var src = liveCounts || ({})
        var ckeys = Object.keys(src)
        for (var ci = 0; ci < ckeys.length; ci++)
            nextCounts[ckeys[ci]] = src[ckeys[ci]]
        nextCounts["__particles"] = entries.length
        liveCounts = nextCounts
        recountEntries(liveEntryCountFromLists())
    }

    function evalConduitSpec(spec, tSec) {
        var kind = spec.kind || "packet"
        var phase = finiteNum(spec.phase, 0)
        var baseSc = finiteNum(spec.scale, 0.75)
        var sx = finiteCoord(spec.sx, 0)
        var sy = finiteCoord(spec.sy, 0)
        var sz = finiteCoord(spec.sz, 0)
        if (kind === "node") {
            var nsc = baseSc * (0.88 + 0.22 * Math.sin(tSec * 3.2 + phase * 6.2831853))
            return { x: sx, y: sy, z: sz, scale: Math.max(0.15, Math.min(2.5, nsc)) }
        }
        var speed = finiteNum(spec.speed, 0.75)
        var t = (phase + tSec * speed) % 1.0
        if (t < 0)
            t += 1.0
        var u = 1.0 - t
        var cx = finiteCoord(spec.cx, sx * 0.5)
        var cy = finiteCoord(spec.cy, Math.max(sy, 0.5) + 1.4)
        var cz = finiteCoord(spec.cz, sz * 0.5)
        var ex = finiteCoord(spec.ex, 0)
        var ey = finiteCoord(spec.ey, 0)
        var ez = finiteCoord(spec.ez, 0)
        var px = u * u * sx + 2.0 * u * t * cx + t * t * ex
        var py = u * u * sy + 2.0 * u * t * cy + t * t * ey
        var pz = u * u * sz + 2.0 * u * t * cz + t * t * ez
        var pulse = 0.65 + 0.55 * Math.sin(t * Math.PI)
        var psc = Math.max(0.15, Math.min(2.2, baseSc * pulse))
        return { x: px, y: py, z: pz, scale: psc }
    }

    function fillConduitEntries(specs) {
        ensureLists()
        if (!conduitList || !specs || !specs.length) {
            conduitSpecs = []
            if (conduitList)
                conduitList.instances = []
            liveByKey["__conduits"] = []
            return []
        }
        var entries = []
        var cleanSpecs = []
        var tSec = finiteNum(sceneTime, 0)
        for (var i = 0; i < specs.length; i++) {
            var sp = specs[i]
            if (!sp)
                continue
            var e = acquireEntry()
            var st = evalConduitSpec(sp, tSec)
            var psc = st.scale * 0.0022
            e.position = Qt.vector3d(st.x, st.y, st.z)
            e.scale = Qt.vector3d(psc, psc, psc)
            e.color = sp.color || "#38bdf8"
            entries.push(e)
            cleanSpecs.push(sp)
        }
        conduitSpecs = cleanSpecs
        conduitList.instances = entries
        liveByKey["__conduits"] = entries
        return entries
    }

    // Edge sources sit still, so their labels move only with the camera or the
    // plate size: re-project on those changes, never per frame.
    function projectSourceLabels() {
        var specs = sourceLabelSpecs || []
        var free = freeViewportRect()
        var out = []
        var key = ""
        for (var i = 0; i < specs.length; i++) {
            var sp = specs[i]
            if (!sp)
                continue
            var mapped = _tryMapFrom3DScene(Qt.vector3d(finiteNum(sp.x), finiteNum(sp.y), finiteNum(sp.z)))
            var sx = mapped ? Math.round(mapped.x) : -1000
            var sy = mapped ? Math.round(mapped.y) : -1000
            // mapFrom3DScene z is the distance past the near plane in scene
            // units (negative behind the camera), not a 0..1 depth.
            // A source under a HUD panel stays hidden with its label.
            var visible = !!mapped && mapped.z > 0 && sx > free.x && sy > free.y
                && sx < free.x + free.width && sy < free.y + free.height
            var row = {
                id: sp.id || ("src-" + i),
                label: sp.label || "",
                hot: !!sp.hot,
                color: sp.color || "#8fd3ff",
                status: sp.status || (sp.hot ? "fetching" : "idle"),
                sx: sx,
                sy: sy,
                visible: visible
            }
            key += row.id + ":" + row.label + ":" + row.hot + ":" + row.status + ":" + sx + ":" + sy + ":" + visible + "|"
            out.push(row)
        }
        if (key === sourceLabelKey)
            return
        sourceLabelKey = key
        sourceLabelScreen = out
        projectOrbLabels()
    }

    property var orbLabelScreen: []
    property string orbLabelKey: ""
    property real pulsePhase: 0
    property var orbLabelBlocks: []
    property var orbLeaders: []
    property var orbDots: []
    property var orbChips: []
    property var orbGlyphs: []

    TextMetrics { id: labelMetrics }

    function measureText(text, family, px) {
        labelMetrics.font.family = family
        labelMetrics.font.pixelSize = px
        labelMetrics.text = text || ""
        return { w: labelMetrics.advanceWidth, h: Math.max(px + 3, labelMetrics.height) }
    }

    // HUD keep-out rects in view pixels (OverseerHud.qml: margins 2 percent, header 72, inspector 360 wide,
    // legend 250 x 165 bottom-left, dispatch bar 96 tall centred, replay strip 60). 8 px clearance.
    function hudKeepOut() {
        var mx = Math.round(width * 0.02), my = Math.round(height * 0.02), pad = 8
        var out = [{ x0: 0, y0: 0, x1: width, y1: my + 72 + pad }]
        if (root.showInspector && root.selectedUnitId)
            out.push({ x0: width - mx - 360 - pad, y0: my + 72, x1: width, y1: height })
        out.push({ x0: 0, y0: height - my - 60 - 165 - pad, x1: mx + 250 + pad, y1: height })
        out.push({ x0: width * 0.5 - 420, y0: height - my - 60 - 96 - pad, x1: width * 0.5 + 420, y1: height })
        out.push({ x0: 0, y0: height - my - 60, x1: width, y1: height })
        return out
    }

    function rectHitsCircle(r, c, rad) {
        var nx = Math.min(Math.max(c.x, r.x0), r.x1)
        var ny = Math.min(Math.max(c.y, r.y0), r.y1)
        var dx = nx - c.x, dy = ny - c.y
        return dx * dx + dy * dy < rad * rad
    }

    function rectHitsRect(a, b, pad) {
        pad = pad === undefined ? 4 : pad
        return !(a.x1 + pad <= b.x0 || b.x1 + pad <= a.x0 || a.y1 + pad <= b.y0 || b.y1 + pad <= a.y0)
    }

    function labelFree(r, keep, cx, cy, rects, beads) {
        if (rectHitsCircle(r, { x: cx, y: cy }, keep))
            return false
        var i
        for (i = 0; i < rects.length; i++) {
            if (rectHitsRect(r, rects[i], 4))
                return false
        }
        for (i = 0; i < beads.length; i++) {
            if (rectHitsCircle(r, { x: beads[i].x, y: beads[i].y }, beads[i].r))
                return false
        }
        return true
    }

    function ringScreenPoints(tilt, radius, n, spinDeg) {
        var pts = []
        for (var i = 0; i <= n; i++) {
            var a = 2 * Math.PI * i / n
            var w = ringWorld(tilt, spinDeg || 0, radius, a)
            var m = _tryMapFrom3DScene(w)
            if (m)
                pts.push({ x: m.x, y: m.y, z: m.z, a: a })
        }
        return pts
    }

    function shellScreen() {
        var cam = cameraWorldPos()
        var c = root.orbCentre
        var dx = cam.x - c.x, dy = cam.y - c.y, dz = cam.z - c.z
        var dist = Math.sqrt(dx * dx + dy * dy + dz * dz)
        var f = Math.max(1, height) / (2 * Math.tan(17.5 * Math.PI / 180))
        var denom = Math.sqrt(Math.max(dist * dist - root.orbRadius * root.orbRadius, 1e-6))
        var rs = f * root.orbRadius / denom
        var mapped = _tryMapFrom3DScene(c)
        return {
            rs: rs,
            keep: rs * 1.04 + 4,
            cx: mapped ? mapped.x : width / 2,
            cy: mapped ? mapped.y : height / 2
        }
    }

    function ellipsize(text, maxGlyphs) {
        var s = String(text || "")
        if (s.length <= maxGlyphs)
            return s
        return s.substring(0, Math.max(0, maxGlyphs - 1)).replace(/\s+$/, "") + "..."
    }

    function projectOrbLabels() {
        var shell = shellScreen()
        // fix-c05bb78 #9: the big block layout is for core focus only; in unit focus the orb is a backdrop.
        var closeUp = shell.rs >= 90 && root.coreMode
        var key
        if (!closeUp) {
            // Overview chips pin to the untilted ring extremes, so spin
            // must not retrigger layout (or the 360 mapFrom3DScene calls).
            key = "o|" + toolsCount + "|" + memoryCount + "|" + Math.round(shell.rs) + "|" + Math.round(cameraDistance * 10) + "|" + Math.round(width) + "x" + Math.round(height)
        } else {
            key = "c|" + toolsCount + "|" + memoryCount + "|" + (orbResults || []).length + "|" + Math.round(shell.rs) + "|" + Math.round(cameraDistance * 10) + "|" + Math.round(memorySpin) + "|" + Math.round(toolsSpin)
        }
        if (key === orbLabelKey)
            return
        orbLabelComputeCount += 1
        var blocks = [], leaders = [], dots = [], chips = [], glyphs = [], screen = []
        var rects = hudKeepOut(), beadGlows = []
        var nKeep = rects.length
        var tp = ringScreenPoints(toolsTiltEuler(), root.toolsRingRadius, 180, 0)
        var mp = ringScreenPoints(memoryTiltEuler(), root.memoryRingRadius, 180, 0)
        if (!tp.length || !mp.length) {
            if (orbLabelKey !== "empty") {
                orbLabelKey = "empty"
                orbLabelBlocks = []; orbLeaders = []; orbDots = []; orbChips = []; orbGlyphs = []; orbLabelScreen = []
            }
            return
        }
        var i
        function leftmost(pts) {
            var best = pts[0]
            for (var k = 1; k < pts.length; k++)
                if (pts[k].x < best.x) best = pts[k]
            return best
        }
        function rightmost(pts) {
            var best = pts[0]
            for (var k = 1; k < pts.length; k++)
                if (pts[k].x > best.x) best = pts[k]
            return best
        }
        function lowest(pts) {
            var best = pts[0]
            for (var k = 1; k < pts.length; k++)
                if (pts[k].y > best.y) best = pts[k]
            return best
        }
        if (!closeUp) {
            function plate(id, text, ax, ay, dx, dy) {
                var sz = measureText(text, root.glyphFontFamily, 15)
                var W = sz.w + 18, H = sz.h + 12
                var r = { x0: ax + dx - W, y0: ay + dy - H / 2, x1: ax + dx, y1: ay + dy + H / 2 }
                var guard = 0
                while (!labelFree(r, shell.keep, shell.cx, shell.cy, rects, beadGlows) && guard < 40) {
                    r = { x0: r.x0 - 8, y0: r.y0, x1: r.x1 - 8, y1: r.y1 }
                    guard++
                }
                var midY = (r.y0 + r.y1) / 2
                leaders.push({ id: id + "Leader", x1: ax, y1: ay, x2: r.x1, y2: midY })
                dots.push({ id: id + "Dot", x: ax, y: ay })
                blocks.push({ id: id, text: text, x: r.x0, y: r.y0, w: W, h: H, kind: "chip" })
                rects.push(r)
                screen.push({ id: id, text: text, color: "#e8dcfb", sx: Math.round((r.x0 + r.x1) / 2), sy: Math.round(midY), visible: true })
            }
            var ta = leftmost(tp)
            plate("tools", "Tools · " + toolsCount + " running", ta.x, ta.y, -70, -34)
            var ma = lowest(mp)
            plate("memory", "Memory · " + memoryCount + " from last chat", ma.x, ma.y, -110, 46)
        } else {
            var tn = Math.max(toolsCount, 1)
            for (i = 0; i < toolsCount; i++) {
                var ang = root.toolPhase + i * 2 * Math.PI / tn
                var bw = ringWorld(toolsTiltEuler(), toolsSpin, root.toolsRingRadius, ang)
                var bm = _tryMapFrom3DScene(bw)
                if (bm)
                    beadGlows.push({ x: bm.x, y: bm.y, r: 34 })
            }
            var axp = rightmost(tp)
            var toolsTitle = measureText("Tools", root.hudSansFamily, 25)
            var toolsStatus = measureText(toolsCount + " running", root.hudSansFamily, 18)
            var tW = Math.max(toolsTitle.w, toolsStatus.w)
            var tH = toolsTitle.h + toolsStatus.h
            var tb = { x0: axp.x + 22, y0: axp.y - 78, x1: axp.x + 22 + tW, y1: axp.y - 78 + tH }
            var guard = 0
            while (!labelFree(tb, shell.keep, shell.cx, shell.cy, rects, beadGlows) && guard < 40) {
                tb = { x0: tb.x0 + 6, y0: tb.y0 - 4, x1: tb.x1 + 6, y1: tb.y1 - 4 }
                guard++
            }
            blocks.push({
                id: "tools", kind: "block", x: tb.x0, y: tb.y0,
                w: tW, h: tH, title: "Tools", status: toolsCount + " running",
                titleSize: 25, statusSize: 18, titleColor: "#ffffff", statusColor: "#cdb2f7"
            })
            leaders.push({ id: "toolsLeader", x1: axp.x + 4, y1: axp.y - 4, x2: tb.x0 - 3, y2: tb.y1 - 4 })
            rects.push(tb)
            screen.push({ id: "tools", text: "Tools " + toolsCount + " running", color: "#ffffff", sx: Math.round((tb.x0 + tb.x1) / 2), sy: Math.round((tb.y0 + tb.y1) / 2), visible: true })

            var bxp = lowest(mp)
            var memTitle = measureText("Memory", root.hudSansFamily, 25)
            var memStatus = measureText(memoryCount + " from last chat", root.hudSansFamily, 18)
            var mW = Math.max(memTitle.w, memStatus.w)
            var mH = memTitle.h + memStatus.h
            var top = Math.max(bxp.y + 18, shell.cy + shell.keep + 6)
            var mb = { x0: bxp.x - mW / 2, y0: top, x1: bxp.x + mW / 2, y1: top + mH }
            blocks.push({
                id: "memory", kind: "block", x: mb.x0, y: mb.y0, align: "centre",
                w: mW, h: mH, title: "Memory", status: memoryCount + " from last chat",
                titleSize: 25, statusSize: 18, titleColor: "#ffffff", statusColor: "#cdb2f7"
            })
            leaders.push({ id: "memoryLeader", x1: bxp.x, y1: bxp.y + 5, x2: bxp.x, y2: mb.y0 - 3 })
            rects.push(mb)
            screen.push({ id: "memory", text: "Memory " + memoryCount + " from last chat", color: "#ffffff", sx: Math.round(bxp.x), sy: Math.round(top + mH / 2), visible: true })

            var names = orbTools || []
            for (i = 0; i < Math.min(toolsCount, names.length || toolsCount); i++) {
                var nm = (names[i] && names[i].id) ? names[i].id : ("tool-" + i)
                var a2 = root.toolPhase + i * 2 * Math.PI / tn
                var ww = ringWorld(toolsTiltEuler(), toolsSpin, root.toolsRingRadius, a2)
                var sm = _tryMapFrom3DScene(ww)
                if (!sm)
                    continue
                if (Math.hypot(sm.x - shell.cx, sm.y - shell.cy) < shell.keep + 8)
                    continue
                var sz = measureText(nm, root.glyphFontFamily, 16)
                var W = sz.w + 16, H = sz.h + 8
                var side = sm.x >= shell.cx ? 1 : -1
                var cands = [], dys = [-26, 26, -46, 46], pushes = [22, 36, 54], di, pi
                for (di = 0; di < dys.length; di++) {
                    for (pi = 0; pi < pushes.length; pi++) {
                        var x0 = side > 0 ? sm.x + pushes[pi] : sm.x - pushes[pi] - W
                        cands.push({ x0: x0, y0: sm.y + dys[di] - H / 2, x1: x0 + W, y1: sm.y + dys[di] + H / 2 })
                    }
                }
                var chosen = cands[0]
                for (pi = 0; pi < cands.length; pi++) {
                    if (labelFree(cands[pi], shell.keep, shell.cx, shell.cy, rects, beadGlows)) {
                        chosen = cands[pi]
                        break
                    }
                }
                chips.push({ id: "chip_" + nm, text: nm, x: chosen.x0, y: chosen.y0, w: W, h: H })
                leaders.push({
                    id: "chipLeader_" + nm,
                    x1: sm.x + side * 6, y1: sm.y,
                    x2: side > 0 ? chosen.x0 : chosen.x1,
                    y2: (chosen.y0 + chosen.y1) / 2
                })
                rects.push(chosen)
            }

            if (root.resultsFade > 0.001 && (orbResults || []).length) {
                var rp = ringScreenPoints(resultsTiltEuler(), root.resultsRadius, 360, 0)
                layoutResultTitles(orbResults, rp, shell, rects, beadGlows, tp.concat(mp), glyphs)
            }
        }
        // Drop any label still touching the HUD or the frame edge (with its leader and dot) instead of overlapping.
        var kept = [], dropped = ({})
        for (i = 0; i < blocks.length; i++) {
            var bk = blocks[i]
            var br = { x0: bk.x, y0: bk.y, x1: bk.x + (bk.w || 0), y1: bk.y + (bk.h || 0) }
            var bad = br.x0 < 0 || br.y0 < 0 || br.x1 > width || br.y1 > height
            for (var hk = 0; hk < nKeep && !bad; hk++)
                if (rectHitsRect(br, rects[hk], 0)) bad = true
            if (bad) dropped[bk.id] = true
            else kept.push(bk)
        }
        blocks = kept
        leaders = leaders.filter(function (q) { return !dropped[String(q.id).replace("Leader", "")] })
        dots = dots.filter(function (q) { return !dropped[String(q.id).replace("Dot", "")] })
        chips = chips.filter(function (q) {
            var cr = { x0: q.x, y0: q.y, x1: q.x + q.w, y1: q.y + q.h }
            for (var hk2 = 0; hk2 < nKeep; hk2++) if (rectHitsRect(cr, rects[hk2], 0)) { dropped[q.id] = true; return false }
            return cr.x0 >= 0 && cr.y0 >= 0 && cr.x1 <= width && cr.y1 <= height
        })
        leaders = leaders.filter(function (q) { return !dropped[String(q.id).replace("chipLeader_", "chip_")] })
        screen = screen.filter(function (q) { return !dropped[q.id] })
        orbLabelKey = key
        orbLabelBlocks = blocks
        orbLeaders = leaders
        orbDots = dots
        orbChips = chips
        orbGlyphs = glyphs
        orbLabelScreen = screen
    }

    function layoutResultTitles(titles, rp, shell, rects, beads, obst, glyphs) {
        if (!rp.length)
            return
        var L = [0]
        var i
        for (i = 1; i < rp.length; i++)
            L.push(L[i - 1] + Math.hypot(rp[i].x - rp[i - 1].x, rp[i].y - rp[i - 1].y))
        function at(sv) {
            var j = 1
            while (j < L.length && L[j] < sv)
                j++
            j = Math.max(1, Math.min(L.length - 1, j))
            var t = (sv - L[j - 1]) / Math.max(L[j] - L[j - 1], 1e-6)
            var p = { x: rp[j - 1].x + (rp[j].x - rp[j - 1].x) * t, y: rp[j - 1].y + (rp[j].y - rp[j - 1].y) * t }
            var ang = Math.atan2(rp[j].y - rp[j - 1].y, rp[j].x - rp[j - 1].x)
            return { p: p, ang: ang, j: j }
        }
        function pickIndex(tx, upper) {
            var best = -1, bestD = 1e9
            for (var k = 0; k < rp.length; k++) {
                if ((rp[k].y < shell.cy) !== upper)
                    continue
                var d = Math.abs(rp[k].x - tx)
                if (d < bestD) { bestD = d; best = k }
            }
            return best
        }
        var tries = [], fxs = [-1.62, 1.62, -1.85, 1.85, -1.4, 1.4, -0.45, 0.45, -1.1, 1.1, 0.0], fi
        for (fi = 0; fi < fxs.length; fi++) {
            tries.push({ fx: fxs[fi], upper: true })
            tries.push({ fx: fxs[fi], upper: false })
        }
        var used = {}
        for (var ti = 0; ti < titles.length; ti++) {
            var txt = ellipsize(titles[ti], 34)
            for (var tr = 0; tr < tries.length; tr++) {
                var tag = tries[tr].fx + ":" + tries[tr].upper
                if (used[tag])
                    continue
                var idx = pickIndex(shell.cx + tries[tr].fx * shell.rs, tries[tr].upper)
                if (idx < 0)
                    continue
                var fontPx = 17
                var fwd = rp[Math.min(idx + 3, rp.length - 1)].x - rp[Math.max(idx - 3, 0)].x >= 0
                var tw = measureText(txt, root.glyphFontFamily, fontPx).w
                var s0 = fwd ? (L[idx] - tw / 2) : (L[idx] + tw / 2)
                var cur = 0, boxes = [], letters = [], ok = true, ci
                for (ci = 0; ci < txt.length; ci++) {
                    var ch = txt.charAt(ci)
                    var cw = measureText(ch, root.glyphFontFamily, fontPx).w
                    var loc = at(s0 + (cur + cw / 2) * (fwd ? 1 : -1))
                    cur += cw
                    var angDeg = (fwd ? loc.ang : loc.ang + Math.PI) * 180 / Math.PI
                    letters.push({ ch: ch, x: loc.p.x, y: loc.p.y, rot: angDeg, w: cw })
                    boxes.push({ x0: loc.p.x - cw, y0: loc.p.y - fontPx, x1: loc.p.x + cw, y1: loc.p.y + fontPx * 0.4 })
                }
                for (ci = 0; ci < boxes.length; ci++) {
                    if (rectHitsCircle(boxes[ci], { x: shell.cx, y: shell.cy }, shell.keep)
                            || !labelFree(boxes[ci], 0, shell.cx, shell.cy, rects, beads)) {
                        ok = false
                        break
                    }
                    for (var oi = 0; oi < obst.length; oi++) {
                        var op = obst[oi]
                        if (op.x >= boxes[ci].x0 - 4 && op.x <= boxes[ci].x1 + 4
                                && op.y >= boxes[ci].y0 - 4 && op.y <= boxes[ci].y1 + 4) {
                            ok = false
                            break
                        }
                    }
                    if (!ok)
                        break
                }
                if (!ok)
                    continue
                used[tag] = true
                var union = boxes[0]
                for (ci = 1; ci < boxes.length; ci++) {
                    union = {
                        x0: Math.min(union.x0, boxes[ci].x0), y0: Math.min(union.y0, boxes[ci].y0),
                        x1: Math.max(union.x1, boxes[ci].x1), y1: Math.max(union.y1, boxes[ci].y1)
                    }
                }
                rects.push(union)
                for (ci = 0; ci < letters.length; ci++) {
                    glyphs.push({
                        id: "result_" + ti + "_" + ci,
                        text: letters[ci].ch, x: letters[ci].x, y: letters[ci].y, rot: letters[ci].rot
                    })
                }
                break
            }
        }
    }


    function stepConduits() {
        var specs = conduitSpecs
        if (!specs || !specs.length || !liveByKey)
            return
        var entries = liveByKey["__conduits"] || []
        if (entries.length !== specs.length)
            return
        var tSec = finiteNum(sceneTime, 0)
        for (var i = 0; i < specs.length; i++) {
            var st = evalConduitSpec(specs[i], tSec)
            var psc = st.scale * 0.0022
            var e = entries[i]
            e.position = Qt.vector3d(st.x, st.y, st.z)
            e.scale = Qt.vector3d(psc, psc, psc)
        }
    }

    function stepOrbits() {
        // band_point() of the runtime at theta + omega * (time since the frame).
        var orbits = unitOrbitSpecs
        if (!orbits || !orbits.length)
            return
        var t = sceneTime
        for (var i = 0; i < orbits.length; i++) {
            var os = orbits[i]
            var o = os.o
            var th = o[6] + o[5] * (t - os.t0)
            var c = Math.cos(th), s = Math.sin(th)
            var x = c * o[3], y = s * o[3], z = o[4]
            var x1 = x * os.cy + z * os.sy
            var z1 = -x * os.sy + z * os.cy
            var y2 = y * os.cx - z1 * os.sx
            var z2 = y * os.sx + z1 * os.cx
            // Tangent (heading) through the same tilt.
            var tx1 = -s * os.cy
            var tz1 = s * os.sy
            var ty2 = c * os.cx - tz1 * os.sx
            var pos = Qt.vector3d(x1, z2 + o[2], -y2)
            var rot = Qt.vector3d(0, -Math.atan2(-ty2, tx1) * 180 / Math.PI, 0)
            var ents = os.entries
            for (var k = 0; k < ents.length; k++) {
                ents[k].position = pos
                ents[k].eulerRotation = rot
            }
        }
    }

    function stepUnits(dt) {
        if (dt <= 0)
            return
        stepOrbits()
        var specs = unitAnimSpecs
        if (!specs || !specs.length)
            return
        var stepDt = Math.min(0.05, dt)
        for (var i = 0; i < specs.length; i++) {
            var sp = specs[i]
            var e = sp.entry
            if (!e)
                continue
            var nx = finiteCoord(e.position.x + sp.vx * stepDt, e.position.x)
            var ny = Math.max(-7.5, finiteCoord(e.position.y + sp.vy * stepDt, e.position.y))
            var nz = finiteCoord(e.position.z + sp.vz * stepDt, e.position.z)
            e.position = Qt.vector3d(nx, ny, nz)
        }
    }

    function liveEntryCountFromLists() {
        var n = 0
        var keys = Object.keys(lists)
        for (var i = 0; i < keys.length; i++) {
            var insts = lists[keys[i]].instances || []
            n += insts.length
        }
        if (particleList && particleList.instances)
            n += particleList.instances.length
        if (conduitList && conduitList.instances)
            n += conduitList.instances.length
        return n
    }

    Component.onCompleted: {
        ensureLists()
        buildStarMesh()
        rebuildOrbOrnaments()
        updateOverview()
    }


    // Thin orbit rings: Qt #Cylinder is a solid 100-unit primitive, so
    // scale (R/50, 0.002, R/50) makes a filled disc of radius R. Pass 5
    // uses a torus of major radius R and minor 0.014 (R<=12) or 0.02.
    readonly property int ringSegments: 96
    readonly property int ringTubeSegments: 8

    function ringPositions(radius, tube) {
        var pos = []
        var segs = ringSegments
        var tubeSegs = ringTubeSegments
        for (var i = 0; i < segs; i++) {
            var theta = i / segs * Math.PI * 2
            var ct = Math.cos(theta)
            var st = Math.sin(theta)
            for (var j = 0; j < tubeSegs; j++) {
                var phi = j / tubeSegs * Math.PI * 2
                var cp = Math.cos(phi)
                var sp = Math.sin(phi)
                var rr = radius + tube * cp
                pos.push(Qt.vector3d(rr * ct, tube * sp, rr * st))
            }
        }
        return pos
    }

    function ringNormals(radius, tube) {
        var nrm = []
        var segs = ringSegments
        var tubeSegs = ringTubeSegments
        for (var i = 0; i < segs; i++) {
            var theta = i / segs * Math.PI * 2
            var ct = Math.cos(theta)
            var st = Math.sin(theta)
            for (var j = 0; j < tubeSegs; j++) {
                var phi = j / tubeSegs * Math.PI * 2
                var cp = Math.cos(phi)
                var sp = Math.sin(phi)
                nrm.push(Qt.vector3d(cp * ct, sp, cp * st))
            }
        }
        return nrm
    }

    function ringIndexes() {
        var idx = []
        var segs = ringSegments
        var tubeSegs = ringTubeSegments
        for (var i = 0; i < segs; i++) {
            var i0 = i * tubeSegs
            var i1 = ((i + 1) % segs) * tubeSegs
            for (var j = 0; j < tubeSegs; j++) {
                var j1 = (j + 1) % tubeSegs
                idx.push(i0 + j, i1 + j, i1 + j1)
                idx.push(i0 + j, i1 + j1, i0 + j1)
            }
        }
        return idx
    }

    FrameAnimation {
        running: root.viewOnScreen
        onTriggered: {
            if (!root.viewOnScreen)
                return
            // A hitch should not catch up a huge spin or layout step.
            var dt = Math.min(frameTime, 0.05)
            root.sceneTime += dt
            root.stepUnits(dt)
            // Ease activity over about 0.5 s, then drift the star layers with it.
            var k = Math.min(1, dt / 0.5)
            root.hiveActivityShown += (root.hiveActivity - root.hiveActivityShown) * k
            root.starDrift += dt * (0.25 + 2.75 * root.hiveActivityShown)
            root.orbEnergyShown += (root.orbEnergy - root.orbEnergyShown) * k
            var spinT = root.tokRate > 0 ? 8.0 : 20.0
            root.orbSpinAngle += dt * (2.0 * Math.PI / spinT)
            root.memorySpin += dt * 6.0
            if (root.toolsCount > 0)
                root.toolsSpin += dt * 30.0
            if (root.tokRate > 0) {
                root.pulsePhase += dt / 0.6
                if (root.pulsePhase >= 1.0)
                    root.pulsePhase -= Math.floor(root.pulsePhase)
                // A 35 percent expanding HDR shell doubled the bloom disc.
                // Keep the token pulse, but as a small breath around the shell.
                root.pulseScale = 1.0 + 0.06 * root.pulsePhase
                root.pulseGain = (1.0 - root.pulsePhase) * root.orbEnergyShown
            } else {
                root.pulsePhase = 0
                root.pulseScale = 1
                root.pulseGain = 0
            }
            root.stepTentacleWeights(dt)
            root.projectOrbLabels()
            root.refreshUnitTex()
        }
    }

    NumberAnimation on entryMs {
        id: entryAnim
        from: 0
        to: 1600
        duration: 1600
        running: false
        onFinished: root.entryPlaying = false
    }

    NumberAnimation {
        id: coreEaseAnim
        target: root
        property: "coreEaseU"
        from: 0
        to: 1
        duration: 900
        easing.type: Easing.InOutCubic
        running: false
        onFinished: root.finishCoreEase()
    }

    onCoreEaseUChanged: {
        if (root.coreTransitioning)
            root.applyCoreEase(root.coreEaseU)
    }

    Rectangle {
        id: backdrop
        objectName: "overseerBackdrop"
        anchors.fill: parent
        color: "#0b0714"
        z: -1
    }

    Rectangle {
        id: fillPlate
        objectName: "overseerFillPlate"
        anchors.fill: parent
        color: "#0b0714"
        // Opaque while View3D.reveal is 0 so the QQuickWidget cannot
        // show its default white clear through a transparent scene.
        opacity: Math.max(root.fill, 1.0 - root.reveal)
        radius: 28
        z: 0
    }

    View3D {
        id: view
        objectName: "OverseerView3D"
        anchors.fill: parent
        camera: cam
        opacity: Math.max(0, Math.min(1, root.reveal))
        z: 1
        WheelHandler {
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function (event) {
                var notches = -event.angleDelta.y / 120
                root.applyWheel(notches)
                event.accepted = true
            }
        }
        TapHandler {
            acceptedButtons: Qt.LeftButton
            grabPermissions: PointerHandler.CanTakeOverFromItems | PointerHandler.ApprovesTakeOverByAnything
            onTapped: function (event, button) {
                var pt = event.position
                var hit = view.pick(pt.x, pt.y)
                var obj = hit ? hit.objectHit : null
                if (obj && root.orbPickHitsCore(obj)) {
                    if (!root.coreMode)
                        root.enterCoreFocus()
                    event.accepted = true
                }
            }
        }
        environment: SceneEnvironment {
            objectName: "overseerEnvironment"
            backgroundMode: SceneEnvironment.Color
            // The scene used to draw a 1600 m lit floor plane under everything.
            // At every approved camera it filled the whole view with one flat
            // dark grey (15, 14, 17 after the filmic tonemap), a full screen of
            // lit fragments per frame. This clear colour tonemaps to the same
            // grey, so the floor plane and its fill are gone.
            clearColor: root.skyColor
            // OverseerBloom's last pass runs the Filmic tonemap.
            tonemapMode: SceneEnvironment.TonemapModeNone
            antialiasingMode: root.msaaSamples > 1 ? SceneEnvironment.MSAA : SceneEnvironment.NoAA
            antialiasingQuality: root.msaaSamples >= 8 ? SceneEnvironment.VeryHigh
                                 : (root.msaaSamples >= 4 ? SceneEnvironment.High : SceneEnvironment.Medium)
            // Bloom: only HDR values over the threshold (eyes, beams, source
            // cores) glow; hulls, lanes and the perimeter stay under it.
            effects: [overseerBloom]
            fog: Fog {
                enabled: true
                color: root.fogColor
                density: 0.6
                depthEnabled: true
                depthNear: root.fogNear
                depthFar: root.fogFar
            }
        }

        OverseerBloom {
            id: overseerBloom
            objectName: "overseerBloom"
            levels: root.glowLevels
            uThreshold: root.glowThreshold
        }

        PerspectiveCamera {
            id: cam
            clipNear: 1.0
            fieldOfView: 35
            fieldOfViewOrientation: PerspectiveCamera.Vertical
            position: {
                const d = root.cameraDistance
                const pitch = root.cameraPitch * Math.PI / 180
                const sh = root.lensShiftOffset()
                return Qt.vector3d(
                    root.cameraTargetX + sh.x,
                    root.cameraTargetY + Math.sin(pitch) * d + sh.y,
                    root.cameraTargetZ + Math.cos(pitch) * d + sh.z
                )
            }
            eulerRotation.x: -root.cameraPitch
            onPositionChanged: root.projectSourceLabels()
            onEulerRotationChanged: root.projectSourceLabels()
        }

        DirectionalLight { eulerRotation.x: -40; eulerRotation.y: 30; brightness: 1.0 }
        DirectionalLight { eulerRotation.x: -15; eulerRotation.y: -120; brightness: 0.35 }

        Node {
            id: hiveCore
            objectName: "hiveCore"
            y: 1.6
            Node {
                objectName: "orbBody"
                Model {
                    id: orbCore
                    objectName: "orbCore"
                    source: "meshes/orb_core_mesh.mesh"
                    materials: CustomMaterial {
                        shadingMode: CustomMaterial.Unshaded
                        vertexShader: "shaders/orb_shell.vert"
                        fragmentShader: "shaders/orb_core.frag"
                        sourceBlend: CustomMaterial.One
                        destinationBlend: CustomMaterial.One
                        depthDrawMode: Material.NeverDepthDraw
                        property real coreGain: root.orbCoreGain
                        property real coreFloor: root.orbCoreFloor
                        property real energy: root.orbEnergyShown
                        property real coreSoftPow: root.orbCoreSoftPow
                        property real coreTightPow: root.orbCoreTightPow
                        property real coreTightMix: root.orbCoreTightMix
                        property vector3d coreCentre: root.linearVec("#f3edff")
                        property vector3d coreEdge: root.linearVec("#b48cf5")
                    }
                }
                Model {
                    objectName: "orbFilaments"
                    source: "meshes/orb_filaments_d_mesh.mesh"
                    materials: CustomMaterial {
                        shadingMode: CustomMaterial.Unshaded
                        vertexShader: "shaders/emission_minpx.vert"
                        fragmentShader: "shaders/orb_emission.frag"
                        sourceBlend: CustomMaterial.One
                        destinationBlend: CustomMaterial.One
                        depthDrawMode: Material.NeverDepthDraw
                        property vector3d spinAxis: Qt.vector3d(0.25, 1.0, 0.2)
                        property real spinAngle: root.orbSpinAngle
                        property real spinShear: 0.15
                        property vector3d tint: Qt.vector3d(1, 1, 1)
                        property real gain: root.orbFilamentGain * root.orbEnergyShown
                        property vector3d litArc: Qt.vector3d(0, 0, 2)
                        property real dim: 1
                        property real tubeRadius: root.filTube
                        property real minPx: root.filMinPx
                        property real pxAngle: 0.6306 / Math.max(1, view.height)
                        property real backGain: 1.0
                        property vector3d orbCentre: root.orbCentre
                    }
                }
                Model {
                    objectName: "orbShell"
                    source: "meshes/orb_shell_mesh.mesh"
                    materials: CustomMaterial {
                        shadingMode: CustomMaterial.Unshaded
                        vertexShader: "shaders/orb_shell.vert"
                        fragmentShader: "shaders/orb_shell.frag"
                        sourceBlend: CustomMaterial.One
                        destinationBlend: CustomMaterial.One
                        depthDrawMode: Material.NeverDepthDraw
                        cullMode: Material.NoCulling
                        property vector3d shellColor: root.linearVec("#b4a0f2")
                        property real energy: root.orbEnergyShown
                        property real shellPower: root.orbShellPower
                        property real shellGain: root.orbShellGain
                        property real shellBody: root.orbShellBody
                        property vector4d impact: root.orbImpact
                    }
                }
                Model {
                    objectName: "orbPulseShell"
                    source: "meshes/orb_shell_mesh.mesh"
                    visible: root.pulseGain > 0.01
                    scale: Qt.vector3d(root.pulseScale, root.pulseScale, root.pulseScale)
                    materials: CustomMaterial {
                        shadingMode: CustomMaterial.Unshaded
                        vertexShader: "shaders/orb_shell.vert"
                        fragmentShader: "shaders/orb_shell.frag"
                        sourceBlend: CustomMaterial.One
                        destinationBlend: CustomMaterial.One
                        depthDrawMode: Material.NeverDepthDraw
                        cullMode: Material.NoCulling
                        property vector3d shellColor: root.linearVec("#b4a0f2")
                        property real energy: root.pulseGain
                        property real shellPower: root.orbShellPower
                        property real shellGain: root.orbPulseShellGain
                        property real shellBody: 0
                        property vector4d impact: Qt.vector4d(0, 1, 0, -1)
                    }
                }
            }
            Node {
                id: memoryTilt
                objectName: "memoryTilt"
                eulerRotation: Qt.vector3d(6.62, 0, -28.75)
                Node {
                    id: memorySpinNode
                    objectName: "memorySpinNode"
                    eulerRotation.y: root.memorySpin
                    Model {
                        objectName: "orbRingMemory"
                        visible: false
                        source: "meshes/orb_ring_memory_d_mesh.mesh"
                    materials: CustomMaterial {
                        shadingMode: CustomMaterial.Unshaded
                        vertexShader: "shaders/emission_minpx.vert"
                        fragmentShader: "shaders/orb_emission.frag"
                        sourceBlend: CustomMaterial.One
                        destinationBlend: CustomMaterial.One
                        depthDrawMode: Material.NeverDepthDraw
                        property vector3d spinAxis: Qt.vector3d(0, 1, 0)
                        property real spinAngle: 0
                        property real spinShear: 0
                        property vector3d tint: Qt.vector3d(1, 1, 1)
                        property real gain: 0.95
                        property vector3d litArc: Qt.vector3d(0, 0, 2)
                        property real dim: 1
                        property real tubeRadius: 0.016
                        property real minPx: root.ringMinPx
                        property real pxAngle: 0.6306 / Math.max(1, view.height)
                        property real backGain: root.ringBackGain
                        property vector3d orbCentre: root.orbCentre
                    }
                    }
                    Model {
                        objectName: "orbMemoryBeads"
                        visible: false
                        instancing: memoryBeadInstanceList
                        source: "meshes/orb_bead_mesh.mesh"
                        materials: CustomMaterial {
                            shadingMode: CustomMaterial.Unshaded
                            vertexShader: "shaders/orb_bead.vert"
                            fragmentShader: "shaders/orb_emission.frag"
                            sourceBlend: CustomMaterial.One
                            destinationBlend: CustomMaterial.One
                            depthDrawMode: Material.NeverDepthDraw
                            property vector3d spinAxis: Qt.vector3d(0, 1, 0)
                            property real spinAngle: 0
                            property real spinShear: 0
                            property vector3d tint: Qt.vector3d(1, 1, 1)
                            property real gain: 1.6
                            property vector3d litArc: Qt.vector3d(0, 0, 2)
                            property real dim: 1
                            property real backGain: root.ringBackGain
                            property vector3d orbCentre: root.orbCentre
                        }
                    }
                }
            }
            Node {
                id: toolsTilt
                objectName: "toolsTilt"
                eulerRotation: Qt.vector3d(-0.22, 0, 13.97)
                Node {
                    id: toolsSpinNode
                    objectName: "toolsSpinNode"
                    eulerRotation.y: root.toolsSpin
                    Model {
                        objectName: "orbRingTools"
                        visible: false
                        source: "meshes/orb_ring_tools_d_mesh.mesh"
                    materials: CustomMaterial {
                        shadingMode: CustomMaterial.Unshaded
                        vertexShader: "shaders/emission_minpx.vert"
                        fragmentShader: "shaders/orb_emission.frag"
                        sourceBlend: CustomMaterial.One
                        destinationBlend: CustomMaterial.One
                        depthDrawMode: Material.NeverDepthDraw
                        property vector3d spinAxis: Qt.vector3d(0, 1, 0)
                        property real spinAngle: 0
                        property real spinShear: 0
                        property vector3d tint: Qt.vector3d(1, 1, 1)
                        property real gain: 0.85
                        property vector3d litArc: root.toolsLitArc
                        property real dim: 1
                        property real tubeRadius: 0.020
                        property real minPx: root.ringMinPx
                        property real pxAngle: 0.6306 / Math.max(1, view.height)
                        property real backGain: root.ringBackGain
                        property vector3d orbCentre: root.orbCentre
                    }
                    }
                    Model {
                        objectName: "orbToolBeads"
                        visible: false
                        instancing: toolBeadInstanceList
                        source: "meshes/orb_bead_mesh.mesh"
                        materials: CustomMaterial {
                            shadingMode: CustomMaterial.Unshaded
                            vertexShader: "shaders/orb_bead.vert"
                            fragmentShader: "shaders/orb_emission.frag"
                            sourceBlend: CustomMaterial.One
                            destinationBlend: CustomMaterial.One
                            depthDrawMode: Material.NeverDepthDraw
                            property vector3d spinAxis: Qt.vector3d(0, 1, 0)
                            property real spinAngle: 0
                            property real spinShear: 0
                            property vector3d tint: Qt.vector3d(1, 1, 1)
                            property real gain: 2.8
                            property vector3d litArc: Qt.vector3d(0, 0, 2)
                            property real dim: 1
                            property real backGain: root.ringBackGain
                            property vector3d orbCentre: root.orbCentre
                        }
                    }
                }
            }
            Node {
                id: resultsTilt
                objectName: "resultsTilt"
                eulerRotation: Qt.vector3d(-4.52, 0, 2.86)
                visible: root.resultsFade > 0.001
                scale: Qt.vector3d(root.resultsRadius / root.resultsRingAuthored,
                                   root.resultsRadius / root.resultsRingAuthored,
                                   root.resultsRadius / root.resultsRingAuthored)
                Model {
                    objectName: "orbRingResults"
                    visible: false
                    source: "meshes/orb_ring_results_d_mesh.mesh"
                    materials: CustomMaterial {
                        shadingMode: CustomMaterial.Unshaded
                        vertexShader: "shaders/emission_minpx.vert"
                        fragmentShader: "shaders/orb_emission.frag"
                        sourceBlend: CustomMaterial.One
                        destinationBlend: CustomMaterial.One
                        depthDrawMode: Material.NeverDepthDraw
                        property vector3d spinAxis: Qt.vector3d(0, 1, 0)
                        property real spinAngle: 0
                        property real spinShear: 0
                        property vector3d tint: Qt.vector3d(1, 1, 1)
                        property real gain: 0.42 * root.resultsFade
                        property vector3d litArc: Qt.vector3d(0, 0, 2)
                        property real dim: 1
                        property real tubeRadius: 0.011
                        property real minPx: root.ringMinPx
                        property real pxAngle: 0.6306 / Math.max(1, view.height)
                        property real backGain: root.ringBackGain
                        property vector3d orbCentre: root.orbCentre
                    }
                }
            }
            Model {
                objectName: "orbOrnaments"
                visible: orbOrnamentPositions.length > 0
                geometry: ProceduralMesh {
                    primitiveMode: ProceduralMesh.Triangles
                    positions: root.orbOrnamentPositions
                    normals: root.orbOrnamentNormals
                    colors: root.orbOrnamentColors
                    uv0s: root.orbOrnamentUvs
                    indexes: root.orbOrnamentIndexes
                }
                materials: CustomMaterial {
                    shadingMode: CustomMaterial.Unshaded
                    vertexShader: "shaders/orb_ornament.vert"
                    fragmentShader: "shaders/orb_ornament.frag"
                    sourceBlend: CustomMaterial.One
                    destinationBlend: CustomMaterial.One
                    depthDrawMode: Material.NeverDepthDraw
                    property vector3d memoryTiltEuler: root.memoryTiltEuler()
                    property vector3d toolsTiltEuler: root.toolsTiltEuler()
                    property vector3d resultsTiltEuler: root.resultsTiltEuler()
                    property real memorySpin: root.memorySpin
                    property real toolsSpin: root.toolsSpin
                    property real resultsScale: root.resultsRadius / root.resultsRingAuthored
                    property real resultsFade: root.resultsFade
                    property real memoryBeadRadius: root.memoryBeadRadius
                    property real toolsBeadRadius: root.toolsBeadRadius
                    property real ringMinPx: root.ringMinPx
                    property real pxAngle: 0.6306 / Math.max(1, view.height)
                    property real backGain: root.ringBackGain
                    property vector3d orbCentre: root.orbCentre
                    property vector3d tint: Qt.vector3d(1, 1, 1)
                    property real gain: 1
                    property vector3d litArc: root.toolsLitArc
                    property real dim: 1
                }
            }
        }
        // Source nodes: one instanced glass draw and one instanced emissive draw.
        // Source nodes: one instanced glass draw and one instanced emissive draw.
        Model {
            objectName: "sourceGlass"
            visible: (root.sourceNodeSpecs || []).length > 0
            instancing: sourceInstanceList
            source: "meshes/source_glass_mesh.mesh"
            materials: PrincipledMaterial {
                baseColor: "#0c0816"
                metalness: 0.9
                roughness: 0.15
                opacity: 0.85
                alphaMode: PrincipledMaterial.Blend
            }
        }
        Model {
            objectName: "sourceEmissive"
            visible: (root.sourceNodeSpecs || []).length > 0
            instancing: sourceInstanceList
            source: "meshes/source_emissive_mesh.mesh"
            materials: CustomMaterial {
                shadingMode: CustomMaterial.Unshaded
                vertexShader: "shaders/source_node.vert"
                fragmentShader: "shaders/source_node.frag"
                sourceBlend: CustomMaterial.One
                destinationBlend: CustomMaterial.One
                depthDrawMode: Material.NeverDepthDraw
                property vector3d spinAxis: Qt.vector3d(0, 1, 0)
                property real spinAngle: 0
                property real spinShear: 0
                property vector3d nodeColor: root.linearVec("#8fd3ff")
                property real lit: 1.0
            }
        }
        Model {
            objectName: "casteBandGuides"
            visible: root.bandGuidePositions.length > 0
            geometry: ProceduralMesh {
                primitiveMode: ProceduralMesh.Lines
                positions: root.bandGuidePositions
                colors: root.bandGuideColors
            }
            materials: PrincipledMaterial {
                lighting: PrincipledMaterial.NoLighting
                vertexColorsEnabled: true
            }
        }
        Model {
            objectName: "tripwirePerimeter"
            y: 0.02
            geometry: ProceduralMesh {
                positions: root.ringPositions(root.perimeterRadius, 0.06)
                normals: root.ringNormals(root.perimeterRadius, 0.06)
                indexes: root.ringIndexes()
            }
            materials: PrincipledMaterial {
                baseColor: root.perimeterColor
                lighting: PrincipledMaterial.NoLighting
            }
        }

        OverseerUnitTex { id: unitTexData; objectName: "overseerUnitTex" }
        OverseerStrandTex { id: strandTexData; objectName: "overseerStrandTex" }

        Repeater3D {
            id: instancedSwarm
            objectName: "instancedSwarm"
            model: root.descriptors
            Model {
                required property var modelData
                objectName: "instanced-" + modelData.key
                source: modelData.source
                // Per-caste models stay in the tree for tests; drawing
                // goes through mergedSwarm (one draw per lod).
                visible: false
                instancing: root.lists[modelData.key]
                materials: [
                    CustomMaterial {
                        shadingMode: CustomMaterial.Unshaded
                        vertexShader: "shaders/sentinel_head.vert"
                        fragmentShader: "shaders/sentinel_head.frag"
                        property real eyeGain: modelData.lod === 0 ? 1.35 : (modelData.lod === 1 ? 1.40 : 2.20)
                        property real rimGain: modelData.lod === 0 ? 0.020 : (modelData.lod === 1 ? 0.030 : 0.060)
                        property real seamGain: modelData.lod === 0 ? 0.45 : (modelData.lod === 1 ? 0.50 : 1.00)
                        property real hullMetal: 0.55
                        property real hullRough: 0.38
                        property vector3d ambSky: Qt.vector3d(0.1000, 0.1050, 0.1300)
                        property vector3d ambGround: Qt.vector3d(0.0300, 0.0300, 0.0350)
                        property real edgeGain: 1.20
                        property real eyeMinPx: modelData.lod === 0 ? 0.0 : (modelData.lod === 1 ? 1.6 : 3.0)
                        property real eyeRadiusMul: modelData.lod === 2 ? 1.5 : 1.0
                        property real uViewportH: Math.max(1, view.height)
                        property vector3d keyDir: root.lightKeyDir
                        property vector3d fillDir: root.lightFillDir
                        property real keyGain: 1.00
                        property real fillGain: 0.35
                        property real specGain: 1.00
                        property real unitFog: 0.30
                    }
                ]
            }
        }

        Repeater3D {
            id: mergedSwarm
            objectName: "mergedSwarm"
            model: root.mergedDescriptors
            Model {
                required property var modelData
                objectName: "instanced-merged-" + modelData.key
                source: modelData.source
                visible: !root.coreMode && (root.mergedCounts[modelData.key] || 0) > 0
                instancing: (modelData.lod === 0 ? mergedHead0List : (modelData.lod === 1 ? mergedHead1List : mergedHead2List))
                materials: [
                    CustomMaterial {
                        shadingMode: CustomMaterial.Unshaded
                        vertexShader: "shaders/sentinel_head.vert"
                        fragmentShader: "shaders/sentinel_head.frag"
                        property real eyeGain: modelData.lod === 0 ? 1.35 : (modelData.lod === 1 ? 1.40 : 2.20)
                        property real rimGain: modelData.lod === 0 ? 0.020 : (modelData.lod === 1 ? 0.030 : 0.060)
                        property real seamGain: modelData.lod === 0 ? 0.45 : (modelData.lod === 1 ? 0.50 : 1.00)
                        property real hullMetal: 0.55
                        property real hullRough: 0.38
                        property vector3d ambSky: Qt.vector3d(0.1000, 0.1050, 0.1300)
                        property vector3d ambGround: Qt.vector3d(0.0300, 0.0300, 0.0350)
                        property real edgeGain: 1.20
                        property real eyeMinPx: modelData.lod === 0 ? 0.0 : (modelData.lod === 1 ? 1.6 : 3.0)
                        property real eyeRadiusMul: modelData.lod === 2 ? 1.5 : 1.0
                        property real uViewportH: Math.max(1, view.height)
                        property vector3d keyDir: root.lightKeyDir
                        property vector3d fillDir: root.lightFillDir
                        property real keyGain: 1.00
                        property real fillGain: 0.35
                        property real specGain: 1.00
                        property real unitFog: 0.30
                    }
                ]
            }
        }

        Model {
            objectName: "tentacleLod2"
            visible: !root.coreMode && (root.tentacleCounts["2"] || 0) > 0
            instancing: tentacleLod2List
            source: "meshes/sentinel_tentacle_lod2_mesh.mesh"
            materials: CustomMaterial {
                shadingMode: CustomMaterial.Unshaded
                cullMode: Material.NoCulling
                vertexShader: "shaders/sentinel_tentacle.vert"
                fragmentShader: "shaders/sentinel_tentacle_lod2.frag"
                property real lod: 2
                property real slitGain: 1.10
                property real rimGain: 0.350
                property real ribbonLight: 1.00
                property real ribbonWidth: 1.70
                property real ribbonMinPx: 1.25
                property real uTime: root.sceneTime
                property real uViewportH: Math.max(1, view.height)
                property vector3d baseMetal: Qt.vector3d(Math.pow(0x2c/255.0, 2.2), Math.pow(0x2f/255.0, 2.2), Math.pow(0x36/255.0, 2.2))
                property vector3d clawMetal: Qt.vector3d(Math.pow(0x5a/255.0, 2.2), Math.pow(0x5e/255.0, 2.2), Math.pow(0x66/255.0, 2.2))
                property vector3d keyDir: root.lightKeyDir
                property vector3d fillDir: root.lightFillDir
                property TextureInput unitTex: TextureInput {
                    texture: Texture {
                        textureData: unitTexData
                        minFilter: Texture.Nearest
                        magFilter: Texture.Nearest
                        tilingModeHorizontal: Texture.ClampToEdge
                        tilingModeVertical: Texture.ClampToEdge
                    }
                }
                property TextureInput strandTex: TextureInput {
                    texture: Texture {
                        textureData: strandTexData
                        minFilter: Texture.Nearest
                        magFilter: Texture.Nearest
                        tilingModeHorizontal: Texture.ClampToEdge
                        tilingModeVertical: Texture.ClampToEdge
                    }
                }
            }
        }
        Model {
            objectName: "tentacleLod1"
            visible: !root.coreMode && (root.tentacleCounts["1"] || 0) > 0
            instancing: tentacleLod1List
            source: "meshes/sentinel_tentacle_lod1_mesh.mesh"
            materials: CustomMaterial {
                shadingMode: CustomMaterial.Unshaded
                vertexShader: "shaders/sentinel_tentacle.vert"
                fragmentShader: "shaders/sentinel_tentacle.frag"
                property real lod: 1
                property real slitGain: 0.55
                property real rimGain: 0.100
                property real ribbonLight: 0.5
                property real tentMetal: 0.55
                property real tentRough: 0.34
                property vector3d ambSky: Qt.vector3d(0.1000, 0.1050, 0.1300)
                property vector3d ambGround: Qt.vector3d(0.0300, 0.0300, 0.0350)
                property real edgeGain: 1.20
                property real keyGain: 1.00
                property real fillGain: 0.35
                property real specGain: 1.00
                property real unitFog: 0.30
                property real ribbonWidth: 1.0
                property real ribbonMinPx: 1.0
                property real uTime: root.sceneTime
                property real uViewportH: Math.max(1, view.height)
                property vector3d baseMetal: Qt.vector3d(Math.pow(0x2c/255.0, 2.2), Math.pow(0x2f/255.0, 2.2), Math.pow(0x36/255.0, 2.2))
                property vector3d clawMetal: Qt.vector3d(Math.pow(0x5a/255.0, 2.2), Math.pow(0x5e/255.0, 2.2), Math.pow(0x66/255.0, 2.2))
                property vector3d keyDir: root.lightKeyDir
                property vector3d fillDir: root.lightFillDir
                property TextureInput unitTex: TextureInput {
                    texture: Texture {
                        textureData: unitTexData
                        minFilter: Texture.Nearest
                        magFilter: Texture.Nearest
                        tilingModeHorizontal: Texture.ClampToEdge
                        tilingModeVertical: Texture.ClampToEdge
                    }
                }
                property TextureInput strandTex: TextureInput {
                    texture: Texture {
                        textureData: strandTexData
                        minFilter: Texture.Nearest
                        magFilter: Texture.Nearest
                        tilingModeHorizontal: Texture.ClampToEdge
                        tilingModeVertical: Texture.ClampToEdge
                    }
                }
            }
        }
        Model {
            objectName: "tentacleLod0"
            visible: !root.coreMode && (root.tentacleCounts["0"] || 0) > 0
            instancing: tentacleLod0List
            source: "meshes/sentinel_tentacle_lod0_mesh.mesh"
            materials: CustomMaterial {
                shadingMode: CustomMaterial.Unshaded
                vertexShader: "shaders/sentinel_tentacle.vert"
                fragmentShader: "shaders/sentinel_tentacle.frag"
                property real lod: 0
                property real slitGain: 0.42
                property real rimGain: 0.080
                property real ribbonLight: 0.5
                property real tentMetal: 0.55
                property real tentRough: 0.34
                property vector3d ambSky: Qt.vector3d(0.1000, 0.1050, 0.1300)
                property vector3d ambGround: Qt.vector3d(0.0300, 0.0300, 0.0350)
                property real edgeGain: 1.20
                property real keyGain: 1.00
                property real fillGain: 0.35
                property real specGain: 1.00
                property real unitFog: 0.30
                property real ribbonWidth: 1.0
                property real ribbonMinPx: 1.0
                property real uTime: root.sceneTime
                property real uViewportH: Math.max(1, view.height)
                property vector3d baseMetal: Qt.vector3d(Math.pow(0x2c/255.0, 2.2), Math.pow(0x2f/255.0, 2.2), Math.pow(0x36/255.0, 2.2))
                property vector3d clawMetal: Qt.vector3d(Math.pow(0x5a/255.0, 2.2), Math.pow(0x5e/255.0, 2.2), Math.pow(0x66/255.0, 2.2))
                property vector3d keyDir: root.lightKeyDir
                property vector3d fillDir: root.lightFillDir
                property TextureInput unitTex: TextureInput {
                    texture: Texture {
                        textureData: unitTexData
                        minFilter: Texture.Nearest
                        magFilter: Texture.Nearest
                        tilingModeHorizontal: Texture.ClampToEdge
                        tilingModeVertical: Texture.ClampToEdge
                    }
                }
                property TextureInput strandTex: TextureInput {
                    texture: Texture {
                        textureData: strandTexData
                        minFilter: Texture.Nearest
                        magFilter: Texture.Nearest
                        tilingModeHorizontal: Texture.ClampToEdge
                        tilingModeVertical: Texture.ClampToEdge
                    }
                }
            }
        }

        Model {
            objectName: "dataConduitCloud"
            source: "#Sphere"
            visible: (root.liveCounts["__conduits"] || 0) > 0
            instancing: root.conduitList
            materials: PrincipledMaterial {
                lighting: PrincipledMaterial.NoLighting
                baseColor: "#ffffff"
                emissiveFactor: Qt.vector3d(0.95, 0.95, 1.0)
            }
        }

        Model {
            objectName: "glyphTrails"
            source: "#Rectangle"
            visible: root.glyphCount > 0
            instancing: root.glyphList
            materials: CustomMaterial {
                shadingMode: CustomMaterial.Unshaded
                vertexShader: "shaders/glyph.vert"
                fragmentShader: "shaders/glyph.frag"
                sourceBlend: CustomMaterial.One
                destinationBlend: CustomMaterial.One
                cullMode: Material.NoCulling
                depthDrawMode: Material.NeverDepthDraw
                property real uTime: root.sceneTime
                property TextureInput uAtlas: TextureInput {
                    texture: Texture {
                        // ASCII 32..127 in a 16 x 6 grid, white on clear; the shader tints it.
                        sourceItem: Item {
                            width: 1024
                            height: 384
                            Repeater {
                                model: 96
                                Text {
                                    required property int index
                                    x: (index % 16) * 64
                                    y: Math.floor(index / 16) * 64
                                    width: 64
                                    height: 64
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    font.family: root.glyphFontFamily
                                    font.pixelSize: 44
                                    color: Qt.rgba(1, 1, 1, 1)
                                    text: String.fromCharCode(32 + index)
                                }
                            }
                        }
                    }
                }
            }
        }

        Model {
            objectName: "entryParticleCloud"
            source: "#Sphere"
            // #Sphere is 100 units; this model scale keeps a leaked
            // instance scale of 1 at 0.12 m instead of 100 m.
            scale: Qt.vector3d(0.0012, 0.0012, 0.0012)
            visible: (root.liveCounts["__particles"] || 0) > 0
            instancing: root.particleList
            materials: PrincipledMaterial {
                lighting: PrincipledMaterial.NoLighting
                baseColor: "#d9ccff"
                emissiveFactor: Qt.vector3d(0.85, 0.82, 1.0)
            }
        }

        // Starfield: 3 parallax layers, 1,000 points, one ProceduralMesh draw.
        // The vertex shader turns each layer about the hive axis at its rate.
        Model {
            objectName: "starLayers"
            visible: root.starPositions.length > 0
            geometry: ProceduralMesh {
                primitiveMode: ProceduralMesh.Triangles
                positions: root.starPositions
                colors: root.starColors
                uv0s: root.starUv0s
                uv1s: root.starUv1s
                indexes: root.starIndexes
            }
            materials: CustomMaterial {
                shadingMode: CustomMaterial.Unshaded
                vertexShader: "shaders/star.vert"
                fragmentShader: "shaders/star.frag"
                sourceBlend: CustomMaterial.One
                destinationBlend: CustomMaterial.One
                cullMode: Material.NoCulling
                depthDrawMode: Material.NeverDepthDraw
                property real uViewportW: Math.max(1, view.width)
                property real uViewportH: Math.max(1, view.height)
                property real uStarDrift: root.starDrift
            }
        }
    }

    Rectangle {
        id: edgeStroke
        anchors.fill: parent
        color: "transparent"
        radius: 28
        border.color: "#a78bfa"
        border.width: 2
        opacity: 0.75 * root.edge
        z: 2
        transform: Scale {
            origin.x: edgeStroke.width - 46
            origin.y: 48
            xScale: 0.2 + 0.8 * root.edge
            yScale: 0.2 + 0.8 * root.edge
        }
    }

    // Fixed harvest source labels at the scene edge (projected from 3D). One
    // delegate per source for the life of the scene: the model is a count, so
    // a new projection only moves the labels. Same size lit or idle (Iris
    // concept 1: name bold, state line below); lit reads brighter.
    Repeater {
        model: root.sourceLabelScreen.length
        delegate: Column {
            id: srcLabel
            required property int index
            readonly property var row: root.sourceLabelScreen[index] || ({})
            objectName: "OverseerSourceLabel_" + (row.id || index)
            visible: !!row.visible
            x: (row.sx || 0) - width * 0.5
            y: (row.sy || 0) + 14
            z: 2
            spacing: 1
            Accessible.role: Accessible.StaticText
            Accessible.name: (row.label || "") + ", " + stateText.text
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: srcLabel.row.label || ""
                color: "#e8dcfb"
                font.pixelSize: 20
                font.bold: true
                style: Text.Outline
                styleColor: "#0b0714"
            }
            Text {
                id: stateText
                anchors.horizontalCenter: parent.horizontalCenter
                text: srcLabel.row.status || (srcLabel.row.hot ? "fetching" : "idle")
                color: "#8fd3ff"
                opacity: srcLabel.row.hot ? 1.0 : 0.75
                font.pixelSize: 15
                style: Text.Outline
                styleColor: "#0b0714"
            }
        }
    }

    Repeater {
        model: root.orbLeaders
        delegate: Rectangle {
            required property var modelData
            objectName: "OverseerOrbLeader_" + (modelData.id || index)
            z: 2
            height: 1
            width: Math.hypot((modelData.x2 || 0) - (modelData.x1 || 0), (modelData.y2 || 0) - (modelData.y1 || 0))
            x: modelData.x1 || 0
            y: (modelData.y1 || 0) - 0.5
            color: Qt.rgba(0xa4 / 255, 0x73 / 255, 0xf0 / 255, 0.6)
            rotation: Math.atan2((modelData.y2 || 0) - (modelData.y1 || 0), (modelData.x2 || 0) - (modelData.x1 || 0)) * 180 / Math.PI
            transformOrigin: Item.Left
        }
    }

    Repeater {
        model: root.orbDots
        delegate: Rectangle {
            required property var modelData
            objectName: "OverseerOrbDot_" + (modelData.id || index)
            z: 2
            width: 6
            height: 6
            radius: 3
            color: "#d2b9f8"
            x: (modelData.x || 0) - 3
            y: (modelData.y || 0) - 3
        }
    }

    Repeater {
        model: root.orbLabelBlocks
        delegate: Item {
            required property var modelData
            objectName: "OverseerOrbLabel_" + (modelData.id || index)
            x: modelData.x || 0
            y: modelData.y || 0
            z: 2
            width: modelData.kind === "chip" ? (modelData.w || 0) : col.implicitWidth
            height: modelData.kind === "chip" ? (modelData.h || 0) : col.implicitHeight
            Accessible.role: Accessible.StaticText
            Accessible.name: modelData.kind === "chip" ? (modelData.text || "") : ((modelData.title || "") + " " + (modelData.status || ""))

            Rectangle {
                anchors.fill: parent
                visible: modelData.kind === "chip"
                radius: 4
                color: Qt.rgba(0x14 / 255, 0x0b / 255, 0x20 / 255, 0.85)
                border.color: "#a473f0"
                border.width: 1
            }
            Text {
                visible: modelData.kind === "chip"
                anchors.centerIn: parent
                text: modelData.text || ""
                color: "#e8dcfb"
                font.family: root.glyphFontFamily
                font.pixelSize: 15
            }
            Column {
                id: col
                visible: modelData.kind === "block"
                spacing: 1
                width: implicitWidth
                Text {
                    text: modelData.title || ""
                    color: modelData.titleColor || "#ffffff"
                    font.family: root.hudSansFamily
                    font.pixelSize: modelData.titleSize || 25
                    font.weight: Font.Medium
                    style: Text.Outline
                    styleColor: "#0b0714"
                    anchors.horizontalCenter: modelData.align === "centre" ? parent.horizontalCenter : undefined
                }
                Text {
                    text: modelData.status || ""
                    color: modelData.statusColor || "#cdb2f7"
                    font.family: root.hudSansFamily
                    font.pixelSize: modelData.statusSize || 18
                    style: Text.Outline
                    styleColor: "#0b0714"
                    anchors.horizontalCenter: modelData.align === "centre" ? parent.horizontalCenter : undefined
                }
            }
        }
    }

    Repeater {
        model: root.orbChips
        delegate: Rectangle {
            required property var modelData
            objectName: "OverseerOrbChip_" + (modelData.id || index)
            x: modelData.x || 0
            y: modelData.y || 0
            z: 2
            width: modelData.w || 0
            height: modelData.h || 0
            radius: 4
            color: Qt.rgba(0x14 / 255, 0x0b / 255, 0x20 / 255, 0.85)
            border.color: "#a473f0"
            border.width: 1
            Text {
                anchors.centerIn: parent
                text: modelData.text || ""
                color: "#e8dcfb"
                font.family: root.glyphFontFamily
                font.pixelSize: 16
            }
        }
    }

    Repeater {
        model: root.orbGlyphs
        delegate: Text {
            required property var modelData
            objectName: "OverseerOrbGlyph_" + (modelData.id || index)
            x: (modelData.x || 0) - width / 2
            y: (modelData.y || 0) - height / 2
            z: 2
            text: modelData.text || ""
            color: Qt.rgba(0xb9 / 255, 0xa7 / 255, 0xe0 / 255, 0.78)
            font.family: root.glyphFontFamily
            font.pixelSize: 17
            rotation: modelData.rot || 0
            transformOrigin: Item.Center
        }
    }


    OverseerCloseMote { flight: root.moteFlight }

    OverseerHud {
        id: chrome
        objectName: "OverseerHud"
        z: 3
        visible: root.reveal > 0.35 || root.inputLive
        pills: root.hudPills
        swarmRows: root.swarmRows
        inspector: root.inspectorCard
        logs: root.hudLogs
        replayTicks: root.replayTicks
        tokRate: root.tokRate
        coreMode: root.coreMode
        logRepeats: root.logRepeats
        inspectorOpen: root.showInspector
        selectedUnitId: root.selectedUnitId
        unitFocused: root.unitFocused
        groupBy: root.swarmGroupBy
        statusLine: root.hudStatusLine
        commandStatus: root.hudCommandStatus
        missionMode: root.missionMode
        missionQuery: root.missionQuery
        onSearchEdited: function (text) { root.swarmSearch = text }
        onGroupModeChosen: function (mode) { root.swarmGroupBy = mode }
        onHeaderToggled: function (key) {
            var next = root.collapsedGroups ? root.collapsedGroups.slice() : []
            var at = next.indexOf(key)
            if (at >= 0)
                next.splice(at, 1)
            else
                next.push(key)
            root.collapsedGroups = next
        }
        onUnitChosen: function (unitId) { root.selectUnit(unitId) }
        onLogFilterChosen: function (name) { root.logFilter = name }
        onLogSearchEdited: function (text) { root.logQuery = text }
        onLogRepeatsChosen: function (on) { root.logRepeats = on }
        onHudCommand: function (name, payload) {
            root.lastHudCommand = name
            root.lastHudPayload = payload
            if (name === "focus" && payload && payload.unit_id) {
                root.selectUnit(payload.unit_id)
                root.focusSelectedUnit()
            }
            if (name === "fit_swarm" || name === "fitSwarm")
                root.fitSwarm()
            if (name === "core_focus" || name === "coreFocus")
                root.enterCoreFocus()
            if (name === "exit_core" || name === "exitCore")
                root.exitCoreFocus()
        }
    }


    function _fmtDumpNum(n) {
        if (n === undefined || n === null)
            return ""
        var v = Number(n)
        if (v !== v)
            return ""
        return String(v)
    }

    function _tryMapFrom3DScene(world) {
        if (!view || !view.camera || world === undefined || world === null)
            return null
        try {
            return view.mapFrom3DScene(world)
        } catch (err) {
            return null
        }
    }

    function _tryAppendMatrix(parts, label, node, propName) {
        if (!node || !parts)
            return
        var m = node[propName]
        if (m === undefined || m === null)
            return
        try {
            if (m.m11 === undefined)
                return
            parts.push(label + "=" + m.m11 + "," + m.m12 + "," + m.m13 + "," + m.m14 + "," + m.m21 + "," + m.m22 + "," + m.m23 + "," + m.m24 + "," + m.m31 + "," + m.m32 + "," + m.m33 + "," + m.m34 + "," + m.m41 + "," + m.m42 + "," + m.m43 + "," + m.m44)
        } catch (err) {
        }
    }

    function frameDump() {
        var rec = (instanceRecords && selectedUnitId) ? instanceRecords[selectedUnitId] : null
        var remembered = unitPositionOf(selectedUnitId)
        var sh = freeViewportShift()
        var aspect = (height > 1 && width > 1) ? (width / height) : Number.NaN
        var parts = []
        parts.push("frameId=" + placementFrameId)
        parts.push("selectedId=" + (selectedUnitId || ""))
        parts.push("selectedCaste=" + (rec && rec.caste ? rec.caste : ""))
        parts.push("modelKey=" + (rec && rec.modelKey ? rec.modelKey : ""))
        parts.push("instanceColor=" + (rec ? String(rec.color || "") : ""))
        parts.push("instanceScale=" + (rec ? _fmtDumpNum(rec.scale) : ""))
        parts.push("instanceX=" + (rec ? _fmtDumpNum(rec.x) : ""))
        parts.push("instanceY=" + (rec ? _fmtDumpNum(rec.y) : ""))
        parts.push("instanceZ=" + (rec ? _fmtDumpNum(rec.z) : ""))
        parts.push("instanceHeading=" + (rec ? _fmtDumpNum(rec.heading) : ""))
        parts.push("rememberedX=" + (remembered ? _fmtDumpNum(remembered.x) : ""))
        parts.push("rememberedY=" + (remembered ? _fmtDumpNum(remembered.y) : ""))
        parts.push("rememberedZ=" + (remembered ? _fmtDumpNum(remembered.z) : ""))
        parts.push("cameraMode=" + cameraMode)
        parts.push("cameraDistance=" + _fmtDumpNum(cameraDistance))
        parts.push("cameraPitch=" + _fmtDumpNum(cameraPitch))
        parts.push("cameraTargetX=" + _fmtDumpNum(cameraTargetX))
        parts.push("cameraTargetY=" + _fmtDumpNum(cameraTargetY))
        parts.push("cameraTargetZ=" + _fmtDumpNum(cameraTargetZ))
        parts.push("cameraFov=" + (cam ? _fmtDumpNum(cam.fieldOfView) : ""))
        parts.push("cameraAspect=" + _fmtDumpNum(aspect))
        parts.push("lensShiftX=" + _fmtDumpNum(sh.x))
        parts.push("lensShiftY=" + _fmtDumpNum(sh.y))
        if (cam && cam.position) {
            parts.push("cameraPosX=" + _fmtDumpNum(cam.position.x))
            parts.push("cameraPosY=" + _fmtDumpNum(cam.position.y))
            parts.push("cameraPosZ=" + _fmtDumpNum(cam.position.z))
            parts.push("cameraEulerX=" + _fmtDumpNum(cam.eulerRotation.x))
            parts.push("cameraEulerY=" + _fmtDumpNum(cam.eulerRotation.y))
            parts.push("cameraEulerZ=" + _fmtDumpNum(cam.eulerRotation.z))
        }
        if (cam && cam.scenePosition) {
            parts.push("cameraSceneX=" + _fmtDumpNum(cam.scenePosition.x))
            parts.push("cameraSceneY=" + _fmtDumpNum(cam.scenePosition.y))
            parts.push("cameraSceneZ=" + _fmtDumpNum(cam.scenePosition.z))
        }
        _tryAppendMatrix(parts, "cameraSceneTransform", cam, "sceneTransform")
        _tryAppendMatrix(parts, "cameraViewMatrix", cam, "viewMatrix")
        _tryAppendMatrix(parts, "cameraProjection", cam, "projection")
        _tryAppendMatrix(parts, "cameraProjectionMatrix", cam, "projectionMatrix")
        if (rec) {
            var mapped = _tryMapFrom3DScene(Qt.vector3d(rec.x, rec.y, rec.z))
            if (mapped) {
                parts.push("projectedInstanceX=" + _fmtDumpNum(mapped.x))
                parts.push("projectedInstanceY=" + _fmtDumpNum(mapped.y))
                parts.push("projectedInstanceZ=" + _fmtDumpNum(mapped.z))
            }
        }
        var mappedT = _tryMapFrom3DScene(Qt.vector3d(cameraTargetX, cameraTargetY, cameraTargetZ))
        if (mappedT) {
            parts.push("projectedTargetX=" + _fmtDumpNum(mappedT.x))
            parts.push("projectedTargetY=" + _fmtDumpNum(mappedT.y))
            parts.push("projectedTargetZ=" + _fmtDumpNum(mappedT.z))
        }
        parts.push("viewW=" + _fmtDumpNum(width))
        parts.push("viewH=" + _fmtDumpNum(height))
        return parts.join(" ")
    }

    // Named readonly values for external UIA/log reads. Transparent so
    // they do not add chrome or clipped pixels. Empty string if a live
    // property is not a number — never a fabricated default.
    function cameraEvidenceLabel() {
        var ev = cameraEvidence()
        var parts = []
        var keys = ["cameraDistance", "cameraPitch", "cameraTargetX", "cameraTargetY", "cameraTargetZ", "selectedUnitId", "framing", "cameraMode"]
        for (var i = 0; i < keys.length; i++) {
            var key = keys[i]
            if (ev[key] === undefined || ev[key] === null || ev[key] === "")
                continue
            parts.push(key + "=" + ev[key])
        }
        return parts.join(" ")
    }

    Text {
        id: cameraEvidenceText
        objectName: "OverseerCameraEvidence"
        z: 4
        visible: true
        color: "transparent"
        font.pixelSize: 1
        text: root.cameraEvidenceLabel()
        Accessible.role: Accessible.StaticText
        Accessible.ignored: false
        Accessible.name: text
    }
    Text {
        objectName: "OverseerCameraDistance"
        visible: true
        color: "transparent"
        font.pixelSize: 1
        text: Number.isFinite(root.cameraDistance) ? String(root.cameraDistance) : ""
        Accessible.role: Accessible.StaticText
        Accessible.ignored: false
        Accessible.name: text
    }
    Text {
        objectName: "OverseerCameraPitch"
        visible: true
        color: "transparent"
        font.pixelSize: 1
        text: Number.isFinite(root.cameraPitch) ? String(root.cameraPitch) : ""
        Accessible.role: Accessible.StaticText
        Accessible.ignored: false
        Accessible.name: text
    }
    Text {
        objectName: "OverseerCameraTargetX"
        visible: true
        color: "transparent"
        font.pixelSize: 1
        text: Number.isFinite(root.cameraTargetX) ? String(root.cameraTargetX) : ""
        Accessible.role: Accessible.StaticText
        Accessible.ignored: false
        Accessible.name: text
    }
    Text {
        objectName: "OverseerCameraTargetY"
        visible: true
        color: "transparent"
        font.pixelSize: 1
        text: Number.isFinite(root.cameraTargetY) ? String(root.cameraTargetY) : ""
        Accessible.role: Accessible.StaticText
        Accessible.ignored: false
        Accessible.name: text
    }
    Text {
        objectName: "OverseerCameraTargetZ"
        visible: true
        color: "transparent"
        font.pixelSize: 1
        text: Number.isFinite(root.cameraTargetZ) ? String(root.cameraTargetZ) : ""
        Accessible.role: Accessible.StaticText
        Accessible.ignored: false
        Accessible.name: text
    }
    Text {
        objectName: "OverseerCameraSelectedUnitId"
        visible: true
        color: "transparent"
        font.pixelSize: 1
        text: root.selectedUnitId || ""
        Accessible.role: Accessible.StaticText
        Accessible.ignored: false
        Accessible.name: text
    }
    Text {
        objectName: "OverseerCameraFraming"
        visible: true
        color: "transparent"
        font.pixelSize: 1
        text: root.framingName()
        Accessible.role: Accessible.StaticText
        Accessible.ignored: false
        Accessible.name: text
    }
    Text {
        objectName: "OverseerCameraMode"
        visible: true
        color: "transparent"
        font.pixelSize: 1
        text: root.cameraMode || ""
        Accessible.role: Accessible.StaticText
        Accessible.ignored: false
        Accessible.name: text
    }
    Text {
        objectName: "OverseerFrameDump"
        visible: true
        color: "transparent"
        font.pixelSize: 1
        text: root.frameDump()
        Accessible.role: Accessible.StaticText
        Accessible.ignored: false
        Accessible.name: text
    }
}

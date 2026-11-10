import QtQuick
import QtQuick3D
import QtQuick3D.Helpers

Item {
    id: root
    objectName: "OverseerView"
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
    property var meshTris: ({
        "0:hull": 10882, "0:emissive": 1087, "0:lens": 28,
        "1:hull": 3570, "1:emissive": 403, "1:lens": 32,
        "2:hull": 628, "2:emissive": 363, "2:lens": 20
    })
    property var lists: ({})
    property var descriptors: []
    property var particleList: null
    property var conduitList: null
    property var conduitSpecs: []
    property var unitAnimSpecs: []
    property var liveCounts: ({})
    onSceneTimeChanged: root.stepConduits()
    property var hudPills: ({})
    property var swarmRows: []
    property var inspectorCard: ({})
    property var hudLogs: []
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
    readonly property int msaaSamples: 4
    readonly property int glowLevels: 3
    readonly property real glowThreshold: 1.0
    readonly property real eyeEmission: 2.4
    // Smallest on-screen eye radius in px, so every eye feeds the bloom.
    readonly property real eyeMinPx: 2.0
    // Lane guides stay soft: edge lanes 0.28, middle lanes 0.16 of caste colour.
    readonly property real laneEdgeEmission: 0.28
    readonly property real laneMidEmission: 0.16
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
    property real hiveActivity: 0
    property real hiveActivityShown: 0
    property real starDrift: 0

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
        ensureLists()
        releaseAllLists()
        var buckets = frame.buckets
        var counts = ({})
        var used = 0
        var tris = 0
        var lods = [0, 0, 0]
        var live = 0
        var animSpecs = []
        for (var ci = 0; ci < casteIds.length; ci++) {
            var caste = casteIds[ci]
            for (var lod = 0; lod < 3; lod++) {
                var rows = buckets[caste + ":" + lod] || []
                lods[lod] += rows.length
                for (var pi = 0; pi < 3; pi++) {
                    var part = ["hull", "emissive", "lens"][pi]
                    var key = caste + ":" + lod + ":" + part
                    var lst = lists[key]
                    if (!lst)
                        continue
                    var entries = []
                    for (var i = 0; i < rows.length; i++) {
                        var row = rows[i]
                        var uEntry = fillUnitEntry(row, caste, key, recs)
                        entries.push(uEntry)
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
                        var mt = meshTris[lod + ":" + part] || 0
                        tris += mt * entries.length
                    }
                }
            }
        }
        unitAnimSpecs = animSpecs
        reachState = reachNext
        counts["__particles"] = 0
        var cEntries = fillConduitEntries(frame.conduits || [])
        counts["__conduits"] = cEntries.length
        live += cEntries.length
        applyGlyphTrails(frame.glyphTrails || [])
        applyBands(frame.bands || [], frame.perimeter)
        hiveActivity = Math.max(0, Math.min(1, finiteNum(frame.hiveActivity, 0)))
        counts["__glyphs"] = glyphCount
        live += glyphCount
        liveCounts = counts
        budgetTris = tris
        unitDrawCalls = used
        budgetDrawCalls = used + 11  // SCENE_FIXED_DRAW: fixed scene draws plus 3 star layers
        lodCounts = lods
        recountEntries(live)
        instanceRecords = recs
        rememberUnitPositions(buckets)
        sourceLabelSpecs = frame.sourceLabels || []
        updateOverview()
        projectSourceLabels()
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
            cameraMode: cameraMode
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
        return unitPositions[unitId] || null
    }

    function syncCameraTargetFromSelection() {
        if (cameraMode === "fit" || cameraMode === "ease")
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
        conduitSpecs = []
        unitAnimSpecs = []
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
        var sc = finiteNum(row.scale, 0.36)
        if (sc < 0.20)
            sc = 0.20
        if (sc > 2.0)
            sc = 2.0
        e.scale = Qt.vector3d(sc, sc, sc)
        // Lens instances carry the eye colour (fetching and engaged eyes differ).
        e.color = (String(key).indexOf(":lens") >= 0 && row.eye) ? row.eye : (row.color || casteColors[caste])
        var uid = row && row.unit_id ? row.unit_id : ""
        var rs = reachSlot(uid, row.reach)
        // y packs claw + 2*reach + 8*previous reach + 32*limp; z is when reach changed.
        var claw = Math.min(0.99, Math.max(0, finiteNum(row.claw, 0.45) || 0.45))
        var limp = row.limp ? 1 : 0
        e.customData = Qt.vector4d(row.phase || 0, claw + 2 * rs.n + 8 * rs.prev + 32 * limp, rs.t, (row.speed === undefined || row.speed === null) ? 1.0 : row.speed)
        if (uid && recs) {
            if (!recs[uid] || String(key).indexOf(":hull") >= 0) {
                recs[uid] = {
                    unit_id: uid,
                    caste: caste,
                    modelKey: key || "",
                    x: e.position.x,
                    y: e.position.y,
                    z: e.position.z,
                    scale: sc,
                    color: String(e.color),
                    heading: -finiteNum(row.heading_deg)
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
        var key = String(finiteNum(perimeter, 35))
        for (var i = 0; i < list.length; i++) {
            var lanes = list[i].lanes || []
            for (var li = 0; li < lanes.length; li++)
                key += "|" + list[i].caste + ":" + lanes[li].r
        }
        if (key === bandKey)
            return
        bandKey = key
        bandSpecs = list
        perimeterRadius = finiteNum(perimeter, 35)
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
                var k = edge ? root.laneEdgeEmission : root.laneMidEmission
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

    function recountEntries(live) {
        liveEntryCount = live
        pooledEntryCount = entryPool ? entryPool.length : 0
        totalEntryCount = liveEntryCount + pooledEntryCount
    }

    function applyWheel(notches) {
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
                var parts = ["hull", "emissive", "lens"]
                for (var pi = 0; pi < 3; pi++) {
                    var part = parts[pi]
                    var key = casteIds[ci] + ":" + lod + ":" + part
                    next[key] = Qt.createQmlObject("import QtQuick3D; InstanceList {}", root)
                    desc.push({
                        key: key,
                        caste: casteIds[ci],
                        lod: lod,
                        part: part,
                        source: "meshes/lod" + lod + "_" + part + "_mesh.mesh"
                    })
                }
            }
        }
        lists = next
        descriptors = desc
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
                sx: sx,
                sy: sy,
                visible: visible
            }
            key += row.id + ":" + row.label + ":" + row.hot + ":" + row.color + ":" + sx + ":" + sy + ":" + visible + "|"
            out.push(row)
        }
        if (key === sourceLabelKey)
            return
        sourceLabelKey = key
        sourceLabelScreen = out
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

    function stepUnits(dt) {
        var specs = unitAnimSpecs
        if (!specs || !specs.length || dt <= 0)
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
        running: true
        onTriggered: {
            root.sceneTime += frameTime
            root.stepUnits(frameTime)
            // Ease activity over about 0.5 s, then drift the star layers with it.
            var k = Math.min(1, frameTime / 0.5)
            root.hiveActivityShown += (root.hiveActivity - root.hiveActivityShown) * k
            root.starDrift += frameTime * (0.25 + 2.75 * root.hiveActivityShown)
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
        environment: ExtendedSceneEnvironment {
            objectName: "overseerEnvironment"
            backgroundMode: SceneEnvironment.Color
            // The scene used to draw a 1600 m lit floor plane under everything.
            // At every approved camera it filled the whole view with one flat
            // dark grey (15, 14, 17 after the filmic tonemap), a full screen of
            // lit fragments per frame. This clear colour tonemaps to the same
            // grey, so the floor plane and its fill are gone.
            clearColor: root.skyColor
            tonemapMode: ExtendedSceneEnvironment.TonemapModeFilmic
            antialiasingMode: root.msaaSamples > 1 ? SceneEnvironment.MSAA : SceneEnvironment.NoAA
            antialiasingQuality: root.msaaSamples >= 8 ? SceneEnvironment.VeryHigh
                                 : (root.msaaSamples >= 4 ? SceneEnvironment.High : SceneEnvironment.Medium)
            // Bloom: only HDR values over the threshold (eyes, beams, source
            // cores) glow; hulls, lanes and the perimeter stay under it.
            glowEnabled: root.glowLevels > 0
            glowHDRMinimumValue: root.glowThreshold
            glowLevel: (1 << root.glowLevels) - 1
            glowStrength: 1.2
            glowIntensity: 1.4
            glowBloom: 0.0
            glowBlendMode: ExtendedSceneEnvironment.GlowBlendMode.Additive
            fog: Fog {
                enabled: true
                color: root.fogColor
                density: 0.6
                depthEnabled: true
                depthNear: root.fogNear
                depthFar: root.fogFar
            }
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

        Model {
            objectName: "hiveCore"
            source: "#Sphere"
            scale: Qt.vector3d(0.022, 0.022, 0.022)
            materials: PrincipledMaterial {
                baseColor: "#3b2a66"; metalness: 0.4; roughness: 0.2
                emissiveFactor: Qt.vector3d(0.45, 0.35, 0.75)
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

        Repeater3D {
            id: instancedSwarm
            objectName: "instancedSwarm"
            model: root.descriptors
            Model {
                required property var modelData
                objectName: "instanced-" + modelData.key
                source: modelData.source
                visible: (root.liveCounts[modelData.key] || 0) > 0
                instancing: root.lists[modelData.key]
                materials: [
                    CustomMaterial {
                        shadingMode: modelData.part === "hull" ? CustomMaterial.Shaded : CustomMaterial.Unshaded
                        vertexShader: modelData.part === "lens" ? "shaders/lens.vert" : (modelData.part === "hull" ? "shaders/hull.vert" : "shaders/emissive.vert")
                        fragmentShader: modelData.part === "lens" ? "shaders/lens.frag" : (modelData.part === "hull" ? "shaders/hull.frag" : "shaders/emissive.frag")
                        property color uHull: root.hullColor
                        property color uRole: modelData.part === "lens" ? root.lensColors[modelData.caste] : root.casteColors[modelData.caste]
                        property real uRimK: 0.85
                        property real uTime: root.sceneTime
                        property real uTentacles: modelData.lod === 0 ? 10 : (modelData.lod === 1 ? 6 : 4)
                        // Eyes run HDR so bloom picks them up; tentacle threads and
                        // seams stay under the glow threshold.
                        property real uStrength: modelData.part === "lens" ? root.eyeEmission : (modelData.part === "emissive" ? 0.7 : 1.0)
                        property real uViewportH: Math.max(1, view.height)
                        property real uEyeMinPx: root.eyeMinPx
                    }
                ]
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

        // Starfield (GAP.md item 4): 3 parallax layers, one instanced draw each.
        // Layers turn about the hive axis at different rates, so they slide past
        // each other as hive activity rises.
        Repeater3D {
            objectName: "starLayers"
            model: root.starLayers
            Model {
                required property var modelData
                objectName: "starLayer"
                source: "#Rectangle"
                eulerRotation.y: root.starDrift * modelData.rate
                instancing: RandomInstancing {
                    instanceCount: modelData.count
                    randomSeed: modelData.seed
                    position: InstanceRange { from: modelData.from; to: modelData.to }
                    color: InstanceRange { from: "#a473f0"; to: "#d2b9f8" }
                    customData: InstanceRange {
                        from: Qt.vector4d(modelData.px0, 0, 0, 0)
                        to: Qt.vector4d(modelData.px1, 0, 0, 0)
                    }
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
                }
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
                color: srcLabel.row.hot ? "#e0d4ff" : "#a99bd6"
                font.pixelSize: 20
                font.bold: true
                style: Text.Outline
                styleColor: "#0b0714"
            }
            Text {
                id: stateText
                anchors.horizontalCenter: parent.horizontalCenter
                text: srcLabel.row.hot ? "fetching" : "idle"
                color: srcLabel.row.hot ? (srcLabel.row.color || "#8fd3ff") : "#a99bd6"
                opacity: srcLabel.row.hot ? 1.0 : 0.75
                font.pixelSize: 15
                style: Text.Outline
                styleColor: "#0b0714"
            }
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

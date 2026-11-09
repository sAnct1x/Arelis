import QtQuick
import QtQuick3D
import QtQuick3D.Helpers

Item {
    id: root
    objectName: "OverseerView"
    property real cameraDistance: 76
    property real cameraPitch: 50.8
    property real cameraTargetX: 0
    property real cameraTargetY: 0
    property real cameraTargetZ: 0
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
    property string cameraMode: "follow"
    property int placementFrameId: 0
    property var instanceRecords: ({})
    // Per unit: open-fetch reach pairs now and before, and the sceneTime the
    // count changed, so the vertex shader eases the reach with no CPU per frame.
    property var reachState: ({})
    property var reachNext: ({})
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
    property string hudCommandStatus: ""
    property string lastHudCommand: ""
    property var lastHudPayload: ({})
    readonly property var casteIds: ["warden", "stalker", "harvester", "sanitizer", "tripwire"]
    readonly property var casteColors: ({
        warden: "#a78bfa", stalker: "#e879f9", harvester: "#8fd3ff",
        sanitizer: "#f2c56b", tripwire: "#7ee0c8"
    })
    readonly property var lensColors: ({
        warden: "#5a1cff", stalker: "#c010e0", harvester: "#0a7cff",
        sanitizer: "#ff8a00", tripwire: "#7ee0c8"
    })

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
        liveCounts = counts
        budgetTris = tris
        unitDrawCalls = used
        budgetDrawCalls = used + 10
        lodCounts = lods
        recountEntries(live)
        instanceRecords = recs
        rememberUnitPositions(buckets)
        sourceLabelSpecs = frame.sourceLabels || []
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
        if (cameraMode === "fit")
            return false
        var pos = unitPositionOf(selectedUnitId)
        if (!pos)
            return false
        setCameraTarget(pos.x, pos.y, pos.z)
        return true
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

    function fitSwarm() {
        cameraMode = "fit"
        unitFocused = false
        setCameraTarget(0, 0, 0)
        cameraDistance = 96.0
        cameraPitch = pitchDeg(96.0)
    }

    function freeViewportShift() {
        var w = Math.max(1, width)
        var h = Math.max(1, height)
        var left = Math.min(440, w * 0.26)
        var top = 86
        // Rank 3 dock: 24 edge + 360 width + 16 gap when open; prior 20 when closed.
        var right = w - (showInspector ? (24 + 360 + 16) : 20)
        if (right <= left)
            right = w
        var bottom = Math.max(top + 1, h - 230)
        var cx = (left + right) / 2
        var cy = (top + bottom) / 2
        return Qt.vector2d(-(cx - w / 2) / w, (cy - h / 2) / h)
    }

    function lensShiftOffset() {
        var sh = freeViewportShift()
        var d = cameraDistance
        var pitch = cameraPitch * Math.PI / 180
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
        if (Math.abs(n) > 40)
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
        e.color = row.color || casteColors[caste]
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
        var old = cameraDistance
        var next = old * Math.pow(1.18, notches)
        var lo = 6 * 0.92
        var hi = 110 * 1.08
        if (next < lo)
            next = lo
        if (next > hi)
            next = hi
        if (wheelPivotLive && old) {
            var s = next / old
            setCameraTarget(
                wheelPivotX + (cameraTargetX - wheelPivotX) * s,
                wheelPivotY + (cameraTargetY - wheelPivotY) * s,
                wheelPivotZ + (cameraTargetZ - wheelPivotZ) * s
            )
        } else {
            syncCameraTargetFromSelection()
        }
        cameraDistance = next
        cameraPitch = pitchDeg(next)
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

    function projectSourceLabels() {
        var specs = sourceLabelSpecs || []
        var out = []
        for (var i = 0; i < specs.length; i++) {
            var sp = specs[i]
            if (!sp)
                continue
            var mapped = _tryMapFrom3DScene(Qt.vector3d(finiteNum(sp.x), finiteNum(sp.y), finiteNum(sp.z)))
            var sx = mapped ? mapped.x : -1000
            var sy = mapped ? mapped.y : -1000
            // Hide labels behind the camera or off the plate.
            var visible = mapped && mapped.z > 0 && mapped.z < 1 && sx > 8 && sy > 8 && sx < width - 8 && sy < height - 8
            out.push({
                id: sp.id || ("src-" + i),
                label: sp.label || "",
                hot: !!sp.hot,
                color: sp.color || "#8fd3ff",
                sx: sx,
                sy: sy,
                visible: !!visible
            })
        }
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
        projectSourceLabels()
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
            var ny = Math.max(0.45, finiteCoord(e.position.y + sp.vy * stepDt, e.position.y))
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

    Component.onCompleted: ensureLists()


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
            backgroundMode: SceneEnvironment.Color
            clearColor: "#0b0714"
            tonemapMode: ExtendedSceneEnvironment.TonemapModeFilmic
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
        }

        DirectionalLight { eulerRotation.x: -40; eulerRotation.y: 30; brightness: 1.0 }
        DirectionalLight { eulerRotation.x: -15; eulerRotation.y: -120; brightness: 0.35 }

        Model {
            objectName: "overseerFloor"
            source: "#Rectangle"
            eulerRotation.x: -90
            scale: Qt.vector3d(16, 16, 16)
            materials: PrincipledMaterial { baseColor: "#050309"; roughness: 0.85 }
        }
        Model {
            objectName: "hiveCore"
            source: "#Sphere"
            scale: Qt.vector3d(0.022, 0.022, 0.022)
            materials: PrincipledMaterial {
                baseColor: "#3b2a66"; metalness: 0.4; roughness: 0.2
                emissiveFactor: Qt.vector3d(0.45, 0.35, 0.75)
            }
        }
        Repeater3D {
            model: [5, 10, 16, 23]
            Model {
                required property real modelData
                objectName: "casteRing"
                y: 0.02
                geometry: ProceduralMesh {
                    positions: root.ringPositions(modelData, modelData > 12 ? 0.02 : 0.014)
                    normals: root.ringNormals(modelData, modelData > 12 ? 0.02 : 0.014)
                    indexes: root.ringIndexes()
                }
                materials: PrincipledMaterial {
                    baseColor: modelData > 12 ? "#6d4ad8" : "#a78bfa"
                    lighting: PrincipledMaterial.NoLighting
                }
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
                        property color uHull: "#140f24"
                        property color uRole: modelData.part === "lens" ? root.lensColors[modelData.caste] : root.casteColors[modelData.caste]
                        property real uRimK: 1.35
                        property real uTime: root.sceneTime
                        property real uTentacles: modelData.lod === 0 ? 10 : (modelData.lod === 1 ? 6 : 4)
                        property real uStrength: modelData.part === "lens" ? 0.95 : (modelData.part === "emissive" ? 1.1 : 1.0)
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

    // Fixed harvest source labels at the scene edge (projected from 3D).
    Repeater {
        model: root.sourceLabelScreen
        delegate: Text {
            visible: modelData.visible
            x: modelData.sx - paintedWidth * 0.5
            y: modelData.sy - paintedHeight - 10
            text: modelData.label
            color: modelData.hot ? modelData.color : "#6b5f8a"
            font.pixelSize: modelData.hot ? 14 : 12
            font.bold: modelData.hot
            opacity: modelData.hot ? 0.95 : 0.55
            style: Text.Outline
            styleColor: "#0b0714"
            z: 20
        }
    }

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
        if (!view || world === undefined || world === null)
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

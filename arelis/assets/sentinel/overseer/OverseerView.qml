import QtQuick
import QtQuick3D
import QtQuick3D.Helpers

Item {
    id: root
    objectName: "OverseerView"
    property real cameraDistance: 76
    property real cameraPitch: 50.8
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
    property var liveCounts: ({})
    property var hudPills: ({})
    property var swarmRows: []
    property var inspectorCard: ({})
    property var hudLogs: []
    property var collapsedGroups: []
    property string selectedUnitId: ""
    property string swarmGroupBy: "caste"
    property string swarmSearch: ""
    property string logFilter: "all"
    property string logQuery: ""
    property string missionMode: "multi"
    property string missionQuery: ""
    property string hudStatusLine: "hive live, all local, sending out blocked"
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
        ensureLists()
        releaseAllLists()
        var buckets = frame.buckets
        var counts = ({})
        var used = 0
        var tris = 0
        var lods = [0, 0, 0]
        var live = 0
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
                        entries.push(fillUnitEntry(rows[i], caste))
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
        counts["__particles"] = 0
        liveCounts = counts
        budgetTris = tris
        unitDrawCalls = used
        budgetDrawCalls = used + 10
        lodCounts = lods
        recountEntries(live)
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

    function inspectorShouldHide() {
        if (selectedUnitId)
            return false
        var lo = 6.0
        var hi = 110.0
        var d = Math.max(lo, Math.min(hi, cameraDistance))
        var t = Math.log(d / lo) / Math.log(hi / lo)
        return t > 0.7
    }

    readonly property bool showInspector: !inspectorShouldHide()

    function selectUnit(unitId) {
        selectedUnitId = unitId || ""
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
            buckets[caste + ":" + lod].push({
                x: pos[0], y: pos[1], z: pos.length > 2 ? pos[2] : 0,
                heading_deg: u.heading_deg || 0,
                scale: u.scale === undefined ? 1 : u.scale,
                color: casteColors[caste],
                phase: u.phase || i * 1.7,
                claw: u.claw || 0.45,
                limp: u.limp || 0
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

    function fillUnitEntry(row, caste) {
        var e = acquireEntry()
        e.position = Qt.vector3d(finiteCoord(row.x), finiteCoord(row.y), finiteCoord(row.z))
        e.eulerRotation = Qt.vector3d(0, -finiteNum(row.heading_deg), 0)
        var sc = finiteNum(row.scale, 1)
        if (sc < 0.25)
            sc = 0.25
        if (sc > 2.0)
            sc = 2.0
        e.scale = Qt.vector3d(sc, sc, sc)
        e.color = row.color || casteColors[caste]
        e.customData = Qt.vector4d(row.phase || 0, row.claw || 0.45, row.limp || 0, 0)
        return e
    }

    function recountEntries(live) {
        liveEntryCount = live
        pooledEntryCount = entryPool ? entryPool.length : 0
        totalEntryCount = liveEntryCount + pooledEntryCount
    }

    function applyWheel(notches) {
        var next = cameraDistance * Math.pow(1.18, notches)
        var lo = 6 * 0.92
        var hi = 110 * 1.08
        if (next < lo)
            next = lo
        if (next > hi)
            next = hi
        cameraDistance = next
        var t = Math.log(Math.max(6, Math.min(110, next)) / 6) / Math.log(110 / 6)
        cameraPitch = 22 + t * (55 - 22)
        return cameraDistance
    }

    function ensureLists() {
        if (particleList === null) {
            particleList = Qt.createQmlObject("import QtQuick3D; InstanceList {}", root)
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

    function liveEntryCountFromLists() {
        var n = 0
        var keys = Object.keys(lists)
        for (var i = 0; i < keys.length; i++) {
            var insts = lists[keys[i]].instances || []
            n += insts.length
        }
        if (particleList && particleList.instances)
            n += particleList.instances.length
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
        onTriggered: root.sceneTime += frameTime
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
            fieldOfView: 35
            fieldOfViewOrientation: PerspectiveCamera.Vertical
            position: {
                const d = root.cameraDistance
                const pitch = root.cameraPitch * Math.PI / 180
                return Qt.vector3d(0, Math.sin(pitch) * d, Math.cos(pitch) * d)
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
                        property color uHull: "#3a2d5c"
                        property color uRole: modelData.part === "lens" ? root.lensColors[modelData.caste] : root.casteColors[modelData.caste]
                        property real uRimK: 1.0
                        property real uTime: root.sceneTime
                        property real uStrength: modelData.part === "lens" ? 0.95 : (modelData.part === "emissive" ? 1.1 : 1.0)
                    }
                ]
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

    OverseerHud {
        id: chrome
        objectName: "OverseerHud"
        z: 3
        visible: root.reveal > 0.35 || root.inputLive
        pills: root.hudPills
        swarmRows: root.swarmRows
        inspector: root.inspectorCard
        logs: root.hudLogs
        inspectorOpen: root.showInspector
        selectedUnitId: root.selectedUnitId
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
        onHudCommand: function (name, payload) {
            root.lastHudCommand = name
            root.lastHudPayload = payload
            if (name === "focus" && payload && payload.unit_id)
                root.selectUnit(payload.unit_id)
        }
    }
}

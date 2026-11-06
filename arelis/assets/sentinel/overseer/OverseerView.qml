import QtQuick
import QtQuick3D
import QtQuick3D.Helpers

Item {
    id: root
    objectName: "OverseerView"
    property real cameraDistance: 32
    property real cameraPitch: 36
    property int particleBudget: 520
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
        var buckets = frame.buckets
        var used = 0
        var tris = 0
        var lods = [0, 0, 0]
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
                        var e = instanceEntry()
                        e.position = Qt.vector3d(row.x || 0, row.z || 0, row.y || 0)
                        e.eulerRotation = Qt.vector3d(0, -(row.heading_deg || 0), 0)
                        var sc = row.scale === undefined ? 1 : row.scale
                        e.scale = Qt.vector3d(sc, sc, sc)
                        e.color = row.color || casteColors[caste]
                        e.customData = Qt.vector4d(row.phase || 0, row.claw || 0.45, row.limp || 0, 0)
                        entries.push(e)
                    }
                    lst.instances = entries
                    if (entries.length > 0) {
                        used += 1
                        var mt = meshTris[lod + ":" + part] || 0
                        tris += mt * entries.length
                    }
                }
            }
        }
        budgetTris = tris
        unitDrawCalls = used
        budgetDrawCalls = used + 10
        lodCounts = lods
        var b = frame.budget
        if (b) {
            // Prefer live instance x mesh totals; keep file budget as a cross-check property.
            if (b.unitTris !== undefined && b.unitTris !== tris)
                root.budgetFileTris = b.unitTris
        }
    }

    property int budgetFileTris: 0

    function applyUnits(units) {
        // Fallback when the host sends a raw unit list (tests / snapshot).
        applyFrame({ buckets: _bucketize(units || []) })
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

    function instanceEntry() {
        return Qt.createQmlObject("import QtQuick3D; InstanceListEntry {}", root)
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
        var entries = []
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i]
            if ((row.visible || 1) <= 0)
                continue
            var e = instanceEntry()
            e.position = Qt.vector3d(row.x || 0, row.y || 0, row.z || 0)
            var s = 0.04 * (row.visible === undefined ? 1 : row.visible)
            e.scale = Qt.vector3d(s, s, s)
            e.color = "#d9ccff"
            entries.push(e)
        }
        particleList.instances = entries
    }

    Component.onCompleted: ensureLists()

    NumberAnimation on entryMs {
        id: entryAnim
        from: 0
        to: 1600
        duration: 1600
        running: false
        onFinished: root.entryPlaying = false
    }

    Rectangle {
        id: fillPlate
        anchors.fill: parent
        color: "#0b0714"
        opacity: root.fill
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
            scale: Qt.vector3d(0.22, 0.22, 0.22)
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
                source: "#Cylinder"
                y: 0.02
                scale: Qt.vector3d(modelData / 50, 0.002, modelData / 50)
                materials: PrincipledMaterial {
                    baseColor: "#6d4ad8"
                    lighting: PrincipledMaterial.NoLighting
                    opacity: 0.35
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
                instancing: root.lists[modelData.key]
                materials: [
                    CustomMaterial {
                        shadingMode: modelData.part === "hull" ? CustomMaterial.Shaded : CustomMaterial.Unshaded
                        vertexShader: modelData.part === "lens" ? "shaders/lens.vert" : (modelData.part === "hull" ? "shaders/hull.vert" : "shaders/emissive.vert")
                        fragmentShader: modelData.part === "lens" ? "shaders/lens.frag" : (modelData.part === "hull" ? "shaders/hull.frag" : "shaders/emissive.frag")
                        property color uHull: "#3a2d5c"
                        property color uRole: modelData.part === "lens" ? root.lensColors[modelData.caste] : root.casteColors[modelData.caste]
                        property real uRimK: 1.0
                        property real uStrength: modelData.part === "lens" ? 0.95 : (modelData.part === "emissive" ? 1.1 : 1.0)
                    }
                ]
            }
        }

        Model {
            objectName: "entryParticleCloud"
            source: "#Sphere"
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
}

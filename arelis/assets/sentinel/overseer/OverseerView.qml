import QtQuick
import QtQuick3D
import QtQuick3D.Helpers
import QtQuick3D.Particles3D

Item {
    id: root
    objectName: "OverseerView"
    property string meshDir: "."
    property var units: []
    property real entryMs: 0
    property bool entryPlaying: false
    property int particleBudget: 520
    property real cameraDistance: 32
    property real cameraPitch: 36
    property real reveal: {
        const t = Math.min(1600, Math.max(0, entryMs))
        if (t < 300) return 0
        if (t > 1100) return 1
        const u = (t - 300) / 800
        return 1 - Math.pow(1 - u, 3)
    }

    function startEntry() {
        entryMs = 0
        entryPlaying = true
        entryAnim.restart()
        if (entryBurst)
            entryBurst.amount = root.particleBudget
        entrySys.reset()
    }

    NumberAnimation on entryMs {
        id: entryAnim
        from: 0
        to: 1600
        duration: 1600
        running: false
        onFinished: root.entryPlaying = false
    }

    View3D {
        id: view
        objectName: "OverseerView3D"
        anchors.fill: parent
        camera: cam
        opacity: root.reveal
        environment: ExtendedSceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#0b0714"
            tonemapMode: ExtendedSceneEnvironment.TonemapModeFilmic
        }

        PerspectiveCamera {
            id: cam
            // Dolly along the view axis; 35 mm-ish FOV. Blender Z-up maps to Qt Y-up.
            fieldOfView: 35
            fieldOfViewOrientation: PerspectiveCamera.Vertical
            position: {
                const d = root.cameraDistance
                const pitch = root.cameraPitch * Math.PI / 180
                return Qt.vector3d(0, Math.sin(pitch) * d, Math.cos(pitch) * d)
            }
            eulerRotation.x: -root.cameraPitch
        }

        DirectionalLight {
            eulerRotation.x: -40
            eulerRotation.y: 30
            brightness: 1.0
        }
        DirectionalLight {
            eulerRotation.x: -15
            eulerRotation.y: -120
            brightness: 0.35
        }

        Model {
            objectName: "overseerFloor"
            source: "#Rectangle"
            eulerRotation.x: -90
            scale: Qt.vector3d(16, 16, 16)
            materials: PrincipledMaterial {
                baseColor: "#050309"
                roughness: 0.85
                metalness: 0
            }
        }

        Model {
            objectName: "hiveCore"
            source: "#Sphere"
            scale: Qt.vector3d(0.22, 0.22, 0.22)
            materials: PrincipledMaterial {
                baseColor: "#3b2a66"
                metalness: 0.4
                roughness: 0.2
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
            id: swarm
            objectName: "swarmRepeater"
            model: root.units
            Node {
                id: unitNode
                required property var modelData
                position: Qt.vector3d(modelData.x || 0, modelData.z || 0, modelData.y || 0)
                eulerRotation.y: -((modelData.heading || 0) * 180 / Math.PI)
                Loader3D {
                    asynchronous: false
                    source: {
                        const lod = Math.max(0, Math.min(2, modelData.lod === undefined ? 1 : modelData.lod))
                        return "Sentinel_lod" + lod + ".qml"
                    }
                }
            }
        }

        ParticleSystem3D {
            id: entrySys
            objectName: "entryParticles"
            ParticleEmitter3D {
                system: entrySys
                emitBursts: [
                    EmitBurst3D {
                        id: entryBurst
                        time: 100
                        amount: root.particleBudget
                        duration: 250
                    }
                ]
                lifeSpan: 660
                particle: SpriteParticle3D {
                    maxAmount: 520
                    color: "#d9ccff"
                    billboard: true
                }
                velocity: VectorDirection3D {
                    direction: Qt.vector3d(0, 2, 0)
                    directionVariation: Qt.vector3d(8, 3, 8)
                }
            }
        }
    }
}

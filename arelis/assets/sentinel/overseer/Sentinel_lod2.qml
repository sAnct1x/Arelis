import QtQuick
import QtQuick3D

Node {
    id: node

    // Resources
    PrincipledMaterial {
        id: seam_a78bfa_002_material
        objectName: "seam#a78bfa.002"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.404226, 0.270073, 1)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: dseam_a78bfa_002_material
        objectName: "dseam#a78bfa.002"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.115929, 0.0774549, 0.286792)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: fil_a78bfa_002_material
        objectName: "fil#a78bfa.002"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.404226, 0.270073, 1)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: rh_a78bfa_100b1c_002_material
        objectName: "rh#a78bfa#100b1c.002"
        baseColor: "#ff100b1c"
        metalness: 0.75
        roughness: 0.25
        emissiveFactor: Qt.vector3d(0.0966074, 0.0645457, 0.238993)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
        clearcoatAmount: 0.6000000238418579
        clearcoatRoughnessAmount: 0.07999999821186066
    }
    PrincipledMaterial {
        id: rh_a78bfa_3a2d5c_002_material
        objectName: "rh#a78bfa#3a2d5c.002"
        baseColor: "#ff3a2d5c"
        metalness: 0.75
        roughness: 0.25
        emissiveFactor: Qt.vector3d(0.386429, 0.258183, 0.955973)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
        clearcoatAmount: 0.6000000238418579
        clearcoatRoughnessAmount: 0.07999999821186066
    }
    PrincipledMaterial {
        id: rh_a78bfa_2c2246_002_material
        objectName: "rh#a78bfa#2c2246.002"
        baseColor: "#ff2c2246"
        metalness: 0.75
        roughness: 0.25
        emissiveFactor: Qt.vector3d(0.193215, 0.129091, 0.477987)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
        clearcoatAmount: 0.6000000238418579
        clearcoatRoughnessAmount: 0.07999999821186066
    }
    PrincipledMaterial {
        id: lens_a78bfa_002_material
        objectName: "lens#a78bfa.002"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.0971296, 0.0110316, 0.95)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }

    // Nodes:
    Node {
        id: lod2
        objectName: "LOD2"
        scale: Qt.vector3d(1.35, 1.35, 1.35)
        Model {
            id: lod2_emissive
            objectName: "lod2_emissive"
            source: "meshes/lod2_emissive_mesh.mesh"
            materials: [
                seam_a78bfa_002_material,
                dseam_a78bfa_002_material,
                fil_a78bfa_002_material
            ]
        }
        Model {
            id: lod2_hull
            objectName: "lod2_hull"
            source: "meshes/lod2_hull_mesh.mesh"
            materials: [
                rh_a78bfa_100b1c_002_material,
                rh_a78bfa_3a2d5c_002_material,
                rh_a78bfa_2c2246_002_material
            ]
        }
        Model {
            id: lod2_lens
            objectName: "lod2_lens"
            source: "meshes/lod2_lens_mesh.mesh"
            materials: [
                lens_a78bfa_002_material
            ]
        }
    }

    // Animations:
}

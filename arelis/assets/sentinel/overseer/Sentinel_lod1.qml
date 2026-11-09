import QtQuick
import QtQuick3D

Node {
    id: node

    // Resources
    PrincipledMaterial {
        id: seam_a78bfa_001_material
        objectName: "seam#a78bfa.001"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.404226, 0.270073, 1)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: dseam_a78bfa_001_material
        objectName: "dseam#a78bfa.001"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.115929, 0.0774549, 0.286792)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: fil_a78bfa_001_material
        objectName: "fil#a78bfa.001"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.404226, 0.270073, 1)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: rh_a78bfa_100b1c_001_material
        objectName: "rh#a78bfa#100b1c.001"
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
        id: rh_a78bfa_3a2d5c_001_material
        objectName: "rh#a78bfa#3a2d5c.001"
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
        id: rh_a78bfa_2c2246_001_material
        objectName: "rh#a78bfa#2c2246.001"
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
        id: lens_a78bfa_001_material
        objectName: "lens#a78bfa.001"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.0971296, 0.0110316, 0.95)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }

    // Nodes:
    Node {
        id: lod1
        objectName: "LOD1"
        scale: Qt.vector3d(1.35, 1.35, 1.35)
        Model {
            id: lod1_emissive
            objectName: "lod1_emissive"
            source: "meshes/lod1_emissive_mesh.mesh"
            materials: [
                seam_a78bfa_001_material,
                dseam_a78bfa_001_material,
                fil_a78bfa_001_material
            ]
        }
        Model {
            id: lod1_hull
            objectName: "lod1_hull"
            source: "meshes/lod1_hull_mesh.mesh"
            materials: [
                rh_a78bfa_100b1c_001_material,
                rh_a78bfa_3a2d5c_001_material,
                rh_a78bfa_2c2246_001_material
            ]
        }
        Model {
            id: lod1_lens
            objectName: "lod1_lens"
            source: "meshes/lod1_lens_mesh.mesh"
            materials: [
                lens_a78bfa_001_material
            ]
        }
    }

    // Animations:
}

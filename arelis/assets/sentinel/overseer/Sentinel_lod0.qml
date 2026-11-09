import QtQuick
import QtQuick3D

Node {
    id: node

    // Resources
    PrincipledMaterial {
        id: seam_a78bfa_material
        objectName: "seam#a78bfa"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.404226, 0.270073, 1)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: dseam_a78bfa_material
        objectName: "dseam#a78bfa"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.115929, 0.0774549, 0.286792)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: fil_a78bfa_material
        objectName: "fil#a78bfa"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.404226, 0.270073, 1)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: rh_a78bfa_100b1c_material
        objectName: "rh#a78bfa#100b1c"
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
        id: rh_a78bfa_3a2d5c_material
        objectName: "rh#a78bfa#3a2d5c"
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
        id: rh_a78bfa_2c2246_material
        objectName: "rh#a78bfa#2c2246"
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
        id: lens_a78bfa_material
        objectName: "lens#a78bfa"
        baseColor: "#ff000000"
        metalness: 1
        roughness: 1
        emissiveFactor: Qt.vector3d(0.0971296, 0.0110316, 0.95)
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }

    // Nodes:
    Node {
        id: lod0
        objectName: "LOD0"
        scale: Qt.vector3d(1.35, 1.35, 1.35)
        Model {
            id: lod0_emissive
            objectName: "lod0_emissive"
            source: "meshes/lod0_emissive_mesh.mesh"
            materials: [
                seam_a78bfa_material,
                dseam_a78bfa_material,
                fil_a78bfa_material
            ]
        }
        Model {
            id: lod0_hull
            objectName: "lod0_hull"
            source: "meshes/lod0_hull_mesh.mesh"
            materials: [
                rh_a78bfa_100b1c_material,
                rh_a78bfa_3a2d5c_material,
                rh_a78bfa_2c2246_material
            ]
        }
        Model {
            id: lod0_lens
            objectName: "lod0_lens"
            source: "meshes/lod0_lens_mesh.mesh"
            materials: [
                lens_a78bfa_material
            ]
        }
    }

    // Animations:
}

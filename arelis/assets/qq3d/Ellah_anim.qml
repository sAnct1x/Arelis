import QtQuick
import QtQuick3D

import QtQuick.Timeline

Node {
    id: node

    // Resources
    property url textureData: "maps/textureData.jpg"
    property url textureData941: "maps/textureData941.png"
    property url textureData22: "maps/textureData22.jpg"
    property url textureData938: "maps/textureData938.jpg"
    property url textureData25: "maps/textureData25.jpg"
    property url textureData27: "maps/textureData27.jpg"
    property url textureData1009: "maps/textureData1009.png"
    property url textureData30: "maps/textureData30.png"
    property url textureData936: "maps/textureData936.jpg"
    property url textureData956: "maps/textureData956.jpg"
    property url textureData1012: "maps/textureData1012.png"
    property url textureData933: "maps/textureData933.jpg"
    property url textureData931: "maps/textureData931.png"
    property url textureData928: "maps/textureData928.jpg"
    property url textureData926: "maps/textureData926.jpg"
    property url textureData1370: "maps/textureData1370.png"
    property url textureData1373: "maps/textureData1373.png"
    property url textureData1376: "maps/textureData1376.png"
    property url textureData998: "maps/textureData998.jpg"
    property url textureData954: "maps/textureData954.jpg"
    property url textureData10: "maps/textureData10.jpg"
    property url textureData7: "maps/textureData7.jpg"
    property url textureData943: "maps/textureData943.jpg"
    property url textureData12: "maps/textureData12.jpg"
    property url textureData15: "maps/textureData15.jpg"
    property url textureData5: "maps/textureData5.jpg"
    property url textureData17: "maps/textureData17.jpg"
    property url textureData20: "maps/textureData20.jpg"
    property url textureData1001: "maps/textureData1001.jpg"
    Texture {
        id: _21_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData956
    }
    Texture {
        id: _29_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData1373
    }
    Texture {
        id: _0_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData5
    }
    Texture {
        id: _27_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData1370
    }
    Texture {
        id: _12_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData926
    }
    Texture {
        id: _30_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData1376
    }
    Texture {
        id: _13_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData928
    }
    Texture {
        id: _14_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData931
    }
    Texture {
        id: _20_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData954
    }
    Texture {
        id: _15_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData933
    }
    Texture {
        id: _16_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData936
    }
    Texture {
        id: _26_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData1012
    }
    Texture {
        id: _22_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData998
    }
    Texture {
        id: _24_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData1009
    }
    Texture {
        id: _19_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData943
    }
    Texture {
        id: _17_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData938
    }
    Texture {
        id: _23_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData1001
    }
    Texture {
        id: _18_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData941
    }
    Texture {
        id: _8_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData25
    }
    Texture {
        id: _2_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData10
    }
    Texture {
        id: _1_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData7
    }
    Texture {
        id: _3_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData12
    }
    Texture {
        id: _4_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData15
    }
    Texture {
        id: _5_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData17
    }
    Texture {
        id: _6_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData20
    }
    Texture {
        id: _7_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData22
    }
    Texture {
        id: _11_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData
    }
    Texture {
        id: _10_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData30
    }
    Texture {
        id: _9_texture
        generateMipmaps: true
        mipFilter: Texture.Linear
        source: node.textureData27
    }
    MorphTarget {
        id: mouth_Shrug_Lower_morphtarget
        objectName: "Mouth_Shrug_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Upper_morphtarget
        objectName: "Mouth_Shrug_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_R_morphtarget
        objectName: "Mouth_Lower_R"
        attributes: MorphTarget.Position
    }
    PrincipledMaterial {
        id: std_Cornea_L_material
        objectName: "Std_Cornea_L"
        baseColorMap: _18_texture
        roughness: 0.6683375239372253
        normalMap: _19_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Blend
    }
    Skin {
        id: skin
        joints: [
            cc_Base_BoneRoot,
            cc_Base_Hip,
            cc_Base_Pelvis,
            cc_Base_L_Thigh,
            cc_Base_L_Calf,
            cc_Base_L_Foot,
            cc_Base_L_ToeBaseShareBone,
            cc_Base_L_ToeBase,
            cc_Base_L_PinkyToe1,
            cc_Base_L_RingToe1,
            cc_Base_L_MidToe1,
            cc_Base_L_IndexToe1,
            cc_Base_L_BigToe1,
            cc_Base_L_CalfTwist01,
            cc_Base_L_CalfTwist02,
            cc_Base_L_KneeShareBone,
            cc_Base_L_ThighTwist01,
            cc_Base_L_ThighTwist02,
            cc_Base_R_Thigh,
            cc_Base_R_Calf,
            cc_Base_R_KneeShareBone,
            cc_Base_R_Foot,
            cc_Base_R_ToeBase,
            cc_Base_R_BigToe1,
            cc_Base_R_PinkyToe1,
            cc_Base_R_RingToe1,
            cc_Base_R_IndexToe1,
            cc_Base_R_MidToe1,
            cc_Base_R_ToeBaseShareBone,
            cc_Base_R_CalfTwist01,
            cc_Base_R_CalfTwist02,
            cc_Base_R_ThighTwist01,
            cc_Base_R_ThighTwist02,
            cc_Base_Waist,
            cc_Base_Spine01,
            cc_Base_Spine02,
            cc_Base_NeckTwist01,
            cc_Base_NeckTwist02,
            cc_Base_Head,
            cc_Base_FacialBone,
            cc_Base_JawRoot,
            cc_Base_Tongue01,
            cc_Base_Tongue02,
            cc_Base_Tongue03,
            cc_Base_Teeth02,
            cc_Base_R_Eye,
            cc_Base_L_Eye,
            cc_Base_UpperJaw,
            cc_Base_Teeth01,
            cc_Base_L_Clavicle,
            cc_Base_L_Upperarm,
            cc_Base_L_Forearm,
            cc_Base_L_ForearmTwist01,
            cc_Base_L_ForearmTwist02,
            cc_Base_L_ElbowShareBone,
            cc_Base_L_Hand,
            cc_Base_L_Pinky1,
            cc_Base_L_Pinky2,
            cc_Base_L_Pinky3,
            cc_Base_L_Ring1,
            cc_Base_L_Ring2,
            cc_Base_L_Ring3,
            cc_Base_L_Mid1,
            cc_Base_L_Mid2,
            cc_Base_L_Mid3,
            cc_Base_L_Index1,
            cc_Base_L_Index2,
            cc_Base_L_Index3,
            cc_Base_L_Thumb1,
            cc_Base_L_Thumb2,
            cc_Base_L_Thumb3,
            cc_Base_L_UpperarmTwist01,
            cc_Base_L_UpperarmTwist02,
            cc_Base_L_RibsTwist,
            cc_Base_L_Breast,
            cc_Base_R_RibsTwist,
            cc_Base_R_Breast,
            cc_Base_R_Clavicle,
            cc_Base_R_Upperarm,
            cc_Base_R_Forearm,
            cc_Base_R_ElbowShareBone,
            cc_Base_R_ForearmTwist01,
            cc_Base_R_ForearmTwist02,
            cc_Base_R_Hand,
            cc_Base_R_Ring1,
            cc_Base_R_Ring2,
            cc_Base_R_Ring3,
            cc_Base_R_Mid1,
            cc_Base_R_Mid2,
            cc_Base_R_Mid3,
            cc_Base_R_Thumb1,
            cc_Base_R_Thumb2,
            cc_Base_R_Thumb3,
            cc_Base_R_Index1,
            cc_Base_R_Index2,
            cc_Base_R_Index3,
            cc_Base_R_Pinky1,
            cc_Base_R_Pinky2,
            cc_Base_R_Pinky3,
            cc_Base_R_UpperarmTwist01,
            cc_Base_R_UpperarmTwist02
        ]
        inverseBindPoses: [
            Qt.matrix4x4(100, 0, 0, 0, 0, 0, -100, 0, 0, 100, 0, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0, 0, 0, 0, 100, 0, -107.16, 0, 0, 100, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, -1.50763e-05, -1.50014e-06, 1.61558e-05, 1.50763e-05, 98.0392, 19.7056, -105.059, -1.50015e-06, -19.7056, 98.0392, 21.1165, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19943, -0.00154083, 7.15862, -2.19935, -99.9738, -0.625483, 104.87, -0.0155098, -0.625462, 99.9971, 1.10913, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.75838, -0.0421809, 7.4091, -1.7563, -99.9396, -2.99681, 56.7001, -0.0950633, -2.99579, 99.9542, 2.45743, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4254, 0.44619, 10.6957, 7.6864, 10.1705, -27.2384, 95.679, 2.96016, 3.3402, 96.2178, 27.0361, -5.07653, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8064, -4.35358, 4.44084, 8.50303, 4.05605, 8.5563, 99.5498, -11.5637, -4.714, 99.5381, -8.36324, -0.491555, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, -4.31662, 4.43681, 8.50295, 4.0552, 8.5548, 99.5499, -11.5636, -4.6768, 99.5398, -8.36343, -0.494889, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4797, -10.1827, 0.321515, 11.6262, 3.3234, -29.4543, 95.5052, -10.6293, -9.6305, 95.0197, 29.6391, -3.94976, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9388, -14.1291, 3.38768, 10.0395, 8.29467, -35.7843, 93.0083, -11.5382, -11.9292, 92.303, 36.5761, -5.2262, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, -11.9903, 6.4032, 8.33146, 8.90352, -21.6488, 97.2208, -13.2905, -10.271, 96.8894, 22.515, -4.04237, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, -12.9598, 6.3167, 6.8974, 9.26771, -23.6197, 96.7267, -13.2502, -11.0437, 96.3024, 24.5737, -4.53582, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, -4.20361, 6.53537, 4.82496, 6.44302, 2.29263, 99.765, -13.8397, -4.34362, 99.8853, -2.015, -1.1624, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.7602, -0.0420473, 7.40808, -1.75813, -99.9395, -2.99824, 56.7002, -0.0950096, -2.99723, 99.9541, 2.45824, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.76061, -0.0444752, 7.40838, -1.75846, -99.9395, -2.99852, 31.2084, -0.0974532, -2.99746, 99.9541, 2.45817, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, 1.85246, -3.25678, 7.32702, -1.75497, -99.9397, -2.99578, 56.7, -3.31055, -2.93671, 99.9012, 2.69389, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19789, -0.00126959, 7.16024, -2.19782, -99.9739, -0.620892, 104.87, -0.0151281, -0.620878, 99.9972, 1.10429, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.1979, -0.000876542, 7.16006, -2.19783, -99.9739, -0.620904, 80.8223, -0.0147355, -0.620899, 99.9972, 1.10544, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, -2.19924, 0.00153699, -7.16575, 2.1992, -99.9739, -0.625714, 104.872, 0.0151791, -0.625438, 99.9985, 1.10604, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75776, 0.0422092, -7.41643, 1.75572, -99.9397, -2.99703, 56.704, 0.0947457, -2.99573, 99.9556, 2.45444, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, -1.85182, 3.25683, -7.33445, 1.75438, -99.9397, -2.99601, 56.704, 3.31021, -2.93666, 99.9025, 2.69113, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4253, -0.445641, -10.6957, -7.69344, -10.1708, -27.2377, 95.6805, 2.9584, -3.33968, 96.218, 27.0361, -5.08513, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, 4.31673, -4.43678, -8.51101, -4.05543, 8.55508, 99.5513, -11.5765, 4.67691, 99.5398, -8.36358, -0.498814, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, 4.20418, -6.53536, -4.83289, -6.44323, 2.29301, 99.7664, -13.8527, 4.34419, 99.8853, -2.01513, -1.16698, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4796, 10.1835, -0.321472, -11.6342, -3.32385, -29.4536, 95.5067, -10.6366, 9.63116, 95.0199, 29.639, -3.95668, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9387, 14.1298, -3.38765, -10.0477, -8.29509, -35.7835, 93.0098, -11.5462, 11.9297, 92.3033, 36.576, -5.23363, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, 12.9605, -6.3167, -6.90615, -9.26806, -23.619, 96.7282, -13.2604, 11.0444, 96.3025, 24.5736, -4.5426, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, 11.9906, -6.40327, -8.33963, -8.90384, -21.6481, 97.2223, -13.3019, 10.2712, 96.8896, 22.5149, -4.04937, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8065, 4.35429, -4.43993, -8.5112, -4.05542, 8.5551, 99.5513, -11.5765, 4.71457, 99.5382, -8.36192, -0.495601, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75958, 0.0420813, -7.41542, 1.75754, -99.9396, -2.99846, 56.7041, 0.0946975, -2.99715, 99.9555, 2.45525, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75998, 0.0445132, -7.41571, 1.75787, -99.9396, -2.99877, 31.2144, 0.0971455, -2.99742, 99.9555, 2.45518, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.19769, 0.00128364, -7.16738, 2.19765, -99.9739, -0.621137, 104.872, 0.0148155, -0.620868, 99.9986, 1.10122, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.1977, 0.000890074, -7.16717, 2.19766, -99.9739, -0.621137, 80.8252, 0.0144221, -0.620877, 99.9986, 1.10237, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0595393, 0.0154999, -0.0669482, -0.0615188, 96.446, 26.423, -110.219, 0.000783055, -26.423, 96.446, 28.2733, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.00372025, 0.000168532, 0.00785771, 0.00372275, 99.9827, -1.86208, -117.476, -9.92306e-05, 1.86208, 99.9827, -5.07925, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0111038, 0.0023672, 0.0174147, 0.0113498, 97.2489, -23.2946, -126.012, 0.000284515, 23.2946, 97.249, -32.914, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0547365, -0.0101122, 0.0848241, 0.0556495, 98.7096, 16.0127, -152.92, 0.00121684, -16.0127, 98.7096, 28.2536, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0401262, -0.0105083, 0.0615821, 0.0414671, 96.0918, 27.6832, -151.999, -0.00101063, -27.6832, 96.0918, 46.7363, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.000265608, 6.35935e-05, -0.00285968, 0.000265636, 100, -0.0357807, -162.25, -6.34991e-05, 0.0357837, 100, 1.83509, 0, 0, 0, 1),
            Qt.matrix4x4(-0.000669168, 100, -0.0360327, -162.25, -6.24571e-05, 0.0360356, 100, 1.83469, 100, 0.000669196, 6.38568e-05, -0.00437637, 0, 0, 0, 1),
            Qt.matrix4x4(-0.00245299, 0.0400948, 100, -0.767438, -0.0145806, -100, 0.0400834, 163.645, 100, -0.0145796, 0.00246047, 0.0205602, 0, 0, 0, 1),
            Qt.matrix4x4(0.112315, -17.6141, 98.4365, 25.0468, -0.0182466, -98.4365, -17.6141, 160.852, 99.9999, 0.001822, -0.113771, -0.00270895, 0, 0, 0, 1),
            Qt.matrix4x4(0.120985, -36.4206, 93.1318, 54.7053, -0.0198629, -93.1319, -36.4206, 153.137, 99.9999, 0.0255649, -0.119909, -0.0410066, 0, 0, 0, 1),
            Qt.matrix4x4(0.121003, -36.42, 93.132, 52.9936, -0.0202164, -93.1321, -36.42, 153.137, 99.9999, 0.0252415, -0.120054, -0.0404762, 0, 0, 0, 1),
            Qt.matrix4x4(0.0169932, 0.0411495, 100, -4.08427, -0.0173491, 100, -0.0411355, -162.538, -100, -0.0173421, 0.0169987, 0.0252892, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0131955, -0.0139593, 3.48603, -0.0139637, -0.0207999, -100, 5.17964, 0.0131926, 100, -0.0207988, -168.877, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0126715, 0.0153175, -3.49781, 0.0153222, -0.0500856, -100, 5.23196, -0.0126638, 100, -0.0500845, -168.872, 0, 0, 0, 1),
            Qt.matrix4x4(0.00847962, 0.034713, 100, -4.58337, -0.000401467, -100, 0.0347213, 164.58, 100, -0.000404406, -0.00847784, -0.00446657, 0, 0, 0, 1),
            Qt.matrix4x4(0.00138361, 0.0389695, 100, -4.95796, 0.00525116, 100, -0.0389778, -164.247, -100, 0.00525169, 0.00137992, 0.00236788, 0, 0, 0, 1),
            Qt.matrix4x4(-1.88568, -99.8883, 4.33249, 149.837, 97.3862, -2.81603, -22.5387, -0.808774, 22.6356, 3.79424, 97.3305, -4.74137, 0, 0, 0, 1),
            Qt.matrix4x4(-49.807, -86.6412, 3.54302, 137.155, 86.7134, -49.7753, 1.79, 61.5499, 0.212671, 3.96382, 99.9212, -1.52919, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.5239, 136.91, 86.3604, -50.3177, 3.16266, 35.73, -0.95603, 4.63749, 99.8878, -2.00221, 0, 0, 0, 1),
            Qt.matrix4x4(-50.409, -86.2932, 3.52318, 136.91, 86.3598, -50.3188, 3.16266, 35.7316, -0.956336, 4.63688, 99.8879, -2.00127, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.52317, 136.91, 86.3604, -50.3177, 3.16351, 23.7177, -0.957131, 4.63729, 99.8878, -2.00141, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4649, -86.264, 3.43616, 136.888, 86.3275, -50.3797, 3.07288, 35.8233, -0.91966, 4.51709, 99.8937, -1.85184, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7679, -87.7827, 3.52396, 137.204, 87.3005, -47.8784, -9.28884, 7.72614, 9.84121, -1.36064, 99.5053, -0.92711, 0, 0, 0, 1),
            Qt.matrix4x4(-49.9004, -86.5883, 3.52285, 136.803, 86.6599, -49.8627, 1.94246, 2.44348, 0.0746406, 4.0222, 99.9191, 0.988494, 0, 0, 0, 1),
            Qt.matrix4x4(-52.663, -84.9267, 3.75148, 136.743, 85.0063, -52.648, 1.4555, 4.14878, 0.738971, 3.9555, 99.919, 0.612436, 0, 0, 0, 1),
            Qt.matrix4x4(-44.5186, -89.4714, 3.60109, 136.398, 89.4575, -44.6162, -2.59674, -10.0752, 3.93001, 2.06542, 99.9014, 0.6083, 0, 0, 0, 1),
            Qt.matrix4x4(-49.6224, -86.7491, 3.49327, 137.198, 86.8192, -49.5725, 2.23479, 1.7522, -0.206964, 4.14179, 99.914, -0.821401, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6708, -83.6615, 3.44216, 137.086, 83.7279, -54.6641, 1.21753, 5.93462, 0.863019, 3.54768, 99.9333, -0.868637, 0, 0, 0, 1),
            Qt.matrix4x4(-47.9847, -87.6646, 3.52107, 136.953, 87.7066, -48.0329, -0.627888, -6.90922, 2.24171, 2.78693, 99.936, -0.96638, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5574, -86.1786, 4.14779, 137.418, 86.2745, -50.4515, 3.36886, 2.85757, -0.810612, 5.2817, 99.8571, -3.58848, 0, 0, 0, 1),
            Qt.matrix4x4(-51.6067, -85.587, 3.40699, 137.448, 85.6431, -51.4929, 3.70805, 0.185814, -1.41925, 4.83145, 99.8731, -2.62696, 0, 0, 0, 1),
            Qt.matrix4x4(-48.7135, -87.2623, 3.50497, 137.288, 87.3183, -48.5935, 3.76532, -7.09703, -1.58252, 4.89471, 99.8676, -2.58154, 0, 0, 0, 1),
            Qt.matrix4x4(-50.7218, -86.0765, 4.25742, 137.125, 86.1791, -50.6972, 1.71972, 3.07359, 0.678116, 4.54128, 99.8945, -5.83135, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4655, -85.0736, 3.13906, 137.165, 85.1159, -52.3497, 3.84519, 2.04567, -1.62795, 4.68924, 99.8767, -4.38814, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0827, -87.615, 3.41648, 136.971, 87.574, -47.7943, 6.81865, -7.42734, -4.34128, 6.27054, 99.7087, -4.27729, 0, 0, 0, 1),
            Qt.matrix4x4(-64.961, -73.2123, 20.4945, 129.222, 59.5939, -32.2961, 73.5223, 4.4705, -47.2084, 59.9743, 64.61, -44.6085, 0, 0, 0, 1),
            Qt.matrix4x4(-57.9161, -77.0926, 26.5039, 129.246, 77.6561, -42.2805, 46.7107, 0.294844, -24.8045, 47.6349, 84.3543, -44.5523, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7869, -80.2894, 29.525, 128.919, 81.9393, -36.6397, 44.085, -11.843, -24.5778, 47.0228, 84.7632, -43.9857, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8061, -86.6307, 3.80604, 137.151, 86.7135, -49.775, 1.7906, 61.5495, 0.343252, 4.19218, 99.9115, -1.8906, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8068, -86.6414, 3.54283, 137.155, 86.7135, -49.775, 1.79084, 48.1756, 0.211837, 3.96408, 99.9212, -1.52922, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0121952, -0.0016524, 10.1203, -0.00110477, 4.47696, 99.8997, -19.2259, 0.0122569, 99.8997, -4.47694, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, 10.1202, -0.00114441, 4.47696, 99.8997, -21.2259, 0.0122638, 99.8997, -4.47693, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122068, -0.00170066, -10.1238, -0.00115246, 4.47694, 99.8997, -19.2055, 0.0122707, 99.8997, -4.47693, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, -10.1238, -0.00114441, 4.47695, 99.8997, -21.2055, 0.0122638, 99.8997, -4.47694, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-1.85887, 99.8888, -4.33163, -149.836, -97.3861, -2.78984, -22.5425, -0.846488, -22.6383, 3.79937, 97.3297, -4.74888, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7835, 86.6547, -3.54387, -137.187, -86.7269, -49.7519, 1.78613, 61.4895, -0.21537, 3.96269, 99.9212, -1.52094, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3848, 86.3073, -3.52505, -136.942, -86.374, -50.2947, 3.1588, 35.7086, 0.953363, 4.63628, 99.8879, -1.99405, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4418, 86.2775, -3.43736, -136.92, -86.3411, -50.3567, 3.06902, 35.8021, 0.91693, 4.51592, 99.8938, -1.84374, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3858, 86.3067, -3.52427, -136.942, -86.3734, -50.2957, 3.1588, 35.7102, 0.953702, 4.63562, 99.8879, -1.99303, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3847, 86.3073, -3.52431, -136.942, -86.374, -50.2946, 3.15966, 23.7108, 0.954484, 4.63607, 99.8879, -1.99325, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7442, 87.7956, -3.52487, -137.236, -87.313, -47.8549, -9.29271, 7.73164, -9.8454, -1.35906, 99.5049, -0.917997, 0, 0, 0, 1),
            Qt.matrix4x4(-49.5991, 86.7624, -3.49434, -137.229, -86.8325, -49.5493, 2.23093, 1.75948, 0.204188, 4.14074, 99.914, -0.813094, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6474, 83.6768, -3.44239, -137.118, -83.7431, -54.6408, 1.21375, 5.94218, -0.865323, 3.54604, 99.9334, -0.858772, 0, 0, 0, 1),
            Qt.matrix4x4(-47.961, 87.6774, -3.52205, -136.985, -87.7194, -48.0094, -0.63177, -6.9061, -2.24483, 2.78652, 99.936, -0.958057, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5341, 86.1921, -4.14882, -137.449, -86.2882, -50.4284, 3.365, 2.86407, 0.808178, 5.28042, 99.8572, -3.57899, 0, 0, 0, 1),
            Qt.matrix4x4(-51.5833, 85.6011, -3.40781, -137.478, -85.6572, -51.4697, 3.70416, 0.191616, 1.41681, 4.82976, 99.8732, -2.61691, 0, 0, 0, 1),
            Qt.matrix4x4(-48.6899, 87.2755, -3.50582, -137.319, -87.3316, -48.5701, 3.76144, -7.092, 1.58004, 4.89313, 99.8677, -2.5717, 0, 0, 0, 1),
            Qt.matrix4x4(-64.9407, 73.2298, -20.4965, -129.252, -59.6054, -32.281, 73.5196, 4.48364, 47.2218, 59.9611, 64.6124, -44.6136, 0, 0, 0, 1),
            Qt.matrix4x4(-57.8947, 77.1081, -26.5056, -129.278, -77.6691, -42.2604, 46.7073, 0.307031, 24.8138, 47.6277, 84.3557, -44.5532, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7624, 80.3053, -29.5247, -128.953, -81.9515, -36.6168, 44.0813, -11.8357, 24.5886, 47.0134, 84.7652, -43.9827, 0, 0, 0, 1),
            Qt.matrix4x4(-50.6986, 86.0901, -4.25856, -137.155, -86.1927, -50.6742, 1.71586, 3.08145, -0.680797, 4.54049, 99.8945, -5.81861, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4425, 85.0878, -3.14012, -137.195, -85.1302, -52.3269, 3.84136, 2.05416, 1.6254, 4.6877, 99.8769, -4.37503, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0592, 87.6278, -3.41758, -137.002, -87.587, -47.771, 6.81477, -7.42022, 4.33903, 6.26848, 99.709, -4.26478, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8771, 86.6017, -3.52394, -136.835, -86.6733, -49.8395, 1.93857, 2.44804, -0.0774823, 4.02122, 99.9191, 0.995909, 0, 0, 0, 1),
            Qt.matrix4x4(-52.6416, 84.9398, -3.75452, -136.775, -85.0194, -52.6268, 1.45174, 4.15666, -0.742781, 3.95629, 99.919, 0.617262, 0, 0, 0, 1),
            Qt.matrix4x4(-44.4949, 89.4831, -3.60251, -136.43, -89.4691, -44.5927, -2.60061, -10.0723, -3.93356, 2.06599, 99.9013, 0.615095, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7826, 86.644, -3.80768, -137.182, -86.727, -49.7518, 1.78673, 61.4894, -0.346297, 4.19176, 99.9115, -1.88352, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7834, 86.6548, -3.54388, -137.187, -86.727, -49.7518, 1.78696, 48.1346, -0.214659, 3.96311, 99.9212, -1.52125, 0, 0, 0, 1)
        ]
    }
    MorphTarget {
        id: v_None_morphtarget
        objectName: "V_None"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_None_morphtarget947
        objectName: "V_None"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_None_morphtarget948
        objectName: "V_None"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Narrow_morphtarget
        objectName: "V_Tongue_Narrow"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Up_morphtarget
        objectName: "Tongue_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_In_morphtarget
        objectName: "Tongue_In"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Out_morphtarget
        objectName: "Tongue_Out"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Contract_morphtarget
        objectName: "Mouth_Contract"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_L_morphtarget
        objectName: "Mouth_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Curl_D_morphtarget
        objectName: "V_Tongue_Curl_D"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Curl_U_morphtarget
        objectName: "V_Tongue_Curl_U"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Lower_morphtarget
        objectName: "V_Tongue_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_None_morphtarget949
        objectName: "V_None"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Out_morphtarget
        objectName: "V_Tongue_Out"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Raise_morphtarget
        objectName: "V_Tongue_Raise"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_up_morphtarget
        objectName: "V_Tongue_up"
        attributes: MorphTarget.Position
    }
    Skin {
        id: skin957
        joints: [
            cc_Base_BoneRoot,
            cc_Base_Hip,
            cc_Base_Pelvis,
            cc_Base_L_Thigh,
            cc_Base_L_Calf,
            cc_Base_L_Foot,
            cc_Base_L_ToeBaseShareBone,
            cc_Base_L_ToeBase,
            cc_Base_L_PinkyToe1,
            cc_Base_L_RingToe1,
            cc_Base_L_MidToe1,
            cc_Base_L_IndexToe1,
            cc_Base_L_BigToe1,
            cc_Base_L_CalfTwist01,
            cc_Base_L_CalfTwist02,
            cc_Base_L_KneeShareBone,
            cc_Base_L_ThighTwist01,
            cc_Base_L_ThighTwist02,
            cc_Base_R_Thigh,
            cc_Base_R_Calf,
            cc_Base_R_KneeShareBone,
            cc_Base_R_Foot,
            cc_Base_R_ToeBase,
            cc_Base_R_BigToe1,
            cc_Base_R_PinkyToe1,
            cc_Base_R_RingToe1,
            cc_Base_R_IndexToe1,
            cc_Base_R_MidToe1,
            cc_Base_R_ToeBaseShareBone,
            cc_Base_R_CalfTwist01,
            cc_Base_R_CalfTwist02,
            cc_Base_R_ThighTwist01,
            cc_Base_R_ThighTwist02,
            cc_Base_Waist,
            cc_Base_Spine01,
            cc_Base_Spine02,
            cc_Base_NeckTwist01,
            cc_Base_NeckTwist02,
            cc_Base_Head,
            cc_Base_FacialBone,
            cc_Base_JawRoot,
            cc_Base_Tongue01,
            cc_Base_Tongue02,
            cc_Base_Tongue03,
            cc_Base_Teeth02,
            cc_Base_R_Eye,
            cc_Base_L_Eye,
            cc_Base_UpperJaw,
            cc_Base_Teeth01,
            cc_Base_L_Clavicle,
            cc_Base_L_Upperarm,
            cc_Base_L_Forearm,
            cc_Base_L_ForearmTwist01,
            cc_Base_L_ForearmTwist02,
            cc_Base_L_ElbowShareBone,
            cc_Base_L_Hand,
            cc_Base_L_Pinky1,
            cc_Base_L_Pinky2,
            cc_Base_L_Pinky3,
            cc_Base_L_Ring1,
            cc_Base_L_Ring2,
            cc_Base_L_Ring3,
            cc_Base_L_Mid1,
            cc_Base_L_Mid2,
            cc_Base_L_Mid3,
            cc_Base_L_Index1,
            cc_Base_L_Index2,
            cc_Base_L_Index3,
            cc_Base_L_Thumb1,
            cc_Base_L_Thumb2,
            cc_Base_L_Thumb3,
            cc_Base_L_UpperarmTwist01,
            cc_Base_L_UpperarmTwist02,
            cc_Base_L_RibsTwist,
            cc_Base_L_Breast,
            cc_Base_R_RibsTwist,
            cc_Base_R_Breast,
            cc_Base_R_Clavicle,
            cc_Base_R_Upperarm,
            cc_Base_R_Forearm,
            cc_Base_R_ElbowShareBone,
            cc_Base_R_ForearmTwist01,
            cc_Base_R_ForearmTwist02,
            cc_Base_R_Hand,
            cc_Base_R_Ring1,
            cc_Base_R_Ring2,
            cc_Base_R_Ring3,
            cc_Base_R_Mid1,
            cc_Base_R_Mid2,
            cc_Base_R_Mid3,
            cc_Base_R_Thumb1,
            cc_Base_R_Thumb2,
            cc_Base_R_Thumb3,
            cc_Base_R_Index1,
            cc_Base_R_Index2,
            cc_Base_R_Index3,
            cc_Base_R_Pinky1,
            cc_Base_R_Pinky2,
            cc_Base_R_Pinky3,
            cc_Base_R_UpperarmTwist01,
            cc_Base_R_UpperarmTwist02
        ]
        inverseBindPoses: [
            Qt.matrix4x4(100, 0, 0, 0, 0, 0, -100, 0, 0, 100, 0, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0, 0, 0, 0, 100, 0, -107.16, 0, 0, 100, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, -1.50763e-05, -1.50014e-06, 1.61558e-05, 1.50763e-05, 98.0392, 19.7056, -105.059, -1.50015e-06, -19.7056, 98.0392, 21.1165, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19943, -0.00154083, 7.15862, -2.19935, -99.9738, -0.625483, 104.87, -0.0155098, -0.625462, 99.9971, 1.10913, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.75838, -0.0421809, 7.4091, -1.7563, -99.9396, -2.99681, 56.7001, -0.0950633, -2.99579, 99.9542, 2.45743, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4254, 0.44619, 10.6957, 7.6864, 10.1705, -27.2384, 95.679, 2.96016, 3.3402, 96.2178, 27.0361, -5.07653, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8064, -4.35358, 4.44084, 8.50303, 4.05605, 8.5563, 99.5498, -11.5637, -4.714, 99.5381, -8.36324, -0.491555, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, -4.31662, 4.43681, 8.50295, 4.0552, 8.5548, 99.5499, -11.5636, -4.6768, 99.5398, -8.36343, -0.494889, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4797, -10.1827, 0.321515, 11.6262, 3.3234, -29.4543, 95.5052, -10.6293, -9.6305, 95.0197, 29.6391, -3.94976, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9388, -14.1291, 3.38768, 10.0395, 8.29467, -35.7843, 93.0083, -11.5382, -11.9292, 92.303, 36.5761, -5.2262, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, -11.9903, 6.4032, 8.33146, 8.90352, -21.6488, 97.2208, -13.2905, -10.271, 96.8894, 22.515, -4.04237, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, -12.9598, 6.3167, 6.8974, 9.26771, -23.6197, 96.7267, -13.2502, -11.0437, 96.3024, 24.5737, -4.53582, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, -4.20361, 6.53537, 4.82496, 6.44302, 2.29263, 99.765, -13.8397, -4.34362, 99.8853, -2.015, -1.1624, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.7602, -0.0420473, 7.40808, -1.75813, -99.9395, -2.99824, 56.7002, -0.0950096, -2.99723, 99.9541, 2.45824, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.76061, -0.0444752, 7.40838, -1.75846, -99.9395, -2.99852, 31.2084, -0.0974532, -2.99746, 99.9541, 2.45817, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, 1.85246, -3.25678, 7.32702, -1.75497, -99.9397, -2.99578, 56.7, -3.31055, -2.93671, 99.9012, 2.69389, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19789, -0.00126959, 7.16024, -2.19782, -99.9739, -0.620892, 104.87, -0.0151281, -0.620878, 99.9972, 1.10429, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.1979, -0.000876542, 7.16006, -2.19783, -99.9739, -0.620904, 80.8223, -0.0147355, -0.620899, 99.9972, 1.10544, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, -2.19924, 0.00153699, -7.16575, 2.1992, -99.9739, -0.625714, 104.872, 0.0151791, -0.625438, 99.9985, 1.10604, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75776, 0.0422092, -7.41643, 1.75572, -99.9397, -2.99703, 56.704, 0.0947457, -2.99573, 99.9556, 2.45444, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, -1.85182, 3.25683, -7.33445, 1.75438, -99.9397, -2.99601, 56.704, 3.31021, -2.93666, 99.9025, 2.69113, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4253, -0.445641, -10.6957, -7.69344, -10.1708, -27.2377, 95.6805, 2.9584, -3.33968, 96.218, 27.0361, -5.08513, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, 4.31673, -4.43678, -8.51101, -4.05543, 8.55508, 99.5513, -11.5765, 4.67691, 99.5398, -8.36358, -0.498814, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, 4.20418, -6.53536, -4.83289, -6.44323, 2.29301, 99.7664, -13.8527, 4.34419, 99.8853, -2.01513, -1.16698, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4796, 10.1835, -0.321472, -11.6342, -3.32385, -29.4536, 95.5067, -10.6366, 9.63116, 95.0199, 29.639, -3.95668, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9387, 14.1298, -3.38765, -10.0477, -8.29509, -35.7835, 93.0098, -11.5462, 11.9297, 92.3033, 36.576, -5.23363, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, 12.9605, -6.3167, -6.90615, -9.26806, -23.619, 96.7282, -13.2604, 11.0444, 96.3025, 24.5736, -4.5426, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, 11.9906, -6.40327, -8.33963, -8.90384, -21.6481, 97.2223, -13.3019, 10.2712, 96.8896, 22.5149, -4.04937, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8065, 4.35429, -4.43993, -8.5112, -4.05542, 8.5551, 99.5513, -11.5765, 4.71457, 99.5382, -8.36192, -0.495601, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75958, 0.0420813, -7.41542, 1.75754, -99.9396, -2.99846, 56.7041, 0.0946975, -2.99715, 99.9555, 2.45525, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75998, 0.0445132, -7.41571, 1.75787, -99.9396, -2.99877, 31.2144, 0.0971455, -2.99742, 99.9555, 2.45518, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.19769, 0.00128364, -7.16738, 2.19765, -99.9739, -0.621137, 104.872, 0.0148155, -0.620868, 99.9986, 1.10122, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.1977, 0.000890074, -7.16717, 2.19766, -99.9739, -0.621137, 80.8252, 0.0144221, -0.620877, 99.9986, 1.10237, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0595393, 0.0154999, -0.0669482, -0.0615188, 96.446, 26.423, -110.219, 0.000783055, -26.423, 96.446, 28.2733, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.00372025, 0.000168532, 0.00785771, 0.00372275, 99.9827, -1.86208, -117.476, -9.92306e-05, 1.86208, 99.9827, -5.07925, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0111038, 0.0023672, 0.0174147, 0.0113498, 97.2489, -23.2946, -126.012, 0.000284515, 23.2946, 97.249, -32.914, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0547365, -0.0101122, 0.0848241, 0.0556495, 98.7096, 16.0127, -152.92, 0.00121684, -16.0127, 98.7096, 28.2536, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0401262, -0.0105083, 0.0615821, 0.0414671, 96.0918, 27.6832, -151.999, -0.00101063, -27.6832, 96.0918, 46.7363, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.000265608, 6.35935e-05, -0.00285968, 0.000265636, 100, -0.0357807, -162.25, -6.34991e-05, 0.0357837, 100, 1.83509, 0, 0, 0, 1),
            Qt.matrix4x4(-0.000669168, 100, -0.0360327, -162.25, -6.24571e-05, 0.0360356, 100, 1.83469, 100, 0.000669196, 6.38568e-05, -0.00437637, 0, 0, 0, 1),
            Qt.matrix4x4(-0.00245299, 0.0400948, 100, -0.767438, -0.0145806, -100, 0.0400834, 163.645, 100, -0.0145796, 0.00246047, 0.0205602, 0, 0, 0, 1),
            Qt.matrix4x4(0.112315, -17.6141, 98.4365, 25.0468, -0.0182466, -98.4365, -17.6141, 160.852, 99.9999, 0.001822, -0.113771, -0.00270895, 0, 0, 0, 1),
            Qt.matrix4x4(0.120985, -36.4206, 93.1318, 54.7053, -0.0198629, -93.1319, -36.4206, 153.137, 99.9999, 0.0255649, -0.119909, -0.0410066, 0, 0, 0, 1),
            Qt.matrix4x4(0.121003, -36.42, 93.132, 52.9936, -0.0202164, -93.1321, -36.42, 153.137, 99.9999, 0.0252415, -0.120054, -0.0404762, 0, 0, 0, 1),
            Qt.matrix4x4(0.0169932, 0.0411495, 100, -4.08427, -0.0173491, 100, -0.0411355, -162.538, -100, -0.0173421, 0.0169987, 0.0252892, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0131955, -0.0139593, 3.48603, -0.0139637, -0.0207999, -100, 5.17964, 0.0131926, 100, -0.0207988, -168.877, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0126715, 0.0153175, -3.49781, 0.0153222, -0.0500856, -100, 5.23196, -0.0126638, 100, -0.0500845, -168.872, 0, 0, 0, 1),
            Qt.matrix4x4(0.00847962, 0.034713, 100, -4.58337, -0.000401467, -100, 0.0347213, 164.58, 100, -0.000404406, -0.00847784, -0.00446657, 0, 0, 0, 1),
            Qt.matrix4x4(0.00138361, 0.0389695, 100, -4.95796, 0.00525116, 100, -0.0389778, -164.247, -100, 0.00525169, 0.00137992, 0.00236788, 0, 0, 0, 1),
            Qt.matrix4x4(-1.88568, -99.8883, 4.33249, 149.837, 97.3862, -2.81603, -22.5387, -0.808774, 22.6356, 3.79424, 97.3305, -4.74137, 0, 0, 0, 1),
            Qt.matrix4x4(-49.807, -86.6412, 3.54302, 137.155, 86.7134, -49.7753, 1.79, 61.5499, 0.212671, 3.96382, 99.9212, -1.52919, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.5239, 136.91, 86.3604, -50.3177, 3.16266, 35.73, -0.95603, 4.63749, 99.8878, -2.00221, 0, 0, 0, 1),
            Qt.matrix4x4(-50.409, -86.2932, 3.52318, 136.91, 86.3598, -50.3188, 3.16266, 35.7316, -0.956336, 4.63688, 99.8879, -2.00127, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.52317, 136.91, 86.3604, -50.3177, 3.16351, 23.7177, -0.957131, 4.63729, 99.8878, -2.00141, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4649, -86.264, 3.43616, 136.888, 86.3275, -50.3797, 3.07288, 35.8233, -0.91966, 4.51709, 99.8937, -1.85184, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7679, -87.7827, 3.52396, 137.204, 87.3005, -47.8784, -9.28884, 7.72614, 9.84121, -1.36064, 99.5053, -0.92711, 0, 0, 0, 1),
            Qt.matrix4x4(-49.9004, -86.5883, 3.52285, 136.803, 86.6599, -49.8627, 1.94246, 2.44348, 0.0746406, 4.0222, 99.9191, 0.988494, 0, 0, 0, 1),
            Qt.matrix4x4(-52.663, -84.9267, 3.75148, 136.743, 85.0063, -52.648, 1.4555, 4.14878, 0.738971, 3.9555, 99.919, 0.612436, 0, 0, 0, 1),
            Qt.matrix4x4(-44.5186, -89.4714, 3.60109, 136.398, 89.4575, -44.6162, -2.59674, -10.0752, 3.93001, 2.06542, 99.9014, 0.6083, 0, 0, 0, 1),
            Qt.matrix4x4(-49.6224, -86.7491, 3.49327, 137.198, 86.8192, -49.5725, 2.23479, 1.7522, -0.206964, 4.14179, 99.914, -0.821401, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6708, -83.6615, 3.44216, 137.086, 83.7279, -54.6641, 1.21753, 5.93462, 0.863019, 3.54768, 99.9333, -0.868637, 0, 0, 0, 1),
            Qt.matrix4x4(-47.9847, -87.6646, 3.52107, 136.953, 87.7066, -48.0329, -0.627888, -6.90922, 2.24171, 2.78693, 99.936, -0.96638, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5574, -86.1786, 4.14779, 137.418, 86.2745, -50.4515, 3.36886, 2.85757, -0.810612, 5.2817, 99.8571, -3.58848, 0, 0, 0, 1),
            Qt.matrix4x4(-51.6067, -85.587, 3.40699, 137.448, 85.6431, -51.4929, 3.70805, 0.185814, -1.41925, 4.83145, 99.8731, -2.62696, 0, 0, 0, 1),
            Qt.matrix4x4(-48.7135, -87.2623, 3.50497, 137.288, 87.3183, -48.5935, 3.76532, -7.09703, -1.58252, 4.89471, 99.8676, -2.58154, 0, 0, 0, 1),
            Qt.matrix4x4(-50.7218, -86.0765, 4.25742, 137.125, 86.1791, -50.6972, 1.71972, 3.07359, 0.678116, 4.54128, 99.8945, -5.83135, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4655, -85.0736, 3.13906, 137.165, 85.1159, -52.3497, 3.84519, 2.04567, -1.62795, 4.68924, 99.8767, -4.38814, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0827, -87.615, 3.41648, 136.971, 87.574, -47.7943, 6.81865, -7.42734, -4.34128, 6.27054, 99.7087, -4.27729, 0, 0, 0, 1),
            Qt.matrix4x4(-64.961, -73.2123, 20.4945, 129.222, 59.5939, -32.2961, 73.5223, 4.4705, -47.2084, 59.9743, 64.61, -44.6085, 0, 0, 0, 1),
            Qt.matrix4x4(-57.9161, -77.0926, 26.5039, 129.246, 77.6561, -42.2805, 46.7107, 0.294844, -24.8045, 47.6349, 84.3543, -44.5523, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7869, -80.2894, 29.525, 128.919, 81.9393, -36.6397, 44.085, -11.843, -24.5778, 47.0228, 84.7632, -43.9857, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8061, -86.6307, 3.80604, 137.151, 86.7135, -49.775, 1.7906, 61.5495, 0.343252, 4.19218, 99.9115, -1.8906, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8068, -86.6414, 3.54283, 137.155, 86.7135, -49.775, 1.79084, 48.1756, 0.211837, 3.96408, 99.9212, -1.52922, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0121952, -0.0016524, 10.1203, -0.00110477, 4.47696, 99.8997, -19.2259, 0.0122569, 99.8997, -4.47694, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, 10.1202, -0.00114441, 4.47696, 99.8997, -21.2259, 0.0122638, 99.8997, -4.47693, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122068, -0.00170066, -10.1238, -0.00115246, 4.47694, 99.8997, -19.2055, 0.0122707, 99.8997, -4.47693, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, -10.1238, -0.00114441, 4.47695, 99.8997, -21.2055, 0.0122638, 99.8997, -4.47694, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-1.85887, 99.8888, -4.33163, -149.836, -97.3861, -2.78984, -22.5425, -0.846488, -22.6383, 3.79937, 97.3297, -4.74888, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7835, 86.6547, -3.54387, -137.187, -86.7269, -49.7519, 1.78613, 61.4895, -0.21537, 3.96269, 99.9212, -1.52094, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3848, 86.3073, -3.52505, -136.942, -86.374, -50.2947, 3.1588, 35.7086, 0.953363, 4.63628, 99.8879, -1.99405, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4418, 86.2775, -3.43736, -136.92, -86.3411, -50.3567, 3.06902, 35.8021, 0.91693, 4.51592, 99.8938, -1.84374, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3858, 86.3067, -3.52427, -136.942, -86.3734, -50.2957, 3.1588, 35.7102, 0.953702, 4.63562, 99.8879, -1.99303, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3847, 86.3073, -3.52431, -136.942, -86.374, -50.2946, 3.15966, 23.7108, 0.954484, 4.63607, 99.8879, -1.99325, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7442, 87.7956, -3.52487, -137.236, -87.313, -47.8549, -9.29271, 7.73164, -9.8454, -1.35906, 99.5049, -0.917997, 0, 0, 0, 1),
            Qt.matrix4x4(-49.5991, 86.7624, -3.49434, -137.229, -86.8325, -49.5493, 2.23093, 1.75948, 0.204188, 4.14074, 99.914, -0.813094, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6474, 83.6768, -3.44239, -137.118, -83.7431, -54.6408, 1.21375, 5.94218, -0.865323, 3.54604, 99.9334, -0.858772, 0, 0, 0, 1),
            Qt.matrix4x4(-47.961, 87.6774, -3.52205, -136.985, -87.7194, -48.0094, -0.63177, -6.9061, -2.24483, 2.78652, 99.936, -0.958057, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5341, 86.1921, -4.14882, -137.449, -86.2882, -50.4284, 3.365, 2.86407, 0.808178, 5.28042, 99.8572, -3.57899, 0, 0, 0, 1),
            Qt.matrix4x4(-51.5833, 85.6011, -3.40781, -137.478, -85.6572, -51.4697, 3.70416, 0.191616, 1.41681, 4.82976, 99.8732, -2.61691, 0, 0, 0, 1),
            Qt.matrix4x4(-48.6899, 87.2755, -3.50582, -137.319, -87.3316, -48.5701, 3.76144, -7.092, 1.58004, 4.89313, 99.8677, -2.5717, 0, 0, 0, 1),
            Qt.matrix4x4(-64.9407, 73.2298, -20.4965, -129.252, -59.6054, -32.281, 73.5196, 4.48364, 47.2218, 59.9611, 64.6124, -44.6136, 0, 0, 0, 1),
            Qt.matrix4x4(-57.8947, 77.1081, -26.5056, -129.278, -77.6691, -42.2604, 46.7073, 0.307031, 24.8138, 47.6277, 84.3557, -44.5532, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7624, 80.3053, -29.5247, -128.953, -81.9515, -36.6168, 44.0813, -11.8357, 24.5886, 47.0134, 84.7652, -43.9827, 0, 0, 0, 1),
            Qt.matrix4x4(-50.6986, 86.0901, -4.25856, -137.155, -86.1927, -50.6742, 1.71586, 3.08145, -0.680797, 4.54049, 99.8945, -5.81861, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4425, 85.0878, -3.14012, -137.195, -85.1302, -52.3269, 3.84136, 2.05416, 1.6254, 4.6877, 99.8769, -4.37503, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0592, 87.6278, -3.41758, -137.002, -87.587, -47.771, 6.81477, -7.42022, 4.33903, 6.26848, 99.709, -4.26478, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8771, 86.6017, -3.52394, -136.835, -86.6733, -49.8395, 1.93857, 2.44804, -0.0774823, 4.02122, 99.9191, 0.995909, 0, 0, 0, 1),
            Qt.matrix4x4(-52.6416, 84.9398, -3.75452, -136.775, -85.0194, -52.6268, 1.45174, 4.15666, -0.742781, 3.95629, 99.919, 0.617262, 0, 0, 0, 1),
            Qt.matrix4x4(-44.4949, 89.4831, -3.60251, -136.43, -89.4691, -44.5927, -2.60061, -10.0723, -3.93356, 2.06599, 99.9013, 0.615095, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7826, 86.644, -3.80768, -137.182, -86.727, -49.7518, 1.78673, 61.4894, -0.346297, 4.19176, 99.9115, -1.88352, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7834, 86.6548, -3.54388, -137.187, -86.727, -49.7518, 1.78696, 48.1346, -0.214659, 3.96311, 99.9212, -1.52125, 0, 0, 0, 1)
        ]
    }
    MorphTarget {
        id: mouth_Lower_L_morphtarget
        objectName: "Mouth_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_L_morphtarget
        objectName: "Eyelash_Lower_Down_L"
        attributes: MorphTarget.Position
    }
    PrincipledMaterial {
        id: std_Tongue_material
        objectName: "Std_Tongue"
        baseColorMap: _20_texture
        roughness: 0.858578622341156
        normalMap: _21_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    MorphTarget {
        id: mouth_Drop_Upper_morphtarget
        objectName: "Mouth_Drop_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_L_morphtarget
        objectName: "Head_Tilt_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Backward_morphtarget
        objectName: "Jaw_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_R_morphtarget
        objectName: "Head_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_L_morphtarget
        objectName: "Jaw_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_R_morphtarget
        objectName: "Jaw_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_L_morphtarget
        objectName: "Head_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Up_morphtarget
        objectName: "Jaw_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Down_morphtarget
        objectName: "Jaw_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_R_morphtarget
        objectName: "Head_Tilt_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Forward_morphtarget
        objectName: "Jaw_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_R_morphtarget
        objectName: "Head_Turn_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_L_morphtarget
        objectName: "Head_Turn_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Down_morphtarget
        objectName: "Head_Turn_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Up_morphtarget
        objectName: "Head_Turn_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_R_morphtarget
        objectName: "Neck_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_L_morphtarget
        objectName: "Neck_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Down_morphtarget
        objectName: "Neck_Swallow_Down"
        attributes: MorphTarget.Position
    }
    PrincipledMaterial {
        id: std_Cornea_R_material
        objectName: "Std_Cornea_R"
        baseColorMap: _14_texture
        roughness: 0.6683375239372253
        normalMap: _15_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Blend
    }
    MorphTarget {
        id: mouth_Drop_Lower_morphtarget
        objectName: "Mouth_Drop_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_L_morphtarget
        objectName: "Mouth_Up_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_R_morphtarget
        objectName: "Mouth_Up_Upper_R"
        attributes: MorphTarget.Position
    }
    PrincipledMaterial {
        id: std_Eye_L_material
        objectName: "Std_Eye_L"
        baseColorMap: _16_texture
        roughness: 0.5527864098548889
        normalMap: _17_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    MorphTarget {
        id: mouth_Down_Lower_L_morphtarget
        objectName: "Mouth_Down_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_R_morphtarget
        objectName: "Mouth_Down_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Chin_Up_morphtarget
        objectName: "Mouth_Chin_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Close_morphtarget
        objectName: "Mouth_Close"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Up_morphtarget
        objectName: "Neck_Swallow_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Contract_morphtarget899
        objectName: "Mouth_Contract"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_L_morphtarget
        objectName: "Tongue_Bulge_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_R_morphtarget
        objectName: "Tongue_Bulge_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Open_morphtarget
        objectName: "Jaw_Open"
        attributes: MorphTarget.Position
    }
    PrincipledMaterial {
        id: std_Eye_R_material
        objectName: "Std_Eye_R"
        baseColorMap: _12_texture
        roughness: 0.5527864098548889
        normalMap: _13_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    MorphTarget {
        id: head_Backward_morphtarget
        objectName: "Head_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Forward_morphtarget
        objectName: "Head_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Curl_D_morphtarget1030
        objectName: "V_Tongue_Curl_D"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_R_morphtarget
        objectName: "Eye_Blink_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_L_morphtarget
        objectName: "Eye_Blink_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_R_morphtarget
        objectName: "Brow_Compress_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_L_morphtarget
        objectName: "Brow_Compress_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_R_morphtarget
        objectName: "Brow_Drop_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_L_morphtarget
        objectName: "Brow_Drop_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_R_morphtarget
        objectName: "Brow_Raise_Outer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_L_morphtarget
        objectName: "Brow_Raise_Outer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_R_morphtarget
        objectName: "Brow_Raise_Inner_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_L_morphtarget
        objectName: "Brow_Raise_Inner_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_L_morphtarget
        objectName: "Eye_Squint_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Curl_U_morphtarget1029
        objectName: "V_Tongue_Curl_U"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Lower_morphtarget1028
        objectName: "V_Tongue_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Narrow_morphtarget1027
        objectName: "V_Tongue_Narrow"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Out_morphtarget1026
        objectName: "V_Tongue_Out"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Raise_morphtarget1025
        objectName: "V_Tongue_Raise"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_up_morphtarget1024
        objectName: "V_Tongue_up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Lip_Open_morphtarget
        objectName: "V_Lip_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Affricate_morphtarget
        objectName: "V_Affricate"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Wide_morphtarget
        objectName: "V_Wide"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Down_morphtarget
        objectName: "Eye_L_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_R_morphtarget
        objectName: "Mouth_Funnel_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_L_morphtarget
        objectName: "Eyelash_Lower_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_R_morphtarget
        objectName: "Eyelash_Upper_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_R_morphtarget
        objectName: "Eyelash_Upper_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_L_morphtarget
        objectName: "Eyelash_Upper_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_L_morphtarget
        objectName: "Eyelash_Upper_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Pupil_Contract_morphtarget
        objectName: "Eye_Pupil_Contract"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Pupil_Dilate_morphtarget
        objectName: "Eye_Pupil_Dilate"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Down_morphtarget
        objectName: "Eye_R_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_morphtarget
        objectName: "V_Tight"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Up_morphtarget
        objectName: "Eye_R_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Up_morphtarget
        objectName: "Eye_L_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_R_morphtarget
        objectName: "Eye_R_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_R_morphtarget
        objectName: "Eye_L_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_L_morphtarget
        objectName: "Eye_R_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_L_morphtarget
        objectName: "Eye_L_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_R_morphtarget
        objectName: "Eye_Wide_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_L_morphtarget
        objectName: "Eye_Wide_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_R_morphtarget
        objectName: "Eye_Squint_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_R_morphtarget
        objectName: "Tongue_Tip_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_L_morphtarget989
        objectName: "Jaw_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Forward_morphtarget988
        objectName: "Jaw_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Open_morphtarget987
        objectName: "Jaw_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Enlarge_morphtarget
        objectName: "Tongue_Enlarge"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Extend_morphtarget
        objectName: "Tongue_Extend"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_R_morphtarget984
        objectName: "Tongue_Bulge_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_L_morphtarget983
        objectName: "Tongue_Bulge_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Twist_R_morphtarget
        objectName: "Tongue_Twist_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Twist_L_morphtarget
        objectName: "Tongue_Twist_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_R_morphtarget990
        objectName: "Jaw_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_L_morphtarget
        objectName: "Tongue_Tip_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_R_morphtarget
        objectName: "Tongue_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_L_morphtarget
        objectName: "Tongue_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Roll_morphtarget
        objectName: "Tongue_Roll"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Wide_morphtarget
        objectName: "Tongue_Wide"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Narrow_morphtarget
        objectName: "Tongue_Narrow"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_Down_morphtarget
        objectName: "Tongue_Tip_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_Up_morphtarget
        objectName: "Tongue_Tip_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Mid_Up_morphtarget
        objectName: "Tongue_Mid_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_None_morphtarget1005
        objectName: "V_None"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_O_morphtarget
        objectName: "V_Tight_O"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Dental_Lip_morphtarget
        objectName: "V_Dental_Lip"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Explosive_morphtarget
        objectName: "V_Explosive"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Open_morphtarget
        objectName: "V_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_None_morphtarget1015
        objectName: "V_None"
        attributes: MorphTarget.Position
    }
    Skin {
        id: skin1014
        joints: [
            cc_Base_BoneRoot,
            cc_Base_Hip,
            cc_Base_Pelvis,
            cc_Base_L_Thigh,
            cc_Base_L_Calf,
            cc_Base_L_Foot,
            cc_Base_L_ToeBaseShareBone,
            cc_Base_L_ToeBase,
            cc_Base_L_PinkyToe1,
            cc_Base_L_RingToe1,
            cc_Base_L_MidToe1,
            cc_Base_L_IndexToe1,
            cc_Base_L_BigToe1,
            cc_Base_L_CalfTwist01,
            cc_Base_L_CalfTwist02,
            cc_Base_L_KneeShareBone,
            cc_Base_L_ThighTwist01,
            cc_Base_L_ThighTwist02,
            cc_Base_R_Thigh,
            cc_Base_R_Calf,
            cc_Base_R_KneeShareBone,
            cc_Base_R_Foot,
            cc_Base_R_ToeBase,
            cc_Base_R_BigToe1,
            cc_Base_R_PinkyToe1,
            cc_Base_R_RingToe1,
            cc_Base_R_IndexToe1,
            cc_Base_R_MidToe1,
            cc_Base_R_ToeBaseShareBone,
            cc_Base_R_CalfTwist01,
            cc_Base_R_CalfTwist02,
            cc_Base_R_ThighTwist01,
            cc_Base_R_ThighTwist02,
            cc_Base_Waist,
            cc_Base_Spine01,
            cc_Base_Spine02,
            cc_Base_NeckTwist01,
            cc_Base_NeckTwist02,
            cc_Base_Head,
            cc_Base_FacialBone,
            cc_Base_JawRoot,
            cc_Base_Tongue01,
            cc_Base_Tongue02,
            cc_Base_Tongue03,
            cc_Base_Teeth02,
            cc_Base_R_Eye,
            cc_Base_L_Eye,
            cc_Base_UpperJaw,
            cc_Base_Teeth01,
            cc_Base_L_Clavicle,
            cc_Base_L_Upperarm,
            cc_Base_L_Forearm,
            cc_Base_L_ForearmTwist01,
            cc_Base_L_ForearmTwist02,
            cc_Base_L_ElbowShareBone,
            cc_Base_L_Hand,
            cc_Base_L_Pinky1,
            cc_Base_L_Pinky2,
            cc_Base_L_Pinky3,
            cc_Base_L_Ring1,
            cc_Base_L_Ring2,
            cc_Base_L_Ring3,
            cc_Base_L_Mid1,
            cc_Base_L_Mid2,
            cc_Base_L_Mid3,
            cc_Base_L_Index1,
            cc_Base_L_Index2,
            cc_Base_L_Index3,
            cc_Base_L_Thumb1,
            cc_Base_L_Thumb2,
            cc_Base_L_Thumb3,
            cc_Base_L_UpperarmTwist01,
            cc_Base_L_UpperarmTwist02,
            cc_Base_L_RibsTwist,
            cc_Base_L_Breast,
            cc_Base_R_RibsTwist,
            cc_Base_R_Breast,
            cc_Base_R_Clavicle,
            cc_Base_R_Upperarm,
            cc_Base_R_Forearm,
            cc_Base_R_ElbowShareBone,
            cc_Base_R_ForearmTwist01,
            cc_Base_R_ForearmTwist02,
            cc_Base_R_Hand,
            cc_Base_R_Ring1,
            cc_Base_R_Ring2,
            cc_Base_R_Ring3,
            cc_Base_R_Mid1,
            cc_Base_R_Mid2,
            cc_Base_R_Mid3,
            cc_Base_R_Thumb1,
            cc_Base_R_Thumb2,
            cc_Base_R_Thumb3,
            cc_Base_R_Index1,
            cc_Base_R_Index2,
            cc_Base_R_Index3,
            cc_Base_R_Pinky1,
            cc_Base_R_Pinky2,
            cc_Base_R_Pinky3,
            cc_Base_R_UpperarmTwist01,
            cc_Base_R_UpperarmTwist02
        ]
        inverseBindPoses: [
            Qt.matrix4x4(100, 0, 0, 0, 0, 0, -100, 0, 0, 100, 0, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0, 0, 0, 0, 100, 0, -107.16, 0, 0, 100, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, -1.50763e-05, -1.50014e-06, 1.61558e-05, 1.50763e-05, 98.0392, 19.7056, -105.059, -1.50015e-06, -19.7056, 98.0392, 21.1165, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19943, -0.00154083, 7.15862, -2.19935, -99.9738, -0.625483, 104.87, -0.0155098, -0.625462, 99.9971, 1.10913, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.75838, -0.0421809, 7.4091, -1.7563, -99.9396, -2.99681, 56.7001, -0.0950633, -2.99579, 99.9542, 2.45743, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4254, 0.44619, 10.6957, 7.6864, 10.1705, -27.2384, 95.679, 2.96016, 3.3402, 96.2178, 27.0361, -5.07653, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8064, -4.35358, 4.44084, 8.50303, 4.05605, 8.5563, 99.5498, -11.5637, -4.714, 99.5381, -8.36324, -0.491555, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, -4.31662, 4.43681, 8.50295, 4.0552, 8.5548, 99.5499, -11.5636, -4.6768, 99.5398, -8.36343, -0.494889, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4797, -10.1827, 0.321515, 11.6262, 3.3234, -29.4543, 95.5052, -10.6293, -9.6305, 95.0197, 29.6391, -3.94976, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9388, -14.1291, 3.38768, 10.0395, 8.29467, -35.7843, 93.0083, -11.5382, -11.9292, 92.303, 36.5761, -5.2262, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, -11.9903, 6.4032, 8.33146, 8.90352, -21.6488, 97.2208, -13.2905, -10.271, 96.8894, 22.515, -4.04237, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, -12.9598, 6.3167, 6.8974, 9.26771, -23.6197, 96.7267, -13.2502, -11.0437, 96.3024, 24.5737, -4.53582, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, -4.20361, 6.53537, 4.82496, 6.44302, 2.29263, 99.765, -13.8397, -4.34362, 99.8853, -2.015, -1.1624, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.7602, -0.0420473, 7.40808, -1.75813, -99.9395, -2.99824, 56.7002, -0.0950096, -2.99723, 99.9541, 2.45824, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.76061, -0.0444752, 7.40838, -1.75846, -99.9395, -2.99852, 31.2084, -0.0974532, -2.99746, 99.9541, 2.45817, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, 1.85246, -3.25678, 7.32702, -1.75497, -99.9397, -2.99578, 56.7, -3.31055, -2.93671, 99.9012, 2.69389, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19789, -0.00126959, 7.16024, -2.19782, -99.9739, -0.620892, 104.87, -0.0151281, -0.620878, 99.9972, 1.10429, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.1979, -0.000876542, 7.16006, -2.19783, -99.9739, -0.620904, 80.8223, -0.0147355, -0.620899, 99.9972, 1.10544, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, -2.19924, 0.00153699, -7.16575, 2.1992, -99.9739, -0.625714, 104.872, 0.0151791, -0.625438, 99.9985, 1.10604, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75776, 0.0422092, -7.41643, 1.75572, -99.9397, -2.99703, 56.704, 0.0947457, -2.99573, 99.9556, 2.45444, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, -1.85182, 3.25683, -7.33445, 1.75438, -99.9397, -2.99601, 56.704, 3.31021, -2.93666, 99.9025, 2.69113, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4253, -0.445641, -10.6957, -7.69344, -10.1708, -27.2377, 95.6805, 2.9584, -3.33968, 96.218, 27.0361, -5.08513, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, 4.31673, -4.43678, -8.51101, -4.05543, 8.55508, 99.5513, -11.5765, 4.67691, 99.5398, -8.36358, -0.498814, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, 4.20418, -6.53536, -4.83289, -6.44323, 2.29301, 99.7664, -13.8527, 4.34419, 99.8853, -2.01513, -1.16698, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4796, 10.1835, -0.321472, -11.6342, -3.32385, -29.4536, 95.5067, -10.6366, 9.63116, 95.0199, 29.639, -3.95668, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9387, 14.1298, -3.38765, -10.0477, -8.29509, -35.7835, 93.0098, -11.5462, 11.9297, 92.3033, 36.576, -5.23363, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, 12.9605, -6.3167, -6.90615, -9.26806, -23.619, 96.7282, -13.2604, 11.0444, 96.3025, 24.5736, -4.5426, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, 11.9906, -6.40327, -8.33963, -8.90384, -21.6481, 97.2223, -13.3019, 10.2712, 96.8896, 22.5149, -4.04937, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8065, 4.35429, -4.43993, -8.5112, -4.05542, 8.5551, 99.5513, -11.5765, 4.71457, 99.5382, -8.36192, -0.495601, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75958, 0.0420813, -7.41542, 1.75754, -99.9396, -2.99846, 56.7041, 0.0946975, -2.99715, 99.9555, 2.45525, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75998, 0.0445132, -7.41571, 1.75787, -99.9396, -2.99877, 31.2144, 0.0971455, -2.99742, 99.9555, 2.45518, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.19769, 0.00128364, -7.16738, 2.19765, -99.9739, -0.621137, 104.872, 0.0148155, -0.620868, 99.9986, 1.10122, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.1977, 0.000890074, -7.16717, 2.19766, -99.9739, -0.621137, 80.8252, 0.0144221, -0.620877, 99.9986, 1.10237, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0595393, 0.0154999, -0.0669482, -0.0615188, 96.446, 26.423, -110.219, 0.000783055, -26.423, 96.446, 28.2733, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.00372025, 0.000168532, 0.00785771, 0.00372275, 99.9827, -1.86208, -117.476, -9.92306e-05, 1.86208, 99.9827, -5.07925, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0111038, 0.0023672, 0.0174147, 0.0113498, 97.2489, -23.2946, -126.012, 0.000284515, 23.2946, 97.249, -32.914, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0547365, -0.0101122, 0.0848241, 0.0556495, 98.7096, 16.0127, -152.92, 0.00121684, -16.0127, 98.7096, 28.2536, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0401262, -0.0105083, 0.0615821, 0.0414671, 96.0918, 27.6832, -151.999, -0.00101063, -27.6832, 96.0918, 46.7363, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.000265608, 6.35935e-05, -0.00285968, 0.000265636, 100, -0.0357807, -162.25, -6.34991e-05, 0.0357837, 100, 1.83509, 0, 0, 0, 1),
            Qt.matrix4x4(-0.000669168, 100, -0.0360327, -162.25, -6.24571e-05, 0.0360356, 100, 1.83469, 100, 0.000669196, 6.38568e-05, -0.00437637, 0, 0, 0, 1),
            Qt.matrix4x4(-0.00245299, 0.0400948, 100, -0.767438, -0.0145806, -100, 0.0400834, 163.645, 100, -0.0145796, 0.00246047, 0.0205602, 0, 0, 0, 1),
            Qt.matrix4x4(0.112315, -17.6141, 98.4365, 25.0468, -0.0182466, -98.4365, -17.6141, 160.852, 99.9999, 0.001822, -0.113771, -0.00270895, 0, 0, 0, 1),
            Qt.matrix4x4(0.120985, -36.4206, 93.1318, 54.7053, -0.0198629, -93.1319, -36.4206, 153.137, 99.9999, 0.0255649, -0.119909, -0.0410066, 0, 0, 0, 1),
            Qt.matrix4x4(0.121003, -36.42, 93.132, 52.9936, -0.0202164, -93.1321, -36.42, 153.137, 99.9999, 0.0252415, -0.120054, -0.0404762, 0, 0, 0, 1),
            Qt.matrix4x4(0.0169932, 0.0411495, 100, -4.08427, -0.0173491, 100, -0.0411355, -162.538, -100, -0.0173421, 0.0169987, 0.0252892, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0131955, -0.0139593, 3.48603, -0.0139637, -0.0207999, -100, 5.17964, 0.0131926, 100, -0.0207988, -168.877, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0126715, 0.0153175, -3.49781, 0.0153222, -0.0500856, -100, 5.23196, -0.0126638, 100, -0.0500845, -168.872, 0, 0, 0, 1),
            Qt.matrix4x4(0.00847962, 0.034713, 100, -4.58337, -0.000401467, -100, 0.0347213, 164.58, 100, -0.000404406, -0.00847784, -0.00446657, 0, 0, 0, 1),
            Qt.matrix4x4(0.00138361, 0.0389695, 100, -4.95796, 0.00525116, 100, -0.0389778, -164.247, -100, 0.00525169, 0.00137992, 0.00236788, 0, 0, 0, 1),
            Qt.matrix4x4(-1.88568, -99.8883, 4.33249, 149.837, 97.3862, -2.81603, -22.5387, -0.808774, 22.6356, 3.79424, 97.3305, -4.74137, 0, 0, 0, 1),
            Qt.matrix4x4(-49.807, -86.6412, 3.54302, 137.155, 86.7134, -49.7753, 1.79, 61.5499, 0.212671, 3.96382, 99.9212, -1.52919, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.5239, 136.91, 86.3604, -50.3177, 3.16266, 35.73, -0.95603, 4.63749, 99.8878, -2.00221, 0, 0, 0, 1),
            Qt.matrix4x4(-50.409, -86.2932, 3.52318, 136.91, 86.3598, -50.3188, 3.16266, 35.7316, -0.956336, 4.63688, 99.8879, -2.00127, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.52317, 136.91, 86.3604, -50.3177, 3.16351, 23.7177, -0.957131, 4.63729, 99.8878, -2.00141, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4649, -86.264, 3.43616, 136.888, 86.3275, -50.3797, 3.07288, 35.8233, -0.91966, 4.51709, 99.8937, -1.85184, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7679, -87.7827, 3.52396, 137.204, 87.3005, -47.8784, -9.28884, 7.72614, 9.84121, -1.36064, 99.5053, -0.92711, 0, 0, 0, 1),
            Qt.matrix4x4(-49.9004, -86.5883, 3.52285, 136.803, 86.6599, -49.8627, 1.94246, 2.44348, 0.0746406, 4.0222, 99.9191, 0.988494, 0, 0, 0, 1),
            Qt.matrix4x4(-52.663, -84.9267, 3.75148, 136.743, 85.0063, -52.648, 1.4555, 4.14878, 0.738971, 3.9555, 99.919, 0.612436, 0, 0, 0, 1),
            Qt.matrix4x4(-44.5186, -89.4714, 3.60109, 136.398, 89.4575, -44.6162, -2.59674, -10.0752, 3.93001, 2.06542, 99.9014, 0.6083, 0, 0, 0, 1),
            Qt.matrix4x4(-49.6224, -86.7491, 3.49327, 137.198, 86.8192, -49.5725, 2.23479, 1.7522, -0.206964, 4.14179, 99.914, -0.821401, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6708, -83.6615, 3.44216, 137.086, 83.7279, -54.6641, 1.21753, 5.93462, 0.863019, 3.54768, 99.9333, -0.868637, 0, 0, 0, 1),
            Qt.matrix4x4(-47.9847, -87.6646, 3.52107, 136.953, 87.7066, -48.0329, -0.627888, -6.90922, 2.24171, 2.78693, 99.936, -0.96638, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5574, -86.1786, 4.14779, 137.418, 86.2745, -50.4515, 3.36886, 2.85757, -0.810612, 5.2817, 99.8571, -3.58848, 0, 0, 0, 1),
            Qt.matrix4x4(-51.6067, -85.587, 3.40699, 137.448, 85.6431, -51.4929, 3.70805, 0.185814, -1.41925, 4.83145, 99.8731, -2.62696, 0, 0, 0, 1),
            Qt.matrix4x4(-48.7135, -87.2623, 3.50497, 137.288, 87.3183, -48.5935, 3.76532, -7.09703, -1.58252, 4.89471, 99.8676, -2.58154, 0, 0, 0, 1),
            Qt.matrix4x4(-50.7218, -86.0765, 4.25742, 137.125, 86.1791, -50.6972, 1.71972, 3.07359, 0.678116, 4.54128, 99.8945, -5.83135, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4655, -85.0736, 3.13906, 137.165, 85.1159, -52.3497, 3.84519, 2.04567, -1.62795, 4.68924, 99.8767, -4.38814, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0827, -87.615, 3.41648, 136.971, 87.574, -47.7943, 6.81865, -7.42734, -4.34128, 6.27054, 99.7087, -4.27729, 0, 0, 0, 1),
            Qt.matrix4x4(-64.961, -73.2123, 20.4945, 129.222, 59.5939, -32.2961, 73.5223, 4.4705, -47.2084, 59.9743, 64.61, -44.6085, 0, 0, 0, 1),
            Qt.matrix4x4(-57.9161, -77.0926, 26.5039, 129.246, 77.6561, -42.2805, 46.7107, 0.294844, -24.8045, 47.6349, 84.3543, -44.5523, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7869, -80.2894, 29.525, 128.919, 81.9393, -36.6397, 44.085, -11.843, -24.5778, 47.0228, 84.7632, -43.9857, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8061, -86.6307, 3.80604, 137.151, 86.7135, -49.775, 1.7906, 61.5495, 0.343252, 4.19218, 99.9115, -1.8906, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8068, -86.6414, 3.54283, 137.155, 86.7135, -49.775, 1.79084, 48.1756, 0.211837, 3.96408, 99.9212, -1.52922, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0121952, -0.0016524, 10.1203, -0.00110477, 4.47696, 99.8997, -19.2259, 0.0122569, 99.8997, -4.47694, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, 10.1202, -0.00114441, 4.47696, 99.8997, -21.2259, 0.0122638, 99.8997, -4.47693, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122068, -0.00170066, -10.1238, -0.00115246, 4.47694, 99.8997, -19.2055, 0.0122707, 99.8997, -4.47693, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, -10.1238, -0.00114441, 4.47695, 99.8997, -21.2055, 0.0122638, 99.8997, -4.47694, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-1.85887, 99.8888, -4.33163, -149.836, -97.3861, -2.78984, -22.5425, -0.846488, -22.6383, 3.79937, 97.3297, -4.74888, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7835, 86.6547, -3.54387, -137.187, -86.7269, -49.7519, 1.78613, 61.4895, -0.21537, 3.96269, 99.9212, -1.52094, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3848, 86.3073, -3.52505, -136.942, -86.374, -50.2947, 3.1588, 35.7086, 0.953363, 4.63628, 99.8879, -1.99405, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4418, 86.2775, -3.43736, -136.92, -86.3411, -50.3567, 3.06902, 35.8021, 0.91693, 4.51592, 99.8938, -1.84374, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3858, 86.3067, -3.52427, -136.942, -86.3734, -50.2957, 3.1588, 35.7102, 0.953702, 4.63562, 99.8879, -1.99303, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3847, 86.3073, -3.52431, -136.942, -86.374, -50.2946, 3.15966, 23.7108, 0.954484, 4.63607, 99.8879, -1.99325, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7442, 87.7956, -3.52487, -137.236, -87.313, -47.8549, -9.29271, 7.73164, -9.8454, -1.35906, 99.5049, -0.917997, 0, 0, 0, 1),
            Qt.matrix4x4(-49.5991, 86.7624, -3.49434, -137.229, -86.8325, -49.5493, 2.23093, 1.75948, 0.204188, 4.14074, 99.914, -0.813094, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6474, 83.6768, -3.44239, -137.118, -83.7431, -54.6408, 1.21375, 5.94218, -0.865323, 3.54604, 99.9334, -0.858772, 0, 0, 0, 1),
            Qt.matrix4x4(-47.961, 87.6774, -3.52205, -136.985, -87.7194, -48.0094, -0.63177, -6.9061, -2.24483, 2.78652, 99.936, -0.958057, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5341, 86.1921, -4.14882, -137.449, -86.2882, -50.4284, 3.365, 2.86407, 0.808178, 5.28042, 99.8572, -3.57899, 0, 0, 0, 1),
            Qt.matrix4x4(-51.5833, 85.6011, -3.40781, -137.478, -85.6572, -51.4697, 3.70416, 0.191616, 1.41681, 4.82976, 99.8732, -2.61691, 0, 0, 0, 1),
            Qt.matrix4x4(-48.6899, 87.2755, -3.50582, -137.319, -87.3316, -48.5701, 3.76144, -7.092, 1.58004, 4.89313, 99.8677, -2.5717, 0, 0, 0, 1),
            Qt.matrix4x4(-64.9407, 73.2298, -20.4965, -129.252, -59.6054, -32.281, 73.5196, 4.48364, 47.2218, 59.9611, 64.6124, -44.6136, 0, 0, 0, 1),
            Qt.matrix4x4(-57.8947, 77.1081, -26.5056, -129.278, -77.6691, -42.2604, 46.7073, 0.307031, 24.8138, 47.6277, 84.3557, -44.5532, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7624, 80.3053, -29.5247, -128.953, -81.9515, -36.6168, 44.0813, -11.8357, 24.5886, 47.0134, 84.7652, -43.9827, 0, 0, 0, 1),
            Qt.matrix4x4(-50.6986, 86.0901, -4.25856, -137.155, -86.1927, -50.6742, 1.71586, 3.08145, -0.680797, 4.54049, 99.8945, -5.81861, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4425, 85.0878, -3.14012, -137.195, -85.1302, -52.3269, 3.84136, 2.05416, 1.6254, 4.6877, 99.8769, -4.37503, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0592, 87.6278, -3.41758, -137.002, -87.587, -47.771, 6.81477, -7.42022, 4.33903, 6.26848, 99.709, -4.26478, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8771, 86.6017, -3.52394, -136.835, -86.6733, -49.8395, 1.93857, 2.44804, -0.0774823, 4.02122, 99.9191, 0.995909, 0, 0, 0, 1),
            Qt.matrix4x4(-52.6416, 84.9398, -3.75452, -136.775, -85.0194, -52.6268, 1.45174, 4.15666, -0.742781, 3.95629, 99.919, 0.617262, 0, 0, 0, 1),
            Qt.matrix4x4(-44.4949, 89.4831, -3.60251, -136.43, -89.4691, -44.5927, -2.60061, -10.0723, -3.93356, 2.06599, 99.9013, 0.615095, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7826, 86.644, -3.80768, -137.182, -86.727, -49.7518, 1.78673, 61.4894, -0.346297, 4.19176, 99.9115, -1.88352, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7834, 86.6548, -3.54388, -137.187, -86.727, -49.7518, 1.78696, 48.1346, -0.214659, 3.96311, 99.9212, -1.52125, 0, 0, 0, 1)
        ]
    }
    PrincipledMaterial {
        id: female_Angled_Base_Transparency_material
        objectName: "Female_Angled_Base_Transparency"
        baseColorMap: _26_texture
        roughness: 0.6837722063064575
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Blend
    }
    PrincipledMaterial {
        id: female_Angled_Transparency_material
        objectName: "Female_Angled_Transparency"
        baseColorMap: _24_texture
        roughness: 0.6837722063064575
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Blend
    }
    MorphTarget {
        id: tongue_Down_morphtarget
        objectName: "Tongue_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_None_morphtarget1004
        objectName: "V_None"
        attributes: MorphTarget.Position
    }
    Skin {
        id: skin1003
        joints: [
            cc_Base_BoneRoot,
            cc_Base_Hip,
            cc_Base_Pelvis,
            cc_Base_L_Thigh,
            cc_Base_L_Calf,
            cc_Base_L_Foot,
            cc_Base_L_ToeBaseShareBone,
            cc_Base_L_ToeBase,
            cc_Base_L_PinkyToe1,
            cc_Base_L_RingToe1,
            cc_Base_L_MidToe1,
            cc_Base_L_IndexToe1,
            cc_Base_L_BigToe1,
            cc_Base_L_CalfTwist01,
            cc_Base_L_CalfTwist02,
            cc_Base_L_KneeShareBone,
            cc_Base_L_ThighTwist01,
            cc_Base_L_ThighTwist02,
            cc_Base_R_Thigh,
            cc_Base_R_Calf,
            cc_Base_R_KneeShareBone,
            cc_Base_R_Foot,
            cc_Base_R_ToeBase,
            cc_Base_R_BigToe1,
            cc_Base_R_PinkyToe1,
            cc_Base_R_RingToe1,
            cc_Base_R_IndexToe1,
            cc_Base_R_MidToe1,
            cc_Base_R_ToeBaseShareBone,
            cc_Base_R_CalfTwist01,
            cc_Base_R_CalfTwist02,
            cc_Base_R_ThighTwist01,
            cc_Base_R_ThighTwist02,
            cc_Base_Waist,
            cc_Base_Spine01,
            cc_Base_Spine02,
            cc_Base_NeckTwist01,
            cc_Base_NeckTwist02,
            cc_Base_Head,
            cc_Base_FacialBone,
            cc_Base_JawRoot,
            cc_Base_Tongue01,
            cc_Base_Tongue02,
            cc_Base_Tongue03,
            cc_Base_Teeth02,
            cc_Base_R_Eye,
            cc_Base_L_Eye,
            cc_Base_UpperJaw,
            cc_Base_Teeth01,
            cc_Base_L_Clavicle,
            cc_Base_L_Upperarm,
            cc_Base_L_Forearm,
            cc_Base_L_ForearmTwist01,
            cc_Base_L_ForearmTwist02,
            cc_Base_L_ElbowShareBone,
            cc_Base_L_Hand,
            cc_Base_L_Pinky1,
            cc_Base_L_Pinky2,
            cc_Base_L_Pinky3,
            cc_Base_L_Ring1,
            cc_Base_L_Ring2,
            cc_Base_L_Ring3,
            cc_Base_L_Mid1,
            cc_Base_L_Mid2,
            cc_Base_L_Mid3,
            cc_Base_L_Index1,
            cc_Base_L_Index2,
            cc_Base_L_Index3,
            cc_Base_L_Thumb1,
            cc_Base_L_Thumb2,
            cc_Base_L_Thumb3,
            cc_Base_L_UpperarmTwist01,
            cc_Base_L_UpperarmTwist02,
            cc_Base_L_RibsTwist,
            cc_Base_L_Breast,
            cc_Base_R_RibsTwist,
            cc_Base_R_Breast,
            cc_Base_R_Clavicle,
            cc_Base_R_Upperarm,
            cc_Base_R_Forearm,
            cc_Base_R_ElbowShareBone,
            cc_Base_R_ForearmTwist01,
            cc_Base_R_ForearmTwist02,
            cc_Base_R_Hand,
            cc_Base_R_Ring1,
            cc_Base_R_Ring2,
            cc_Base_R_Ring3,
            cc_Base_R_Mid1,
            cc_Base_R_Mid2,
            cc_Base_R_Mid3,
            cc_Base_R_Thumb1,
            cc_Base_R_Thumb2,
            cc_Base_R_Thumb3,
            cc_Base_R_Index1,
            cc_Base_R_Index2,
            cc_Base_R_Index3,
            cc_Base_R_Pinky1,
            cc_Base_R_Pinky2,
            cc_Base_R_Pinky3,
            cc_Base_R_UpperarmTwist01,
            cc_Base_R_UpperarmTwist02
        ]
        inverseBindPoses: [
            Qt.matrix4x4(100, 0, 0, 0, 0, 0, -100, 0, 0, 100, 0, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0, 0, 0, 0, 100, 0, -107.16, 0, 0, 100, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, -1.50763e-05, -1.50014e-06, 1.61558e-05, 1.50763e-05, 98.0392, 19.7056, -105.059, -1.50015e-06, -19.7056, 98.0392, 21.1165, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19943, -0.00154083, 7.15862, -2.19935, -99.9738, -0.625483, 104.87, -0.0155098, -0.625462, 99.9971, 1.10913, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.75838, -0.0421809, 7.4091, -1.7563, -99.9396, -2.99681, 56.7001, -0.0950633, -2.99579, 99.9542, 2.45743, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4254, 0.44619, 10.6957, 7.6864, 10.1705, -27.2384, 95.679, 2.96016, 3.3402, 96.2178, 27.0361, -5.07653, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8064, -4.35358, 4.44084, 8.50303, 4.05605, 8.5563, 99.5498, -11.5637, -4.714, 99.5381, -8.36324, -0.491555, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, -4.31662, 4.43681, 8.50295, 4.0552, 8.5548, 99.5499, -11.5636, -4.6768, 99.5398, -8.36343, -0.494889, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4797, -10.1827, 0.321515, 11.6262, 3.3234, -29.4543, 95.5052, -10.6293, -9.6305, 95.0197, 29.6391, -3.94976, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9388, -14.1291, 3.38768, 10.0395, 8.29467, -35.7843, 93.0083, -11.5382, -11.9292, 92.303, 36.5761, -5.2262, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, -11.9903, 6.4032, 8.33146, 8.90352, -21.6488, 97.2208, -13.2905, -10.271, 96.8894, 22.515, -4.04237, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, -12.9598, 6.3167, 6.8974, 9.26771, -23.6197, 96.7267, -13.2502, -11.0437, 96.3024, 24.5737, -4.53582, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, -4.20361, 6.53537, 4.82496, 6.44302, 2.29263, 99.765, -13.8397, -4.34362, 99.8853, -2.015, -1.1624, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.7602, -0.0420473, 7.40808, -1.75813, -99.9395, -2.99824, 56.7002, -0.0950096, -2.99723, 99.9541, 2.45824, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.76061, -0.0444752, 7.40838, -1.75846, -99.9395, -2.99852, 31.2084, -0.0974532, -2.99746, 99.9541, 2.45817, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, 1.85246, -3.25678, 7.32702, -1.75497, -99.9397, -2.99578, 56.7, -3.31055, -2.93671, 99.9012, 2.69389, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19789, -0.00126959, 7.16024, -2.19782, -99.9739, -0.620892, 104.87, -0.0151281, -0.620878, 99.9972, 1.10429, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.1979, -0.000876542, 7.16006, -2.19783, -99.9739, -0.620904, 80.8223, -0.0147355, -0.620899, 99.9972, 1.10544, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, -2.19924, 0.00153699, -7.16575, 2.1992, -99.9739, -0.625714, 104.872, 0.0151791, -0.625438, 99.9985, 1.10604, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75776, 0.0422092, -7.41643, 1.75572, -99.9397, -2.99703, 56.704, 0.0947457, -2.99573, 99.9556, 2.45444, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, -1.85182, 3.25683, -7.33445, 1.75438, -99.9397, -2.99601, 56.704, 3.31021, -2.93666, 99.9025, 2.69113, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4253, -0.445641, -10.6957, -7.69344, -10.1708, -27.2377, 95.6805, 2.9584, -3.33968, 96.218, 27.0361, -5.08513, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, 4.31673, -4.43678, -8.51101, -4.05543, 8.55508, 99.5513, -11.5765, 4.67691, 99.5398, -8.36358, -0.498814, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, 4.20418, -6.53536, -4.83289, -6.44323, 2.29301, 99.7664, -13.8527, 4.34419, 99.8853, -2.01513, -1.16698, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4796, 10.1835, -0.321472, -11.6342, -3.32385, -29.4536, 95.5067, -10.6366, 9.63116, 95.0199, 29.639, -3.95668, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9387, 14.1298, -3.38765, -10.0477, -8.29509, -35.7835, 93.0098, -11.5462, 11.9297, 92.3033, 36.576, -5.23363, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, 12.9605, -6.3167, -6.90615, -9.26806, -23.619, 96.7282, -13.2604, 11.0444, 96.3025, 24.5736, -4.5426, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, 11.9906, -6.40327, -8.33963, -8.90384, -21.6481, 97.2223, -13.3019, 10.2712, 96.8896, 22.5149, -4.04937, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8065, 4.35429, -4.43993, -8.5112, -4.05542, 8.5551, 99.5513, -11.5765, 4.71457, 99.5382, -8.36192, -0.495601, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75958, 0.0420813, -7.41542, 1.75754, -99.9396, -2.99846, 56.7041, 0.0946975, -2.99715, 99.9555, 2.45525, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75998, 0.0445132, -7.41571, 1.75787, -99.9396, -2.99877, 31.2144, 0.0971455, -2.99742, 99.9555, 2.45518, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.19769, 0.00128364, -7.16738, 2.19765, -99.9739, -0.621137, 104.872, 0.0148155, -0.620868, 99.9986, 1.10122, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.1977, 0.000890074, -7.16717, 2.19766, -99.9739, -0.621137, 80.8252, 0.0144221, -0.620877, 99.9986, 1.10237, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0595393, 0.0154999, -0.0669482, -0.0615188, 96.446, 26.423, -110.219, 0.000783055, -26.423, 96.446, 28.2733, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.00372025, 0.000168532, 0.00785771, 0.00372275, 99.9827, -1.86208, -117.476, -9.92306e-05, 1.86208, 99.9827, -5.07925, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0111038, 0.0023672, 0.0174147, 0.0113498, 97.2489, -23.2946, -126.012, 0.000284515, 23.2946, 97.249, -32.914, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0547365, -0.0101122, 0.0848241, 0.0556495, 98.7096, 16.0127, -152.92, 0.00121684, -16.0127, 98.7096, 28.2536, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0401262, -0.0105083, 0.0615821, 0.0414671, 96.0918, 27.6832, -151.999, -0.00101063, -27.6832, 96.0918, 46.7363, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.000265608, 6.35935e-05, -0.00285968, 0.000265636, 100, -0.0357807, -162.25, -6.34991e-05, 0.0357837, 100, 1.83509, 0, 0, 0, 1),
            Qt.matrix4x4(-0.000669168, 100, -0.0360327, -162.25, -6.24571e-05, 0.0360356, 100, 1.83469, 100, 0.000669196, 6.38568e-05, -0.00437637, 0, 0, 0, 1),
            Qt.matrix4x4(-0.00245299, 0.0400948, 100, -0.767438, -0.0145806, -100, 0.0400834, 163.645, 100, -0.0145796, 0.00246047, 0.0205602, 0, 0, 0, 1),
            Qt.matrix4x4(0.112315, -17.6141, 98.4365, 25.0468, -0.0182466, -98.4365, -17.6141, 160.852, 99.9999, 0.001822, -0.113771, -0.00270895, 0, 0, 0, 1),
            Qt.matrix4x4(0.120985, -36.4206, 93.1318, 54.7053, -0.0198629, -93.1319, -36.4206, 153.137, 99.9999, 0.0255649, -0.119909, -0.0410066, 0, 0, 0, 1),
            Qt.matrix4x4(0.121003, -36.42, 93.132, 52.9936, -0.0202164, -93.1321, -36.42, 153.137, 99.9999, 0.0252415, -0.120054, -0.0404762, 0, 0, 0, 1),
            Qt.matrix4x4(0.0169932, 0.0411495, 100, -4.08427, -0.0173491, 100, -0.0411355, -162.538, -100, -0.0173421, 0.0169987, 0.0252892, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0131955, -0.0139593, 3.48603, -0.0139637, -0.0207999, -100, 5.17964, 0.0131926, 100, -0.0207988, -168.877, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0126715, 0.0153175, -3.49781, 0.0153222, -0.0500856, -100, 5.23196, -0.0126638, 100, -0.0500845, -168.872, 0, 0, 0, 1),
            Qt.matrix4x4(0.00847962, 0.034713, 100, -4.58337, -0.000401467, -100, 0.0347213, 164.58, 100, -0.000404406, -0.00847784, -0.00446657, 0, 0, 0, 1),
            Qt.matrix4x4(0.00138361, 0.0389695, 100, -4.95796, 0.00525116, 100, -0.0389778, -164.247, -100, 0.00525169, 0.00137992, 0.00236788, 0, 0, 0, 1),
            Qt.matrix4x4(-1.88568, -99.8883, 4.33249, 149.837, 97.3862, -2.81603, -22.5387, -0.808774, 22.6356, 3.79424, 97.3305, -4.74137, 0, 0, 0, 1),
            Qt.matrix4x4(-49.807, -86.6412, 3.54302, 137.155, 86.7134, -49.7753, 1.79, 61.5499, 0.212671, 3.96382, 99.9212, -1.52919, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.5239, 136.91, 86.3604, -50.3177, 3.16266, 35.73, -0.95603, 4.63749, 99.8878, -2.00221, 0, 0, 0, 1),
            Qt.matrix4x4(-50.409, -86.2932, 3.52318, 136.91, 86.3598, -50.3188, 3.16266, 35.7316, -0.956336, 4.63688, 99.8879, -2.00127, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.52317, 136.91, 86.3604, -50.3177, 3.16351, 23.7177, -0.957131, 4.63729, 99.8878, -2.00141, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4649, -86.264, 3.43616, 136.888, 86.3275, -50.3797, 3.07288, 35.8233, -0.91966, 4.51709, 99.8937, -1.85184, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7679, -87.7827, 3.52396, 137.204, 87.3005, -47.8784, -9.28884, 7.72614, 9.84121, -1.36064, 99.5053, -0.92711, 0, 0, 0, 1),
            Qt.matrix4x4(-49.9004, -86.5883, 3.52285, 136.803, 86.6599, -49.8627, 1.94246, 2.44348, 0.0746406, 4.0222, 99.9191, 0.988494, 0, 0, 0, 1),
            Qt.matrix4x4(-52.663, -84.9267, 3.75148, 136.743, 85.0063, -52.648, 1.4555, 4.14878, 0.738971, 3.9555, 99.919, 0.612436, 0, 0, 0, 1),
            Qt.matrix4x4(-44.5186, -89.4714, 3.60109, 136.398, 89.4575, -44.6162, -2.59674, -10.0752, 3.93001, 2.06542, 99.9014, 0.6083, 0, 0, 0, 1),
            Qt.matrix4x4(-49.6224, -86.7491, 3.49327, 137.198, 86.8192, -49.5725, 2.23479, 1.7522, -0.206964, 4.14179, 99.914, -0.821401, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6708, -83.6615, 3.44216, 137.086, 83.7279, -54.6641, 1.21753, 5.93462, 0.863019, 3.54768, 99.9333, -0.868637, 0, 0, 0, 1),
            Qt.matrix4x4(-47.9847, -87.6646, 3.52107, 136.953, 87.7066, -48.0329, -0.627888, -6.90922, 2.24171, 2.78693, 99.936, -0.96638, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5574, -86.1786, 4.14779, 137.418, 86.2745, -50.4515, 3.36886, 2.85757, -0.810612, 5.2817, 99.8571, -3.58848, 0, 0, 0, 1),
            Qt.matrix4x4(-51.6067, -85.587, 3.40699, 137.448, 85.6431, -51.4929, 3.70805, 0.185814, -1.41925, 4.83145, 99.8731, -2.62696, 0, 0, 0, 1),
            Qt.matrix4x4(-48.7135, -87.2623, 3.50497, 137.288, 87.3183, -48.5935, 3.76532, -7.09703, -1.58252, 4.89471, 99.8676, -2.58154, 0, 0, 0, 1),
            Qt.matrix4x4(-50.7218, -86.0765, 4.25742, 137.125, 86.1791, -50.6972, 1.71972, 3.07359, 0.678116, 4.54128, 99.8945, -5.83135, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4655, -85.0736, 3.13906, 137.165, 85.1159, -52.3497, 3.84519, 2.04567, -1.62795, 4.68924, 99.8767, -4.38814, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0827, -87.615, 3.41648, 136.971, 87.574, -47.7943, 6.81865, -7.42734, -4.34128, 6.27054, 99.7087, -4.27729, 0, 0, 0, 1),
            Qt.matrix4x4(-64.961, -73.2123, 20.4945, 129.222, 59.5939, -32.2961, 73.5223, 4.4705, -47.2084, 59.9743, 64.61, -44.6085, 0, 0, 0, 1),
            Qt.matrix4x4(-57.9161, -77.0926, 26.5039, 129.246, 77.6561, -42.2805, 46.7107, 0.294844, -24.8045, 47.6349, 84.3543, -44.5523, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7869, -80.2894, 29.525, 128.919, 81.9393, -36.6397, 44.085, -11.843, -24.5778, 47.0228, 84.7632, -43.9857, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8061, -86.6307, 3.80604, 137.151, 86.7135, -49.775, 1.7906, 61.5495, 0.343252, 4.19218, 99.9115, -1.8906, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8068, -86.6414, 3.54283, 137.155, 86.7135, -49.775, 1.79084, 48.1756, 0.211837, 3.96408, 99.9212, -1.52922, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0121952, -0.0016524, 10.1203, -0.00110477, 4.47696, 99.8997, -19.2259, 0.0122569, 99.8997, -4.47694, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, 10.1202, -0.00114441, 4.47696, 99.8997, -21.2259, 0.0122638, 99.8997, -4.47693, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122068, -0.00170066, -10.1238, -0.00115246, 4.47694, 99.8997, -19.2055, 0.0122707, 99.8997, -4.47693, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, -10.1238, -0.00114441, 4.47695, 99.8997, -21.2055, 0.0122638, 99.8997, -4.47694, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-1.85887, 99.8888, -4.33163, -149.836, -97.3861, -2.78984, -22.5425, -0.846488, -22.6383, 3.79937, 97.3297, -4.74888, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7835, 86.6547, -3.54387, -137.187, -86.7269, -49.7519, 1.78613, 61.4895, -0.21537, 3.96269, 99.9212, -1.52094, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3848, 86.3073, -3.52505, -136.942, -86.374, -50.2947, 3.1588, 35.7086, 0.953363, 4.63628, 99.8879, -1.99405, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4418, 86.2775, -3.43736, -136.92, -86.3411, -50.3567, 3.06902, 35.8021, 0.91693, 4.51592, 99.8938, -1.84374, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3858, 86.3067, -3.52427, -136.942, -86.3734, -50.2957, 3.1588, 35.7102, 0.953702, 4.63562, 99.8879, -1.99303, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3847, 86.3073, -3.52431, -136.942, -86.374, -50.2946, 3.15966, 23.7108, 0.954484, 4.63607, 99.8879, -1.99325, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7442, 87.7956, -3.52487, -137.236, -87.313, -47.8549, -9.29271, 7.73164, -9.8454, -1.35906, 99.5049, -0.917997, 0, 0, 0, 1),
            Qt.matrix4x4(-49.5991, 86.7624, -3.49434, -137.229, -86.8325, -49.5493, 2.23093, 1.75948, 0.204188, 4.14074, 99.914, -0.813094, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6474, 83.6768, -3.44239, -137.118, -83.7431, -54.6408, 1.21375, 5.94218, -0.865323, 3.54604, 99.9334, -0.858772, 0, 0, 0, 1),
            Qt.matrix4x4(-47.961, 87.6774, -3.52205, -136.985, -87.7194, -48.0094, -0.63177, -6.9061, -2.24483, 2.78652, 99.936, -0.958057, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5341, 86.1921, -4.14882, -137.449, -86.2882, -50.4284, 3.365, 2.86407, 0.808178, 5.28042, 99.8572, -3.57899, 0, 0, 0, 1),
            Qt.matrix4x4(-51.5833, 85.6011, -3.40781, -137.478, -85.6572, -51.4697, 3.70416, 0.191616, 1.41681, 4.82976, 99.8732, -2.61691, 0, 0, 0, 1),
            Qt.matrix4x4(-48.6899, 87.2755, -3.50582, -137.319, -87.3316, -48.5701, 3.76144, -7.092, 1.58004, 4.89313, 99.8677, -2.5717, 0, 0, 0, 1),
            Qt.matrix4x4(-64.9407, 73.2298, -20.4965, -129.252, -59.6054, -32.281, 73.5196, 4.48364, 47.2218, 59.9611, 64.6124, -44.6136, 0, 0, 0, 1),
            Qt.matrix4x4(-57.8947, 77.1081, -26.5056, -129.278, -77.6691, -42.2604, 46.7073, 0.307031, 24.8138, 47.6277, 84.3557, -44.5532, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7624, 80.3053, -29.5247, -128.953, -81.9515, -36.6168, 44.0813, -11.8357, 24.5886, 47.0134, 84.7652, -43.9827, 0, 0, 0, 1),
            Qt.matrix4x4(-50.6986, 86.0901, -4.25856, -137.155, -86.1927, -50.6742, 1.71586, 3.08145, -0.680797, 4.54049, 99.8945, -5.81861, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4425, 85.0878, -3.14012, -137.195, -85.1302, -52.3269, 3.84136, 2.05416, 1.6254, 4.6877, 99.8769, -4.37503, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0592, 87.6278, -3.41758, -137.002, -87.587, -47.771, 6.81477, -7.42022, 4.33903, 6.26848, 99.709, -4.26478, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8771, 86.6017, -3.52394, -136.835, -86.6733, -49.8395, 1.93857, 2.44804, -0.0774823, 4.02122, 99.9191, 0.995909, 0, 0, 0, 1),
            Qt.matrix4x4(-52.6416, 84.9398, -3.75452, -136.775, -85.0194, -52.6268, 1.45174, 4.15666, -0.742781, 3.95629, 99.919, 0.617262, 0, 0, 0, 1),
            Qt.matrix4x4(-44.4949, 89.4831, -3.60251, -136.43, -89.4691, -44.5927, -2.60061, -10.0723, -3.93356, 2.06599, 99.9013, 0.615095, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7826, 86.644, -3.80768, -137.182, -86.727, -49.7518, 1.78673, 61.4894, -0.346297, 4.19176, 99.9115, -1.88352, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7834, 86.6548, -3.54388, -137.187, -86.727, -49.7518, 1.78696, 48.1346, -0.214659, 3.96311, 99.9212, -1.52125, 0, 0, 0, 1)
        ]
    }
    PrincipledMaterial {
        id: mouth_material
        objectName: "Mouth"
        baseColorMap: _23_texture
        roughness: 0.16333997249603271
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: teeth_material
        objectName: "Teeth"
        baseColorMap: _22_texture
        roughness: 0.2928932309150696
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    MorphTarget {
        id: head_Backward_morphtarget994
        objectName: "Head_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_L_morphtarget993
        objectName: "Head_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Down_morphtarget992
        objectName: "Jaw_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Up_morphtarget991
        objectName: "Jaw_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_L_morphtarget769
        objectName: "Head_Tilt_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_morphtarget779
        objectName: "V_Tight"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_O_morphtarget778
        objectName: "V_Tight_O"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Dental_Lip_morphtarget777
        objectName: "V_Dental_Lip"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Explosive_morphtarget776
        objectName: "V_Explosive"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Open_morphtarget775
        objectName: "V_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Backward_morphtarget774
        objectName: "Head_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Forward_morphtarget773
        objectName: "Head_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_R_morphtarget772
        objectName: "Head_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_L_morphtarget771
        objectName: "Head_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_R_morphtarget770
        objectName: "Head_Tilt_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Wide_morphtarget780
        objectName: "V_Wide"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_R_morphtarget768
        objectName: "Head_Turn_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_L_morphtarget767
        objectName: "Head_Turn_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Down_morphtarget766
        objectName: "Head_Turn_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Up_morphtarget765
        objectName: "Head_Turn_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_R_morphtarget764
        objectName: "Neck_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_L_morphtarget763
        objectName: "Neck_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Down_morphtarget762
        objectName: "Neck_Swallow_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Up_morphtarget761
        objectName: "Neck_Swallow_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Down_morphtarget760
        objectName: "Jaw_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Up_morphtarget759
        objectName: "Jaw_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_R_morphtarget790
        objectName: "Brow_Compress_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_R_morphtarget800
        objectName: "Eye_R_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_R_morphtarget799
        objectName: "Eye_L_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_L_morphtarget798
        objectName: "Eye_R_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_L_morphtarget797
        objectName: "Eye_L_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_R_morphtarget796
        objectName: "Eye_Wide_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_L_morphtarget795
        objectName: "Eye_Wide_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_R_morphtarget794
        objectName: "Eye_Squint_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_L_morphtarget793
        objectName: "Eye_Squint_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_R_morphtarget792
        objectName: "Eye_Blink_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_L_morphtarget791
        objectName: "Eye_Blink_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_R_morphtarget758
        objectName: "Jaw_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_L_morphtarget789
        objectName: "Brow_Compress_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_R_morphtarget788
        objectName: "Brow_Drop_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_L_morphtarget787
        objectName: "Brow_Drop_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_R_morphtarget786
        objectName: "Brow_Raise_Outer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_L_morphtarget785
        objectName: "Brow_Raise_Outer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_R_morphtarget784
        objectName: "Brow_Raise_Inner_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_L_morphtarget783
        objectName: "Brow_Raise_Inner_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Lip_Open_morphtarget782
        objectName: "V_Lip_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Affricate_morphtarget781
        objectName: "V_Affricate"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_R_morphtarget
        objectName: "Mouth_Push_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_R_morphtarget
        objectName: "Mouth_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_L_morphtarget735
        objectName: "Mouth_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_morphtarget
        objectName: "Mouth_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_morphtarget
        objectName: "Mouth_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_R_morphtarget
        objectName: "Mouth_Pull_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_L_morphtarget
        objectName: "Mouth_Pull_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_R_morphtarget
        objectName: "Mouth_Pull_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_L_morphtarget
        objectName: "Mouth_Pull_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_R_morphtarget
        objectName: "Mouth_Push_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_L_morphtarget
        objectName: "Mouth_Push_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_L_morphtarget
        objectName: "Mouth_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_L_morphtarget
        objectName: "Mouth_Push_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_R_morphtarget
        objectName: "Mouth_Roll_Out_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_L_morphtarget
        objectName: "Mouth_Roll_Out_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_R_morphtarget
        objectName: "Mouth_Roll_Out_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_L_morphtarget
        objectName: "Mouth_Roll_Out_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_R_morphtarget
        objectName: "Mouth_Roll_In_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_L_morphtarget
        objectName: "Mouth_Roll_In_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_R_morphtarget
        objectName: "Mouth_Roll_In_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_L_morphtarget
        objectName: "Mouth_Roll_In_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: rightFrontForward_morphtarget
        objectName: "RightFrontForward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_L_morphtarget747
        objectName: "Mouth_Down_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_L_morphtarget757
        objectName: "Jaw_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Backward_morphtarget756
        objectName: "Jaw_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Forward_morphtarget755
        objectName: "Jaw_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Open_morphtarget754
        objectName: "Jaw_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_R_morphtarget753
        objectName: "Tongue_Bulge_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_L_morphtarget752
        objectName: "Tongue_Bulge_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Contract_morphtarget751
        objectName: "Mouth_Contract"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Close_morphtarget750
        objectName: "Mouth_Close"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Chin_Up_morphtarget749
        objectName: "Mouth_Chin_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_R_morphtarget748
        objectName: "Mouth_Down_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Up_morphtarget801
        objectName: "Eye_L_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_R_morphtarget746
        objectName: "Mouth_Up_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_L_morphtarget745
        objectName: "Mouth_Up_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Lower_morphtarget744
        objectName: "Mouth_Drop_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Upper_morphtarget743
        objectName: "Mouth_Drop_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Lower_morphtarget742
        objectName: "Mouth_Shrug_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Upper_morphtarget741
        objectName: "Mouth_Shrug_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_R_morphtarget740
        objectName: "Mouth_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_L_morphtarget739
        objectName: "Mouth_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_R_morphtarget
        objectName: "Mouth_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_R_morphtarget
        objectName: "Mouth_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_R_morphtarget864
        objectName: "Mouth_Funnel_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_L_morphtarget
        objectName: "Mouth_Funnel_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_R_morphtarget
        objectName: "Mouth_Funnel_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_L_morphtarget
        objectName: "Mouth_Funnel_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_R_morphtarget
        objectName: "Mouth_Pucker_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_L_morphtarget
        objectName: "Mouth_Pucker_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_R_morphtarget
        objectName: "Mouth_Pucker_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_L_morphtarget
        objectName: "Mouth_Pucker_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_R_morphtarget
        objectName: "Mouth_Blow_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_L_morphtarget
        objectName: "Mouth_Blow_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_L_morphtarget865
        objectName: "Mouth_Roll_In_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_L_morphtarget
        objectName: "Mouth_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_R_morphtarget
        objectName: "Mouth_Press_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_L_morphtarget
        objectName: "Mouth_Press_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_R_morphtarget
        objectName: "Mouth_Dimple_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_L_morphtarget
        objectName: "Mouth_Dimple_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_R_morphtarget
        objectName: "Mouth_Stretch_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_L_morphtarget
        objectName: "Mouth_Stretch_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_R_morphtarget
        objectName: "Mouth_Frown_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_L_morphtarget
        objectName: "Mouth_Frown_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_R_morphtarget
        objectName: "Mouth_Smile_Sharp_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_L_morphtarget875
        objectName: "Mouth_Push_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_L_morphtarget885
        objectName: "Mouth_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_R_morphtarget884
        objectName: "Mouth_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_L_morphtarget883
        objectName: "Mouth_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_morphtarget882
        objectName: "Mouth_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_morphtarget881
        objectName: "Mouth_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_R_morphtarget880
        objectName: "Mouth_Pull_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_L_morphtarget879
        objectName: "Mouth_Pull_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_R_morphtarget878
        objectName: "Mouth_Pull_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_L_morphtarget877
        objectName: "Mouth_Pull_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_R_morphtarget876
        objectName: "Mouth_Push_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_L_morphtarget
        objectName: "Mouth_Smile_Sharp_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_R_morphtarget874
        objectName: "Mouth_Push_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_L_morphtarget873
        objectName: "Mouth_Push_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_R_morphtarget872
        objectName: "Mouth_Roll_Out_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_L_morphtarget871
        objectName: "Mouth_Roll_Out_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_R_morphtarget870
        objectName: "Mouth_Roll_Out_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_L_morphtarget869
        objectName: "Mouth_Roll_Out_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_R_morphtarget868
        objectName: "Mouth_Roll_In_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_L_morphtarget867
        objectName: "Mouth_Roll_In_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_R_morphtarget866
        objectName: "Mouth_Roll_In_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_R_morphtarget
        objectName: "Eyelash_Lower_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_L_morphtarget
        objectName: "Nose_Nostril_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_R_morphtarget
        objectName: "Nose_Sneer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_L_morphtarget
        objectName: "Nose_Sneer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_R_morphtarget
        objectName: "Ear_Out_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_L_morphtarget
        objectName: "Ear_Out_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_R_morphtarget
        objectName: "Ear_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_L_morphtarget
        objectName: "Ear_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_R_morphtarget
        objectName: "Ear_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_L_morphtarget
        objectName: "Ear_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_R_morphtarget
        objectName: "Eyelash_Lower_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_R_morphtarget
        objectName: "Nose_Nostril_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_L_morphtarget810
        objectName: "Eyelash_Lower_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_L_morphtarget809
        objectName: "Eyelash_Lower_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_R_morphtarget808
        objectName: "Eyelash_Upper_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_R_morphtarget807
        objectName: "Eyelash_Upper_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_L_morphtarget806
        objectName: "Eyelash_Upper_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_L_morphtarget805
        objectName: "Eyelash_Upper_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Down_morphtarget804
        objectName: "Eye_R_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Down_morphtarget803
        objectName: "Eye_L_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Up_morphtarget802
        objectName: "Eye_R_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_R_morphtarget
        objectName: "Nose_Tip_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_R_morphtarget
        objectName: "Mouth_Smile_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_L_morphtarget
        objectName: "Mouth_Smile_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_R_morphtarget
        objectName: "Cheek_Puff_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_L_morphtarget
        objectName: "Cheek_Puff_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_R_morphtarget
        objectName: "Cheek_Suck_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_L_morphtarget
        objectName: "Cheek_Suck_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_R_morphtarget
        objectName: "Cheek_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_L_morphtarget
        objectName: "Cheek_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Down_morphtarget
        objectName: "Nose_Tip_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Up_morphtarget
        objectName: "Nose_Tip_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_R_morphtarget886
        objectName: "Mouth_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_L_morphtarget
        objectName: "Nose_Tip_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_R_morphtarget
        objectName: "Nose_Nostril_In_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_L_morphtarget
        objectName: "Nose_Nostril_In_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_R_morphtarget
        objectName: "Nose_Nostril_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_L_morphtarget
        objectName: "Nose_Nostril_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_R_morphtarget
        objectName: "Nose_Crease_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_L_morphtarget
        objectName: "Nose_Crease_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_R_morphtarget
        objectName: "Nose_Nostril_Dilate_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_L_morphtarget
        objectName: "Nose_Nostril_Dilate_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_L_morphtarget1285
        objectName: "Mouth_Pucker_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_L_morphtarget1295
        objectName: "Mouth_Roll_Out_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_R_morphtarget1294
        objectName: "Mouth_Roll_In_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_L_morphtarget1293
        objectName: "Mouth_Roll_In_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_R_morphtarget1292
        objectName: "Mouth_Roll_In_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_L_morphtarget1291
        objectName: "Mouth_Roll_In_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_R_morphtarget1290
        objectName: "Mouth_Funnel_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_L_morphtarget1289
        objectName: "Mouth_Funnel_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_R_morphtarget1288
        objectName: "Mouth_Funnel_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_L_morphtarget1287
        objectName: "Mouth_Funnel_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_R_morphtarget1286
        objectName: "Mouth_Pucker_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_R_morphtarget1296
        objectName: "Mouth_Roll_Out_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_R_morphtarget1284
        objectName: "Mouth_Pucker_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_L_morphtarget1283
        objectName: "Mouth_Pucker_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_R_morphtarget1282
        objectName: "Mouth_Blow_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_L_morphtarget1281
        objectName: "Mouth_Blow_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_R_morphtarget1280
        objectName: "Mouth_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_L_morphtarget1279
        objectName: "Mouth_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_R_morphtarget1278
        objectName: "Mouth_Press_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_L_morphtarget1277
        objectName: "Mouth_Press_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_R_morphtarget1276
        objectName: "Mouth_Dimple_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_L_morphtarget1275
        objectName: "Mouth_Dimple_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_R_morphtarget1306
        objectName: "Mouth_Pull_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Lower_morphtarget1316
        objectName: "Mouth_Shrug_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Upper_morphtarget1315
        objectName: "Mouth_Shrug_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_R_morphtarget1314
        objectName: "Mouth_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_L_morphtarget1313
        objectName: "Mouth_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_R_morphtarget1312
        objectName: "Mouth_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_L_morphtarget1311
        objectName: "Mouth_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_R_morphtarget1310
        objectName: "Mouth_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_L_morphtarget1309
        objectName: "Mouth_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_morphtarget1308
        objectName: "Mouth_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_morphtarget1307
        objectName: "Mouth_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_R_morphtarget1274
        objectName: "Mouth_Stretch_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_L_morphtarget1305
        objectName: "Mouth_Pull_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_R_morphtarget1304
        objectName: "Mouth_Pull_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_L_morphtarget1303
        objectName: "Mouth_Pull_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_R_morphtarget1302
        objectName: "Mouth_Push_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_L_morphtarget1301
        objectName: "Mouth_Push_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_R_morphtarget1300
        objectName: "Mouth_Push_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_L_morphtarget1299
        objectName: "Mouth_Push_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_R_morphtarget1298
        objectName: "Mouth_Roll_Out_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_L_morphtarget1297
        objectName: "Mouth_Roll_Out_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_R_morphtarget1242
        objectName: "Ear_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_R_morphtarget1252
        objectName: "Nose_Crease_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_L_morphtarget1251
        objectName: "Nose_Crease_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_R_morphtarget1250
        objectName: "Nose_Nostril_Dilate_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_L_morphtarget1249
        objectName: "Nose_Nostril_Dilate_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_R_morphtarget1248
        objectName: "Nose_Nostril_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_L_morphtarget1247
        objectName: "Nose_Nostril_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_R_morphtarget1246
        objectName: "Nose_Sneer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_L_morphtarget1245
        objectName: "Nose_Sneer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_R_morphtarget1244
        objectName: "Ear_Out_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_L_morphtarget1243
        objectName: "Ear_Out_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_L_morphtarget1253
        objectName: "Nose_Nostril_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_L_morphtarget1241
        objectName: "Ear_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_R_morphtarget1240
        objectName: "Ear_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_L_morphtarget1239
        objectName: "Ear_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_R_morphtarget1238
        objectName: "Eyelash_Lower_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_R_morphtarget1237
        objectName: "Eyelash_Lower_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_L_morphtarget1236
        objectName: "Eyelash_Lower_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_L_morphtarget1235
        objectName: "Eyelash_Lower_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_R_morphtarget1234
        objectName: "Eyelash_Upper_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_R_morphtarget1233
        objectName: "Eyelash_Upper_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_L_morphtarget1232
        objectName: "Eyelash_Upper_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_L_morphtarget1263
        objectName: "Cheek_Suck_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_L_morphtarget1273
        objectName: "Mouth_Stretch_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_R_morphtarget1272
        objectName: "Mouth_Frown_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_L_morphtarget1271
        objectName: "Mouth_Frown_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_R_morphtarget1270
        objectName: "Mouth_Smile_Sharp_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_L_morphtarget1269
        objectName: "Mouth_Smile_Sharp_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_R_morphtarget1268
        objectName: "Mouth_Smile_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_L_morphtarget1267
        objectName: "Mouth_Smile_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_R_morphtarget1266
        objectName: "Cheek_Puff_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_L_morphtarget1265
        objectName: "Cheek_Puff_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_R_morphtarget1264
        objectName: "Cheek_Suck_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Upper_morphtarget1317
        objectName: "Mouth_Drop_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_R_morphtarget1262
        objectName: "Cheek_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_L_morphtarget1261
        objectName: "Cheek_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Down_morphtarget1260
        objectName: "Nose_Tip_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Up_morphtarget1259
        objectName: "Nose_Tip_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_R_morphtarget1258
        objectName: "Nose_Tip_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_L_morphtarget1257
        objectName: "Nose_Tip_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_R_morphtarget1256
        objectName: "Nose_Nostril_In_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_L_morphtarget1255
        objectName: "Nose_Nostril_In_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_R_morphtarget1254
        objectName: "Nose_Nostril_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: leftFrontForward_morphtarget
        objectName: "LeftFrontForward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: backRight_morphtarget
        objectName: "BackRight"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: backLeft_morphtarget
        objectName: "BackLeft"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: messy_morphtarget
        objectName: "Messy"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: backBack_morphtarget
        objectName: "BackBack"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontRightBack_morphtarget
        objectName: "FrontRightBack"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontRightOut_morphtarget
        objectName: "FrontRightOut"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontLeftBack_morphtarget
        objectName: "FrontLeftBack"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontLeftOut_morphtarget
        objectName: "FrontLeftOut"
        attributes: MorphTarget.Position
    }
    Skin {
        id: skin1378
        joints: [
            cc_Base_BoneRoot,
            cc_Base_Hip,
            cc_Base_Pelvis,
            cc_Base_L_Thigh,
            cc_Base_L_Calf,
            cc_Base_L_Foot,
            cc_Base_L_ToeBaseShareBone,
            cc_Base_L_ToeBase,
            cc_Base_L_PinkyToe1,
            cc_Base_L_RingToe1,
            cc_Base_L_MidToe1,
            cc_Base_L_IndexToe1,
            cc_Base_L_BigToe1,
            cc_Base_L_CalfTwist01,
            cc_Base_L_CalfTwist02,
            cc_Base_L_KneeShareBone,
            cc_Base_L_ThighTwist01,
            cc_Base_L_ThighTwist02,
            cc_Base_R_Thigh,
            cc_Base_R_Calf,
            cc_Base_R_KneeShareBone,
            cc_Base_R_Foot,
            cc_Base_R_ToeBase,
            cc_Base_R_BigToe1,
            cc_Base_R_PinkyToe1,
            cc_Base_R_RingToe1,
            cc_Base_R_IndexToe1,
            cc_Base_R_MidToe1,
            cc_Base_R_ToeBaseShareBone,
            cc_Base_R_CalfTwist01,
            cc_Base_R_CalfTwist02,
            cc_Base_R_ThighTwist01,
            cc_Base_R_ThighTwist02,
            cc_Base_Waist,
            cc_Base_Spine01,
            cc_Base_Spine02,
            cc_Base_NeckTwist01,
            cc_Base_NeckTwist02,
            cc_Base_Head,
            cc_Base_FacialBone,
            cc_Base_JawRoot,
            cc_Base_Tongue01,
            cc_Base_Tongue02,
            cc_Base_Tongue03,
            cc_Base_Teeth02,
            cc_Base_R_Eye,
            cc_Base_L_Eye,
            cc_Base_UpperJaw,
            cc_Base_Teeth01,
            cc_Base_L_Clavicle,
            cc_Base_L_Upperarm,
            cc_Base_L_Forearm,
            cc_Base_L_ForearmTwist01,
            cc_Base_L_ForearmTwist02,
            cc_Base_L_ElbowShareBone,
            cc_Base_L_Hand,
            cc_Base_L_Pinky1,
            cc_Base_L_Pinky2,
            cc_Base_L_Pinky3,
            cc_Base_L_Ring1,
            cc_Base_L_Ring2,
            cc_Base_L_Ring3,
            cc_Base_L_Mid1,
            cc_Base_L_Mid2,
            cc_Base_L_Mid3,
            cc_Base_L_Index1,
            cc_Base_L_Index2,
            cc_Base_L_Index3,
            cc_Base_L_Thumb1,
            cc_Base_L_Thumb2,
            cc_Base_L_Thumb3,
            cc_Base_L_UpperarmTwist01,
            cc_Base_L_UpperarmTwist02,
            cc_Base_L_RibsTwist,
            cc_Base_L_Breast,
            cc_Base_R_RibsTwist,
            cc_Base_R_Breast,
            cc_Base_R_Clavicle,
            cc_Base_R_Upperarm,
            cc_Base_R_Forearm,
            cc_Base_R_ElbowShareBone,
            cc_Base_R_ForearmTwist01,
            cc_Base_R_ForearmTwist02,
            cc_Base_R_Hand,
            cc_Base_R_Ring1,
            cc_Base_R_Ring2,
            cc_Base_R_Ring3,
            cc_Base_R_Mid1,
            cc_Base_R_Mid2,
            cc_Base_R_Mid3,
            cc_Base_R_Thumb1,
            cc_Base_R_Thumb2,
            cc_Base_R_Thumb3,
            cc_Base_R_Index1,
            cc_Base_R_Index2,
            cc_Base_R_Index3,
            cc_Base_R_Pinky1,
            cc_Base_R_Pinky2,
            cc_Base_R_Pinky3,
            cc_Base_R_UpperarmTwist01,
            cc_Base_R_UpperarmTwist02
        ]
        inverseBindPoses: [
            Qt.matrix4x4(100, 0, 0, 0, 0, 0, -100, 0, 0, 100, 0, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0, 0, 0, 0, 100, 0, -107.16, 0, 0, 100, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, -1.50763e-05, -1.50014e-06, 1.61558e-05, 1.50763e-05, 98.0392, 19.7056, -105.059, -1.50015e-06, -19.7056, 98.0392, 21.1165, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19943, -0.00154083, 7.15862, -2.19935, -99.9738, -0.625483, 104.87, -0.0155098, -0.625462, 99.9971, 1.10913, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.75838, -0.0421809, 7.4091, -1.7563, -99.9396, -2.99681, 56.7001, -0.0950633, -2.99579, 99.9542, 2.45743, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4254, 0.44619, 10.6957, 7.6864, 10.1705, -27.2384, 95.679, 2.96016, 3.3402, 96.2178, 27.0361, -5.07653, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8064, -4.35358, 4.44084, 8.50303, 4.05605, 8.5563, 99.5498, -11.5637, -4.714, 99.5381, -8.36324, -0.491555, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, -4.31662, 4.43681, 8.50295, 4.0552, 8.5548, 99.5499, -11.5636, -4.6768, 99.5398, -8.36343, -0.494889, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4797, -10.1827, 0.321515, 11.6262, 3.3234, -29.4543, 95.5052, -10.6293, -9.6305, 95.0197, 29.6391, -3.94976, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9388, -14.1291, 3.38768, 10.0395, 8.29467, -35.7843, 93.0083, -11.5382, -11.9292, 92.303, 36.5761, -5.2262, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, -11.9903, 6.4032, 8.33146, 8.90352, -21.6488, 97.2208, -13.2905, -10.271, 96.8894, 22.515, -4.04237, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, -12.9598, 6.3167, 6.8974, 9.26771, -23.6197, 96.7267, -13.2502, -11.0437, 96.3024, 24.5737, -4.53582, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, -4.20361, 6.53537, 4.82496, 6.44302, 2.29263, 99.765, -13.8397, -4.34362, 99.8853, -2.015, -1.1624, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.7602, -0.0420473, 7.40808, -1.75813, -99.9395, -2.99824, 56.7002, -0.0950096, -2.99723, 99.9541, 2.45824, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.76061, -0.0444752, 7.40838, -1.75846, -99.9395, -2.99852, 31.2084, -0.0974532, -2.99746, 99.9541, 2.45817, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, 1.85246, -3.25678, 7.32702, -1.75497, -99.9397, -2.99578, 56.7, -3.31055, -2.93671, 99.9012, 2.69389, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19789, -0.00126959, 7.16024, -2.19782, -99.9739, -0.620892, 104.87, -0.0151281, -0.620878, 99.9972, 1.10429, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.1979, -0.000876542, 7.16006, -2.19783, -99.9739, -0.620904, 80.8223, -0.0147355, -0.620899, 99.9972, 1.10544, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, -2.19924, 0.00153699, -7.16575, 2.1992, -99.9739, -0.625714, 104.872, 0.0151791, -0.625438, 99.9985, 1.10604, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75776, 0.0422092, -7.41643, 1.75572, -99.9397, -2.99703, 56.704, 0.0947457, -2.99573, 99.9556, 2.45444, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, -1.85182, 3.25683, -7.33445, 1.75438, -99.9397, -2.99601, 56.704, 3.31021, -2.93666, 99.9025, 2.69113, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4253, -0.445641, -10.6957, -7.69344, -10.1708, -27.2377, 95.6805, 2.9584, -3.33968, 96.218, 27.0361, -5.08513, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, 4.31673, -4.43678, -8.51101, -4.05543, 8.55508, 99.5513, -11.5765, 4.67691, 99.5398, -8.36358, -0.498814, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, 4.20418, -6.53536, -4.83289, -6.44323, 2.29301, 99.7664, -13.8527, 4.34419, 99.8853, -2.01513, -1.16698, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4796, 10.1835, -0.321472, -11.6342, -3.32385, -29.4536, 95.5067, -10.6366, 9.63116, 95.0199, 29.639, -3.95668, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9387, 14.1298, -3.38765, -10.0477, -8.29509, -35.7835, 93.0098, -11.5462, 11.9297, 92.3033, 36.576, -5.23363, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, 12.9605, -6.3167, -6.90615, -9.26806, -23.619, 96.7282, -13.2604, 11.0444, 96.3025, 24.5736, -4.5426, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, 11.9906, -6.40327, -8.33963, -8.90384, -21.6481, 97.2223, -13.3019, 10.2712, 96.8896, 22.5149, -4.04937, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8065, 4.35429, -4.43993, -8.5112, -4.05542, 8.5551, 99.5513, -11.5765, 4.71457, 99.5382, -8.36192, -0.495601, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75958, 0.0420813, -7.41542, 1.75754, -99.9396, -2.99846, 56.7041, 0.0946975, -2.99715, 99.9555, 2.45525, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75998, 0.0445132, -7.41571, 1.75787, -99.9396, -2.99877, 31.2144, 0.0971455, -2.99742, 99.9555, 2.45518, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.19769, 0.00128364, -7.16738, 2.19765, -99.9739, -0.621137, 104.872, 0.0148155, -0.620868, 99.9986, 1.10122, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.1977, 0.000890074, -7.16717, 2.19766, -99.9739, -0.621137, 80.8252, 0.0144221, -0.620877, 99.9986, 1.10237, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0595393, 0.0154999, -0.0669482, -0.0615188, 96.446, 26.423, -110.219, 0.000783055, -26.423, 96.446, 28.2733, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.00372025, 0.000168532, 0.00785771, 0.00372275, 99.9827, -1.86208, -117.476, -9.92306e-05, 1.86208, 99.9827, -5.07925, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0111038, 0.0023672, 0.0174147, 0.0113498, 97.2489, -23.2946, -126.012, 0.000284515, 23.2946, 97.249, -32.914, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0547365, -0.0101122, 0.0848241, 0.0556495, 98.7096, 16.0127, -152.92, 0.00121684, -16.0127, 98.7096, 28.2536, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0401262, -0.0105083, 0.0615821, 0.0414671, 96.0918, 27.6832, -151.999, -0.00101063, -27.6832, 96.0918, 46.7363, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.000265608, 6.35935e-05, -0.00285968, 0.000265636, 100, -0.0357807, -162.25, -6.34991e-05, 0.0357837, 100, 1.83509, 0, 0, 0, 1),
            Qt.matrix4x4(-0.000669168, 100, -0.0360327, -162.25, -6.24571e-05, 0.0360356, 100, 1.83469, 100, 0.000669196, 6.38568e-05, -0.00437637, 0, 0, 0, 1),
            Qt.matrix4x4(-0.00245299, 0.0400948, 100, -0.767438, -0.0145806, -100, 0.0400834, 163.645, 100, -0.0145796, 0.00246047, 0.0205602, 0, 0, 0, 1),
            Qt.matrix4x4(0.112315, -17.6141, 98.4365, 25.0468, -0.0182466, -98.4365, -17.6141, 160.852, 99.9999, 0.001822, -0.113771, -0.00270895, 0, 0, 0, 1),
            Qt.matrix4x4(0.120985, -36.4206, 93.1318, 54.7053, -0.0198629, -93.1319, -36.4206, 153.137, 99.9999, 0.0255649, -0.119909, -0.0410066, 0, 0, 0, 1),
            Qt.matrix4x4(0.121003, -36.42, 93.132, 52.9936, -0.0202164, -93.1321, -36.42, 153.137, 99.9999, 0.0252415, -0.120054, -0.0404762, 0, 0, 0, 1),
            Qt.matrix4x4(0.0169932, 0.0411495, 100, -4.08427, -0.0173491, 100, -0.0411355, -162.538, -100, -0.0173421, 0.0169987, 0.0252892, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0131955, -0.0139593, 3.48603, -0.0139637, -0.0207999, -100, 5.17964, 0.0131926, 100, -0.0207988, -168.877, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0126715, 0.0153175, -3.49781, 0.0153222, -0.0500856, -100, 5.23196, -0.0126638, 100, -0.0500845, -168.872, 0, 0, 0, 1),
            Qt.matrix4x4(0.00847962, 0.034713, 100, -4.58337, -0.000401467, -100, 0.0347213, 164.58, 100, -0.000404406, -0.00847784, -0.00446657, 0, 0, 0, 1),
            Qt.matrix4x4(0.00138361, 0.0389695, 100, -4.95796, 0.00525116, 100, -0.0389778, -164.247, -100, 0.00525169, 0.00137992, 0.00236788, 0, 0, 0, 1),
            Qt.matrix4x4(-1.88568, -99.8883, 4.33249, 149.837, 97.3862, -2.81603, -22.5387, -0.808774, 22.6356, 3.79424, 97.3305, -4.74137, 0, 0, 0, 1),
            Qt.matrix4x4(-49.807, -86.6412, 3.54302, 137.155, 86.7134, -49.7753, 1.79, 61.5499, 0.212671, 3.96382, 99.9212, -1.52919, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.5239, 136.91, 86.3604, -50.3177, 3.16266, 35.73, -0.95603, 4.63749, 99.8878, -2.00221, 0, 0, 0, 1),
            Qt.matrix4x4(-50.409, -86.2932, 3.52318, 136.91, 86.3598, -50.3188, 3.16266, 35.7316, -0.956336, 4.63688, 99.8879, -2.00127, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.52317, 136.91, 86.3604, -50.3177, 3.16351, 23.7177, -0.957131, 4.63729, 99.8878, -2.00141, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4649, -86.264, 3.43616, 136.888, 86.3275, -50.3797, 3.07288, 35.8233, -0.91966, 4.51709, 99.8937, -1.85184, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7679, -87.7827, 3.52396, 137.204, 87.3005, -47.8784, -9.28884, 7.72614, 9.84121, -1.36064, 99.5053, -0.92711, 0, 0, 0, 1),
            Qt.matrix4x4(-49.9004, -86.5883, 3.52285, 136.803, 86.6599, -49.8627, 1.94246, 2.44348, 0.0746406, 4.0222, 99.9191, 0.988494, 0, 0, 0, 1),
            Qt.matrix4x4(-52.663, -84.9267, 3.75148, 136.743, 85.0063, -52.648, 1.4555, 4.14878, 0.738971, 3.9555, 99.919, 0.612436, 0, 0, 0, 1),
            Qt.matrix4x4(-44.5186, -89.4714, 3.60109, 136.398, 89.4575, -44.6162, -2.59674, -10.0752, 3.93001, 2.06542, 99.9014, 0.6083, 0, 0, 0, 1),
            Qt.matrix4x4(-49.6224, -86.7491, 3.49327, 137.198, 86.8192, -49.5725, 2.23479, 1.7522, -0.206964, 4.14179, 99.914, -0.821401, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6708, -83.6615, 3.44216, 137.086, 83.7279, -54.6641, 1.21753, 5.93462, 0.863019, 3.54768, 99.9333, -0.868637, 0, 0, 0, 1),
            Qt.matrix4x4(-47.9847, -87.6646, 3.52107, 136.953, 87.7066, -48.0329, -0.627888, -6.90922, 2.24171, 2.78693, 99.936, -0.96638, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5574, -86.1786, 4.14779, 137.418, 86.2745, -50.4515, 3.36886, 2.85757, -0.810612, 5.2817, 99.8571, -3.58848, 0, 0, 0, 1),
            Qt.matrix4x4(-51.6067, -85.587, 3.40699, 137.448, 85.6431, -51.4929, 3.70805, 0.185814, -1.41925, 4.83145, 99.8731, -2.62696, 0, 0, 0, 1),
            Qt.matrix4x4(-48.7135, -87.2623, 3.50497, 137.288, 87.3183, -48.5935, 3.76532, -7.09703, -1.58252, 4.89471, 99.8676, -2.58154, 0, 0, 0, 1),
            Qt.matrix4x4(-50.7218, -86.0765, 4.25742, 137.125, 86.1791, -50.6972, 1.71972, 3.07359, 0.678116, 4.54128, 99.8945, -5.83135, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4655, -85.0736, 3.13906, 137.165, 85.1159, -52.3497, 3.84519, 2.04567, -1.62795, 4.68924, 99.8767, -4.38814, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0827, -87.615, 3.41648, 136.971, 87.574, -47.7943, 6.81865, -7.42734, -4.34128, 6.27054, 99.7087, -4.27729, 0, 0, 0, 1),
            Qt.matrix4x4(-64.961, -73.2123, 20.4945, 129.222, 59.5939, -32.2961, 73.5223, 4.4705, -47.2084, 59.9743, 64.61, -44.6085, 0, 0, 0, 1),
            Qt.matrix4x4(-57.9161, -77.0926, 26.5039, 129.246, 77.6561, -42.2805, 46.7107, 0.294844, -24.8045, 47.6349, 84.3543, -44.5523, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7869, -80.2894, 29.525, 128.919, 81.9393, -36.6397, 44.085, -11.843, -24.5778, 47.0228, 84.7632, -43.9857, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8061, -86.6307, 3.80604, 137.151, 86.7135, -49.775, 1.7906, 61.5495, 0.343252, 4.19218, 99.9115, -1.8906, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8068, -86.6414, 3.54283, 137.155, 86.7135, -49.775, 1.79084, 48.1756, 0.211837, 3.96408, 99.9212, -1.52922, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0121952, -0.0016524, 10.1203, -0.00110477, 4.47696, 99.8997, -19.2259, 0.0122569, 99.8997, -4.47694, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, 10.1202, -0.00114441, 4.47696, 99.8997, -21.2259, 0.0122638, 99.8997, -4.47693, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122068, -0.00170066, -10.1238, -0.00115246, 4.47694, 99.8997, -19.2055, 0.0122707, 99.8997, -4.47693, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, -10.1238, -0.00114441, 4.47695, 99.8997, -21.2055, 0.0122638, 99.8997, -4.47694, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-1.85887, 99.8888, -4.33163, -149.836, -97.3861, -2.78984, -22.5425, -0.846488, -22.6383, 3.79937, 97.3297, -4.74888, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7835, 86.6547, -3.54387, -137.187, -86.7269, -49.7519, 1.78613, 61.4895, -0.21537, 3.96269, 99.9212, -1.52094, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3848, 86.3073, -3.52505, -136.942, -86.374, -50.2947, 3.1588, 35.7086, 0.953363, 4.63628, 99.8879, -1.99405, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4418, 86.2775, -3.43736, -136.92, -86.3411, -50.3567, 3.06902, 35.8021, 0.91693, 4.51592, 99.8938, -1.84374, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3858, 86.3067, -3.52427, -136.942, -86.3734, -50.2957, 3.1588, 35.7102, 0.953702, 4.63562, 99.8879, -1.99303, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3847, 86.3073, -3.52431, -136.942, -86.374, -50.2946, 3.15966, 23.7108, 0.954484, 4.63607, 99.8879, -1.99325, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7442, 87.7956, -3.52487, -137.236, -87.313, -47.8549, -9.29271, 7.73164, -9.8454, -1.35906, 99.5049, -0.917997, 0, 0, 0, 1),
            Qt.matrix4x4(-49.5991, 86.7624, -3.49434, -137.229, -86.8325, -49.5493, 2.23093, 1.75948, 0.204188, 4.14074, 99.914, -0.813094, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6474, 83.6768, -3.44239, -137.118, -83.7431, -54.6408, 1.21375, 5.94218, -0.865323, 3.54604, 99.9334, -0.858772, 0, 0, 0, 1),
            Qt.matrix4x4(-47.961, 87.6774, -3.52205, -136.985, -87.7194, -48.0094, -0.63177, -6.9061, -2.24483, 2.78652, 99.936, -0.958057, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5341, 86.1921, -4.14882, -137.449, -86.2882, -50.4284, 3.365, 2.86407, 0.808178, 5.28042, 99.8572, -3.57899, 0, 0, 0, 1),
            Qt.matrix4x4(-51.5833, 85.6011, -3.40781, -137.478, -85.6572, -51.4697, 3.70416, 0.191616, 1.41681, 4.82976, 99.8732, -2.61691, 0, 0, 0, 1),
            Qt.matrix4x4(-48.6899, 87.2755, -3.50582, -137.319, -87.3316, -48.5701, 3.76144, -7.092, 1.58004, 4.89313, 99.8677, -2.5717, 0, 0, 0, 1),
            Qt.matrix4x4(-64.9407, 73.2298, -20.4965, -129.252, -59.6054, -32.281, 73.5196, 4.48364, 47.2218, 59.9611, 64.6124, -44.6136, 0, 0, 0, 1),
            Qt.matrix4x4(-57.8947, 77.1081, -26.5056, -129.278, -77.6691, -42.2604, 46.7073, 0.307031, 24.8138, 47.6277, 84.3557, -44.5532, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7624, 80.3053, -29.5247, -128.953, -81.9515, -36.6168, 44.0813, -11.8357, 24.5886, 47.0134, 84.7652, -43.9827, 0, 0, 0, 1),
            Qt.matrix4x4(-50.6986, 86.0901, -4.25856, -137.155, -86.1927, -50.6742, 1.71586, 3.08145, -0.680797, 4.54049, 99.8945, -5.81861, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4425, 85.0878, -3.14012, -137.195, -85.1302, -52.3269, 3.84136, 2.05416, 1.6254, 4.6877, 99.8769, -4.37503, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0592, 87.6278, -3.41758, -137.002, -87.587, -47.771, 6.81477, -7.42022, 4.33903, 6.26848, 99.709, -4.26478, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8771, 86.6017, -3.52394, -136.835, -86.6733, -49.8395, 1.93857, 2.44804, -0.0774823, 4.02122, 99.9191, 0.995909, 0, 0, 0, 1),
            Qt.matrix4x4(-52.6416, 84.9398, -3.75452, -136.775, -85.0194, -52.6268, 1.45174, 4.15666, -0.742781, 3.95629, 99.919, 0.617262, 0, 0, 0, 1),
            Qt.matrix4x4(-44.4949, 89.4831, -3.60251, -136.43, -89.4691, -44.5927, -2.60061, -10.0723, -3.93356, 2.06599, 99.9013, 0.615095, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7826, 86.644, -3.80768, -137.182, -86.727, -49.7518, 1.78673, 61.4894, -0.346297, 4.19176, 99.9115, -1.88352, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7834, 86.6548, -3.54388, -137.187, -86.727, -49.7518, 1.78696, 48.1346, -0.214659, 3.96311, 99.9212, -1.52125, 0, 0, 0, 1)
        ]
    }
    MorphTarget {
        id: rightFrontForward_morphtarget1388
        objectName: "RightFrontForward"
        attributes: MorphTarget.Position
    }
    PrincipledMaterial {
        id: front_Transparency_material
        objectName: "Front_Transparency"
        baseColorMap: _30_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Blend
    }
    PrincipledMaterial {
        id: scalp_Transparency_material
        objectName: "scalp_Transparency"
        baseColor: "#ff000000"
        baseColorMap: _29_texture
        roughness: 0.4000000059604645
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Blend
    }
    PrincipledMaterial {
        id: hair_Transparency_material
        objectName: "hair_Transparency"
        baseColorMap: _27_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Blend
    }
    MorphTarget {
        id: head_Backward_morphtarget1366
        objectName: "Head_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Forward_morphtarget1365
        objectName: "Head_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_R_morphtarget1364
        objectName: "Head_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_L_morphtarget1363
        objectName: "Head_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_R_morphtarget1362
        objectName: "Head_Tilt_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_L_morphtarget1361
        objectName: "Head_Tilt_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_R_morphtarget1360
        objectName: "Head_Turn_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: rightFrontForward_morphtarget1398
        objectName: "RightFrontForward"
        attributes: MorphTarget.Position
    }
    PrincipledMaterial {
        id: std_Skin_Head_material
        objectName: "Std_Skin_Head"
        baseColorMap: _0_texture
        roughness: 0.5527864098548889
        normalMap: _1_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    MorphTarget {
        id: leftFrontForward_morphtarget1407
        objectName: "LeftFrontForward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: backRight_morphtarget1406
        objectName: "BackRight"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: backLeft_morphtarget1405
        objectName: "BackLeft"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: messy_morphtarget1404
        objectName: "Messy"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: backBack_morphtarget1403
        objectName: "BackBack"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontRightBack_morphtarget1402
        objectName: "FrontRightBack"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontRightOut_morphtarget1401
        objectName: "FrontRightOut"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontLeftBack_morphtarget1400
        objectName: "FrontLeftBack"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontLeftOut_morphtarget1399
        objectName: "FrontLeftOut"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_L_morphtarget1359
        objectName: "Head_Turn_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: leftFrontForward_morphtarget1397
        objectName: "LeftFrontForward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: backRight_morphtarget1396
        objectName: "BackRight"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: backLeft_morphtarget1395
        objectName: "BackLeft"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: messy_morphtarget1394
        objectName: "Messy"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: backBack_morphtarget1393
        objectName: "BackBack"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontRightBack_morphtarget1392
        objectName: "FrontRightBack"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontRightOut_morphtarget1391
        objectName: "FrontRightOut"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontLeftBack_morphtarget1390
        objectName: "FrontLeftBack"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: frontLeftOut_morphtarget1389
        objectName: "FrontLeftOut"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_In_morphtarget1327
        objectName: "Tongue_In"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_R_morphtarget1337
        objectName: "Tongue_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_L_morphtarget1336
        objectName: "Tongue_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Roll_morphtarget1335
        objectName: "Tongue_Roll"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Wide_morphtarget1334
        objectName: "Tongue_Wide"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Narrow_morphtarget1333
        objectName: "Tongue_Narrow"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_Down_morphtarget1332
        objectName: "Tongue_Tip_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_Up_morphtarget1331
        objectName: "Tongue_Tip_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Mid_Up_morphtarget1330
        objectName: "Tongue_Mid_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Down_morphtarget1329
        objectName: "Tongue_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Up_morphtarget1328
        objectName: "Tongue_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_L_morphtarget1338
        objectName: "Tongue_Tip_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Out_morphtarget1326
        objectName: "Tongue_Out"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Contract_morphtarget1325
        objectName: "Mouth_Contract"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Close_morphtarget1324
        objectName: "Mouth_Close"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Chin_Up_morphtarget1323
        objectName: "Mouth_Chin_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_R_morphtarget1322
        objectName: "Mouth_Down_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_L_morphtarget1321
        objectName: "Mouth_Down_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_R_morphtarget1320
        objectName: "Mouth_Up_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_L_morphtarget1319
        objectName: "Mouth_Up_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Lower_morphtarget1318
        objectName: "Mouth_Drop_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Backward_morphtarget1348
        objectName: "Jaw_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Down_morphtarget1358
        objectName: "Head_Turn_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Up_morphtarget1357
        objectName: "Head_Turn_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_R_morphtarget1356
        objectName: "Neck_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_L_morphtarget1355
        objectName: "Neck_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Down_morphtarget1354
        objectName: "Neck_Swallow_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Up_morphtarget1353
        objectName: "Neck_Swallow_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Down_morphtarget1352
        objectName: "Jaw_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Up_morphtarget1351
        objectName: "Jaw_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_R_morphtarget1350
        objectName: "Jaw_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_L_morphtarget1349
        objectName: "Jaw_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_L_morphtarget1231
        objectName: "Eyelash_Upper_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Forward_morphtarget1347
        objectName: "Jaw_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Open_morphtarget1346
        objectName: "Jaw_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Enlarge_morphtarget1345
        objectName: "Tongue_Enlarge"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Extend_morphtarget1344
        objectName: "Tongue_Extend"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_R_morphtarget1343
        objectName: "Tongue_Bulge_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_L_morphtarget1342
        objectName: "Tongue_Bulge_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Twist_R_morphtarget1341
        objectName: "Tongue_Twist_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Twist_L_morphtarget1340
        objectName: "Tongue_Twist_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_R_morphtarget1339
        objectName: "Tongue_Tip_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_R_morphtarget1114
        objectName: "Mouth_Funnel_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_R_morphtarget1124
        objectName: "Mouth_Push_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_L_morphtarget1123
        objectName: "Mouth_Push_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_R_morphtarget1122
        objectName: "Mouth_Roll_Out_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_L_morphtarget1121
        objectName: "Mouth_Roll_Out_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_R_morphtarget1120
        objectName: "Mouth_Roll_Out_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_L_morphtarget1119
        objectName: "Mouth_Roll_Out_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_R_morphtarget1118
        objectName: "Mouth_Roll_In_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_L_morphtarget1117
        objectName: "Mouth_Roll_In_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_R_morphtarget1116
        objectName: "Mouth_Roll_In_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_L_morphtarget1115
        objectName: "Mouth_Roll_In_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_L_morphtarget1125
        objectName: "Mouth_Push_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_L_morphtarget1113
        objectName: "Mouth_Funnel_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_R_morphtarget1112
        objectName: "Mouth_Funnel_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_L_morphtarget1111
        objectName: "Mouth_Funnel_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_R_morphtarget1110
        objectName: "Mouth_Pucker_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_L_morphtarget1109
        objectName: "Mouth_Pucker_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_R_morphtarget1108
        objectName: "Mouth_Pucker_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_L_morphtarget1107
        objectName: "Mouth_Pucker_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_R_morphtarget1106
        objectName: "Mouth_Blow_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_L_morphtarget1105
        objectName: "Mouth_Blow_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_R_morphtarget1104
        objectName: "Mouth_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_L_morphtarget1135
        objectName: "Mouth_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_L_morphtarget1145
        objectName: "Mouth_Down_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_R_morphtarget1144
        objectName: "Mouth_Up_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_L_morphtarget1143
        objectName: "Mouth_Up_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Lower_morphtarget1142
        objectName: "Mouth_Drop_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Upper_morphtarget1141
        objectName: "Mouth_Drop_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Lower_morphtarget1140
        objectName: "Mouth_Shrug_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Upper_morphtarget1139
        objectName: "Mouth_Shrug_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_R_morphtarget1138
        objectName: "Mouth_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_L_morphtarget1137
        objectName: "Mouth_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_R_morphtarget1136
        objectName: "Mouth_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_L_morphtarget1103
        objectName: "Mouth_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_R_morphtarget1134
        objectName: "Mouth_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_L_morphtarget1133
        objectName: "Mouth_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_morphtarget1132
        objectName: "Mouth_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_morphtarget1131
        objectName: "Mouth_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_R_morphtarget1130
        objectName: "Mouth_Pull_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_L_morphtarget1129
        objectName: "Mouth_Pull_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_R_morphtarget1128
        objectName: "Mouth_Pull_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_L_morphtarget1127
        objectName: "Mouth_Pull_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_R_morphtarget1126
        objectName: "Mouth_Push_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_L_morphtarget1071
        objectName: "Nose_Nostril_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_L_morphtarget1081
        objectName: "Nose_Tip_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_R_morphtarget1080
        objectName: "Nose_Nostril_In_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_L_morphtarget1079
        objectName: "Nose_Nostril_In_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_R_morphtarget1078
        objectName: "Nose_Nostril_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_L_morphtarget1077
        objectName: "Nose_Nostril_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_R_morphtarget1076
        objectName: "Nose_Crease_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_L_morphtarget1075
        objectName: "Nose_Crease_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_R_morphtarget1074
        objectName: "Nose_Nostril_Dilate_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_L_morphtarget1073
        objectName: "Nose_Nostril_Dilate_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_R_morphtarget1072
        objectName: "Nose_Nostril_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_R_morphtarget1082
        objectName: "Nose_Tip_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_R_morphtarget1070
        objectName: "Nose_Sneer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_L_morphtarget1069
        objectName: "Nose_Sneer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_R_morphtarget1068
        objectName: "Ear_Out_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_L_morphtarget1067
        objectName: "Ear_Out_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_R_morphtarget1066
        objectName: "Ear_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_L_morphtarget1065
        objectName: "Ear_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_R_morphtarget1064
        objectName: "Ear_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_L_morphtarget1063
        objectName: "Ear_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_R_morphtarget1062
        objectName: "Eyelash_Lower_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_R_morphtarget1092
        objectName: "Mouth_Smile_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_R_morphtarget1102
        objectName: "Mouth_Press_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_L_morphtarget1101
        objectName: "Mouth_Press_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_R_morphtarget1100
        objectName: "Mouth_Dimple_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_L_morphtarget1099
        objectName: "Mouth_Dimple_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_R_morphtarget1098
        objectName: "Mouth_Stretch_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_L_morphtarget1097
        objectName: "Mouth_Stretch_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_R_morphtarget1096
        objectName: "Mouth_Frown_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_L_morphtarget1095
        objectName: "Mouth_Frown_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_R_morphtarget1094
        objectName: "Mouth_Smile_Sharp_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_L_morphtarget1093
        objectName: "Mouth_Smile_Sharp_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_R_morphtarget1146
        objectName: "Mouth_Down_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_L_morphtarget1091
        objectName: "Mouth_Smile_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_R_morphtarget1090
        objectName: "Cheek_Puff_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_L_morphtarget1089
        objectName: "Cheek_Puff_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_R_morphtarget1088
        objectName: "Cheek_Suck_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_L_morphtarget1087
        objectName: "Cheek_Suck_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_R_morphtarget1086
        objectName: "Cheek_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_L_morphtarget1085
        objectName: "Cheek_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Down_morphtarget1084
        objectName: "Nose_Tip_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Up_morphtarget1083
        objectName: "Nose_Tip_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Lip_Open_morphtarget1199
        objectName: "V_Lip_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_L_morphtarget1209
        objectName: "Brow_Raise_Outer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_R_morphtarget1208
        objectName: "Brow_Raise_Inner_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_L_morphtarget1207
        objectName: "Brow_Raise_Inner_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Curl_D_morphtarget1206
        objectName: "V_Tongue_Curl_D"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Curl_U_morphtarget1205
        objectName: "V_Tongue_Curl_U"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Lower_morphtarget1204
        objectName: "V_Tongue_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Narrow_morphtarget1203
        objectName: "V_Tongue_Narrow"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Out_morphtarget1202
        objectName: "V_Tongue_Out"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_Raise_morphtarget1201
        objectName: "V_Tongue_Raise"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tongue_up_morphtarget1200
        objectName: "V_Tongue_up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_R_morphtarget1210
        objectName: "Brow_Raise_Outer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Affricate_morphtarget1198
        objectName: "V_Affricate"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Wide_morphtarget1197
        objectName: "V_Wide"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_morphtarget1196
        objectName: "V_Tight"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_O_morphtarget1195
        objectName: "V_Tight_O"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Dental_Lip_morphtarget1194
        objectName: "V_Dental_Lip"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Explosive_morphtarget1193
        objectName: "V_Explosive"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Open_morphtarget1192
        objectName: "V_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_None_morphtarget1191
        objectName: "V_None"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Backward_morphtarget1190
        objectName: "Head_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Forward_morphtarget1189
        objectName: "Head_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_R_morphtarget1220
        objectName: "Eye_Wide_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Pupil_Contract_morphtarget1230
        objectName: "Eye_Pupil_Contract"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Pupil_Dilate_morphtarget1229
        objectName: "Eye_Pupil_Dilate"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Down_morphtarget1228
        objectName: "Eye_R_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Down_morphtarget1227
        objectName: "Eye_L_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Up_morphtarget1226
        objectName: "Eye_R_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Up_morphtarget1225
        objectName: "Eye_L_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_R_morphtarget1224
        objectName: "Eye_R_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_R_morphtarget1223
        objectName: "Eye_L_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_L_morphtarget1222
        objectName: "Eye_R_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_L_morphtarget1221
        objectName: "Eye_L_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_R_morphtarget1188
        objectName: "Head_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_L_morphtarget1219
        objectName: "Eye_Wide_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_R_morphtarget1218
        objectName: "Eye_Squint_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_L_morphtarget1217
        objectName: "Eye_Squint_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_R_morphtarget1216
        objectName: "Eye_Blink_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_L_morphtarget1215
        objectName: "Eye_Blink_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_R_morphtarget1214
        objectName: "Brow_Compress_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_L_morphtarget1213
        objectName: "Brow_Compress_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_R_morphtarget1212
        objectName: "Brow_Drop_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_L_morphtarget1211
        objectName: "Brow_Drop_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_Down_morphtarget1156
        objectName: "Tongue_Tip_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_L_morphtarget1166
        objectName: "Tongue_Bulge_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Twist_R_morphtarget1165
        objectName: "Tongue_Twist_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Twist_L_morphtarget1164
        objectName: "Tongue_Twist_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_R_morphtarget1163
        objectName: "Tongue_Tip_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_L_morphtarget1162
        objectName: "Tongue_Tip_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_R_morphtarget1161
        objectName: "Tongue_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_L_morphtarget1160
        objectName: "Tongue_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Roll_morphtarget1159
        objectName: "Tongue_Roll"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Wide_morphtarget1158
        objectName: "Tongue_Wide"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Narrow_morphtarget1157
        objectName: "Tongue_Narrow"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_R_morphtarget1167
        objectName: "Tongue_Bulge_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Tip_Up_morphtarget1155
        objectName: "Tongue_Tip_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Mid_Up_morphtarget1154
        objectName: "Tongue_Mid_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Down_morphtarget1153
        objectName: "Tongue_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Up_morphtarget1152
        objectName: "Tongue_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_In_morphtarget1151
        objectName: "Tongue_In"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Out_morphtarget1150
        objectName: "Tongue_Out"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Contract_morphtarget1149
        objectName: "Mouth_Contract"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Close_morphtarget1148
        objectName: "Mouth_Close"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Chin_Up_morphtarget1147
        objectName: "Mouth_Chin_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Up_morphtarget1177
        objectName: "Neck_Swallow_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_L_morphtarget1187
        objectName: "Head_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_R_morphtarget1186
        objectName: "Head_Tilt_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_L_morphtarget1185
        objectName: "Head_Tilt_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_R_morphtarget1184
        objectName: "Head_Turn_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_L_morphtarget1183
        objectName: "Head_Turn_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Down_morphtarget1182
        objectName: "Head_Turn_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Up_morphtarget1181
        objectName: "Head_Turn_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_R_morphtarget1180
        objectName: "Neck_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_L_morphtarget1179
        objectName: "Neck_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Down_morphtarget1178
        objectName: "Neck_Swallow_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_R_morphtarget1061
        objectName: "Eyelash_Lower_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Down_morphtarget1176
        objectName: "Jaw_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Up_morphtarget1175
        objectName: "Jaw_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_R_morphtarget1174
        objectName: "Jaw_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_L_morphtarget1173
        objectName: "Jaw_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Backward_morphtarget1172
        objectName: "Jaw_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Forward_morphtarget1171
        objectName: "Jaw_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Open_morphtarget1170
        objectName: "Jaw_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Enlarge_morphtarget1169
        objectName: "Tongue_Enlarge"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Extend_morphtarget1168
        objectName: "Tongue_Extend"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_L_morphtarget253
        objectName: "Mouth_Frown_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_L_morphtarget263
        objectName: "Mouth_Blow_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_R_morphtarget262
        objectName: "Mouth_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_L_morphtarget261
        objectName: "Mouth_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_R_morphtarget260
        objectName: "Mouth_Press_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_L_morphtarget259
        objectName: "Mouth_Press_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_R_morphtarget258
        objectName: "Mouth_Dimple_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_L_morphtarget257
        objectName: "Mouth_Dimple_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_R_morphtarget256
        objectName: "Mouth_Stretch_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_L_morphtarget255
        objectName: "Mouth_Stretch_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_R_morphtarget254
        objectName: "Mouth_Frown_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_R_morphtarget264
        objectName: "Mouth_Blow_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_R_morphtarget252
        objectName: "Mouth_Smile_Sharp_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_L_morphtarget251
        objectName: "Mouth_Smile_Sharp_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_R_morphtarget250
        objectName: "Mouth_Smile_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_L_morphtarget249
        objectName: "Mouth_Smile_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_R_morphtarget248
        objectName: "Cheek_Puff_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_L_morphtarget247
        objectName: "Cheek_Puff_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_R_morphtarget246
        objectName: "Cheek_Suck_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_L_morphtarget245
        objectName: "Cheek_Suck_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_R_morphtarget244
        objectName: "Cheek_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_L_morphtarget243
        objectName: "Cheek_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_R_morphtarget274
        objectName: "Mouth_Roll_In_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_R_morphtarget284
        objectName: "Mouth_Push_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_L_morphtarget283
        objectName: "Mouth_Push_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_R_morphtarget282
        objectName: "Mouth_Push_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_L_morphtarget281
        objectName: "Mouth_Push_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_R_morphtarget280
        objectName: "Mouth_Roll_Out_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_L_morphtarget279
        objectName: "Mouth_Roll_Out_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_R_morphtarget278
        objectName: "Mouth_Roll_Out_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_L_morphtarget277
        objectName: "Mouth_Roll_Out_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_R_morphtarget276
        objectName: "Mouth_Roll_In_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_L_morphtarget275
        objectName: "Mouth_Roll_In_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Down_morphtarget242
        objectName: "Nose_Tip_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_L_morphtarget273
        objectName: "Mouth_Roll_In_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_R_morphtarget272
        objectName: "Mouth_Funnel_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_L_morphtarget271
        objectName: "Mouth_Funnel_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_R_morphtarget270
        objectName: "Mouth_Funnel_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_L_morphtarget269
        objectName: "Mouth_Funnel_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_R_morphtarget268
        objectName: "Mouth_Pucker_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_L_morphtarget267
        objectName: "Mouth_Pucker_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_R_morphtarget266
        objectName: "Mouth_Pucker_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_L_morphtarget265
        objectName: "Mouth_Pucker_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Up_morphtarget210
        objectName: "Eye_R_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_R_morphtarget220
        objectName: "Eyelash_Lower_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_R_morphtarget219
        objectName: "Eyelash_Lower_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_L_morphtarget218
        objectName: "Eyelash_Lower_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_L_morphtarget217
        objectName: "Eyelash_Lower_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_R_morphtarget216
        objectName: "Eyelash_Upper_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_R_morphtarget215
        objectName: "Eyelash_Upper_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_L_morphtarget214
        objectName: "Eyelash_Upper_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_L_morphtarget213
        objectName: "Eyelash_Upper_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Down_morphtarget212
        objectName: "Eye_R_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Down_morphtarget211
        objectName: "Eye_L_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_L_morphtarget221
        objectName: "Ear_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Up_morphtarget209
        objectName: "Eye_L_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_R_morphtarget208
        objectName: "Eye_R_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_R_morphtarget207
        objectName: "Eye_L_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_L_morphtarget206
        objectName: "Eye_R_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_L_morphtarget205
        objectName: "Eye_L_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_R_morphtarget204
        objectName: "Eye_Wide_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_L_morphtarget203
        objectName: "Eye_Wide_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_R_morphtarget202
        objectName: "Eye_Squint_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_L_morphtarget201
        objectName: "Eye_Squint_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_R_morphtarget200
        objectName: "Eye_Blink_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_L_morphtarget231
        objectName: "Nose_Nostril_Dilate_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Up_morphtarget241
        objectName: "Nose_Tip_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_R_morphtarget240
        objectName: "Nose_Tip_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_L_morphtarget239
        objectName: "Nose_Tip_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_R_morphtarget238
        objectName: "Nose_Nostril_In_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_L_morphtarget237
        objectName: "Nose_Nostril_In_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_R_morphtarget236
        objectName: "Nose_Nostril_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_L_morphtarget235
        objectName: "Nose_Nostril_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_R_morphtarget234
        objectName: "Nose_Crease_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_L_morphtarget233
        objectName: "Nose_Crease_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_R_morphtarget232
        objectName: "Nose_Nostril_Dilate_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_L_morphtarget285
        objectName: "Mouth_Pull_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_R_morphtarget230
        objectName: "Nose_Nostril_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_L_morphtarget229
        objectName: "Nose_Nostril_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_R_morphtarget228
        objectName: "Nose_Sneer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_L_morphtarget227
        objectName: "Nose_Sneer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_R_morphtarget226
        objectName: "Ear_Out_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_L_morphtarget225
        objectName: "Ear_Out_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_R_morphtarget224
        objectName: "Ear_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_L_morphtarget223
        objectName: "Ear_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_R_morphtarget222
        objectName: "Ear_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_L_morphtarget339
        objectName: "Brow_Raise_Inner_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_L_morphtarget349
        objectName: "Eye_Squint_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_R_morphtarget348
        objectName: "Eye_Blink_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_L_morphtarget347
        objectName: "Eye_Blink_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_R_morphtarget346
        objectName: "Brow_Compress_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_L_morphtarget345
        objectName: "Brow_Compress_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_R_morphtarget344
        objectName: "Brow_Drop_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_L_morphtarget343
        objectName: "Brow_Drop_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_R_morphtarget342
        objectName: "Brow_Raise_Outer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_L_morphtarget341
        objectName: "Brow_Raise_Outer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_R_morphtarget340
        objectName: "Brow_Raise_Inner_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_R_morphtarget350
        objectName: "Eye_Squint_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Lip_Open_morphtarget338
        objectName: "V_Lip_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Affricate_morphtarget337
        objectName: "V_Affricate"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Wide_morphtarget336
        objectName: "V_Wide"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_morphtarget335
        objectName: "V_Tight"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_O_morphtarget334
        objectName: "V_Tight_O"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Dental_Lip_morphtarget333
        objectName: "V_Dental_Lip"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Explosive_morphtarget332
        objectName: "V_Explosive"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Open_morphtarget331
        objectName: "V_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Backward_morphtarget330
        objectName: "Head_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Forward_morphtarget329
        objectName: "Head_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Down_morphtarget360
        objectName: "Eye_R_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_R_morphtarget370
        objectName: "Ear_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_L_morphtarget369
        objectName: "Ear_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_R_morphtarget368
        objectName: "Eyelash_Lower_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_R_morphtarget367
        objectName: "Eyelash_Lower_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_L_morphtarget366
        objectName: "Eyelash_Lower_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_L_morphtarget365
        objectName: "Eyelash_Lower_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_R_morphtarget364
        objectName: "Eyelash_Upper_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_R_morphtarget363
        objectName: "Eyelash_Upper_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_L_morphtarget362
        objectName: "Eyelash_Upper_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_L_morphtarget361
        objectName: "Eyelash_Upper_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_R_morphtarget328
        objectName: "Head_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Down_morphtarget359
        objectName: "Eye_L_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Up_morphtarget358
        objectName: "Eye_R_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Up_morphtarget357
        objectName: "Eye_L_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_R_morphtarget356
        objectName: "Eye_R_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_R_morphtarget355
        objectName: "Eye_L_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_L_morphtarget354
        objectName: "Eye_R_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_L_morphtarget353
        objectName: "Eye_L_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_R_morphtarget352
        objectName: "Eye_Wide_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_L_morphtarget351
        objectName: "Eye_Wide_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_R_morphtarget296
        objectName: "Mouth_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Close_morphtarget306
        objectName: "Mouth_Close"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Chin_Up_morphtarget305
        objectName: "Mouth_Chin_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_R_morphtarget304
        objectName: "Mouth_Down_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_L_morphtarget303
        objectName: "Mouth_Down_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_R_morphtarget302
        objectName: "Mouth_Up_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_L_morphtarget301
        objectName: "Mouth_Up_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Lower_morphtarget300
        objectName: "Mouth_Drop_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Upper_morphtarget299
        objectName: "Mouth_Drop_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Lower_morphtarget298
        objectName: "Mouth_Shrug_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Upper_morphtarget297
        objectName: "Mouth_Shrug_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Contract_morphtarget307
        objectName: "Mouth_Contract"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_L_morphtarget295
        objectName: "Mouth_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_R_morphtarget294
        objectName: "Mouth_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_L_morphtarget293
        objectName: "Mouth_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_R_morphtarget292
        objectName: "Mouth_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_L_morphtarget291
        objectName: "Mouth_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_morphtarget290
        objectName: "Mouth_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_morphtarget289
        objectName: "Mouth_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_R_morphtarget288
        objectName: "Mouth_Pull_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_L_morphtarget287
        objectName: "Mouth_Pull_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_R_morphtarget286
        objectName: "Mouth_Pull_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Up_morphtarget317
        objectName: "Neck_Swallow_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_L_morphtarget327
        objectName: "Head_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_R_morphtarget326
        objectName: "Head_Tilt_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_L_morphtarget325
        objectName: "Head_Tilt_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_R_morphtarget324
        objectName: "Head_Turn_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_L_morphtarget323
        objectName: "Head_Turn_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Down_morphtarget322
        objectName: "Head_Turn_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Up_morphtarget321
        objectName: "Head_Turn_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_R_morphtarget320
        objectName: "Neck_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_L_morphtarget319
        objectName: "Neck_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Down_morphtarget318
        objectName: "Neck_Swallow_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_L_morphtarget199
        objectName: "Eye_Blink_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Down_morphtarget316
        objectName: "Jaw_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Up_morphtarget315
        objectName: "Jaw_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_R_morphtarget314
        objectName: "Jaw_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_L_morphtarget313
        objectName: "Jaw_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Backward_morphtarget312
        objectName: "Jaw_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Forward_morphtarget311
        objectName: "Jaw_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Open_morphtarget310
        objectName: "Jaw_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_R_morphtarget309
        objectName: "Tongue_Bulge_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_L_morphtarget308
        objectName: "Tongue_Bulge_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_L_morphtarget81
        objectName: "Nose_Nostril_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_L_morphtarget91
        objectName: "Nose_Tip_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_R_morphtarget90
        objectName: "Nose_Nostril_In_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_L_morphtarget89
        objectName: "Nose_Nostril_In_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_R_morphtarget88
        objectName: "Nose_Nostril_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_L_morphtarget87
        objectName: "Nose_Nostril_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_R_morphtarget86
        objectName: "Nose_Crease_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_L_morphtarget85
        objectName: "Nose_Crease_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_R_morphtarget84
        objectName: "Nose_Nostril_Dilate_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_L_morphtarget83
        objectName: "Nose_Nostril_Dilate_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_R_morphtarget82
        objectName: "Nose_Nostril_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_R_morphtarget92
        objectName: "Nose_Tip_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_R_morphtarget80
        objectName: "Nose_Sneer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_L_morphtarget79
        objectName: "Nose_Sneer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_R_morphtarget78
        objectName: "Ear_Out_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_L_morphtarget77
        objectName: "Ear_Out_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_R_morphtarget76
        objectName: "Ear_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_L_morphtarget75
        objectName: "Ear_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_R_morphtarget74
        objectName: "Ear_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_L_morphtarget73
        objectName: "Ear_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_R_morphtarget72
        objectName: "Eyelash_Lower_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_R_morphtarget71
        objectName: "Eyelash_Lower_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_R_morphtarget102
        objectName: "Mouth_Smile_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_R_morphtarget112
        objectName: "Mouth_Press_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_L_morphtarget111
        objectName: "Mouth_Press_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_R_morphtarget110
        objectName: "Mouth_Dimple_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_L_morphtarget109
        objectName: "Mouth_Dimple_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_R_morphtarget108
        objectName: "Mouth_Stretch_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_L_morphtarget107
        objectName: "Mouth_Stretch_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_R_morphtarget106
        objectName: "Mouth_Frown_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_L_morphtarget105
        objectName: "Mouth_Frown_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_R_morphtarget104
        objectName: "Mouth_Smile_Sharp_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_L_morphtarget103
        objectName: "Mouth_Smile_Sharp_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_L_morphtarget70
        objectName: "Eyelash_Lower_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_L_morphtarget101
        objectName: "Mouth_Smile_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_R_morphtarget100
        objectName: "Cheek_Puff_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_L_morphtarget99
        objectName: "Cheek_Puff_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_R_morphtarget98
        objectName: "Cheek_Suck_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_L_morphtarget97
        objectName: "Cheek_Suck_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_R_morphtarget96
        objectName: "Cheek_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_L_morphtarget95
        objectName: "Cheek_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Down_morphtarget94
        objectName: "Nose_Tip_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Up_morphtarget93
        objectName: "Nose_Tip_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_O_morphtarget38
        objectName: "V_Tight_O"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_R_morphtarget48
        objectName: "Brow_Drop_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_L_morphtarget47
        objectName: "Brow_Drop_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_R_morphtarget46
        objectName: "Brow_Raise_Outer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_L_morphtarget45
        objectName: "Brow_Raise_Outer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_R_morphtarget44
        objectName: "Brow_Raise_Inner_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_L_morphtarget43
        objectName: "Brow_Raise_Inner_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Lip_Open_morphtarget42
        objectName: "V_Lip_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Affricate_morphtarget41
        objectName: "V_Affricate"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Wide_morphtarget40
        objectName: "V_Wide"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_morphtarget39
        objectName: "V_Tight"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_L_morphtarget49
        objectName: "Brow_Compress_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Dental_Lip_morphtarget37
        objectName: "V_Dental_Lip"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Explosive_morphtarget36
        objectName: "V_Explosive"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Open_morphtarget35
        objectName: "V_Open"
        attributes: MorphTarget.Position
    }
    Skin {
        id: skin34
        joints: [
            cc_Base_BoneRoot,
            cc_Base_Hip,
            cc_Base_Pelvis,
            cc_Base_L_Thigh,
            cc_Base_L_Calf,
            cc_Base_L_Foot,
            cc_Base_L_ToeBaseShareBone,
            cc_Base_L_ToeBase,
            cc_Base_L_PinkyToe1,
            cc_Base_L_RingToe1,
            cc_Base_L_MidToe1,
            cc_Base_L_IndexToe1,
            cc_Base_L_BigToe1,
            cc_Base_L_CalfTwist01,
            cc_Base_L_CalfTwist02,
            cc_Base_L_KneeShareBone,
            cc_Base_L_ThighTwist01,
            cc_Base_L_ThighTwist02,
            cc_Base_R_Thigh,
            cc_Base_R_Calf,
            cc_Base_R_KneeShareBone,
            cc_Base_R_Foot,
            cc_Base_R_ToeBase,
            cc_Base_R_BigToe1,
            cc_Base_R_PinkyToe1,
            cc_Base_R_RingToe1,
            cc_Base_R_IndexToe1,
            cc_Base_R_MidToe1,
            cc_Base_R_ToeBaseShareBone,
            cc_Base_R_CalfTwist01,
            cc_Base_R_CalfTwist02,
            cc_Base_R_ThighTwist01,
            cc_Base_R_ThighTwist02,
            cc_Base_Waist,
            cc_Base_Spine01,
            cc_Base_Spine02,
            cc_Base_NeckTwist01,
            cc_Base_NeckTwist02,
            cc_Base_Head,
            cc_Base_FacialBone,
            cc_Base_JawRoot,
            cc_Base_Tongue01,
            cc_Base_Tongue02,
            cc_Base_Tongue03,
            cc_Base_Teeth02,
            cc_Base_R_Eye,
            cc_Base_L_Eye,
            cc_Base_UpperJaw,
            cc_Base_Teeth01,
            cc_Base_L_Clavicle,
            cc_Base_L_Upperarm,
            cc_Base_L_Forearm,
            cc_Base_L_ForearmTwist01,
            cc_Base_L_ForearmTwist02,
            cc_Base_L_ElbowShareBone,
            cc_Base_L_Hand,
            cc_Base_L_Pinky1,
            cc_Base_L_Pinky2,
            cc_Base_L_Pinky3,
            cc_Base_L_Ring1,
            cc_Base_L_Ring2,
            cc_Base_L_Ring3,
            cc_Base_L_Mid1,
            cc_Base_L_Mid2,
            cc_Base_L_Mid3,
            cc_Base_L_Index1,
            cc_Base_L_Index2,
            cc_Base_L_Index3,
            cc_Base_L_Thumb1,
            cc_Base_L_Thumb2,
            cc_Base_L_Thumb3,
            cc_Base_L_UpperarmTwist01,
            cc_Base_L_UpperarmTwist02,
            cc_Base_L_RibsTwist,
            cc_Base_L_Breast,
            cc_Base_R_RibsTwist,
            cc_Base_R_Breast,
            cc_Base_R_Clavicle,
            cc_Base_R_Upperarm,
            cc_Base_R_Forearm,
            cc_Base_R_ElbowShareBone,
            cc_Base_R_ForearmTwist01,
            cc_Base_R_ForearmTwist02,
            cc_Base_R_Hand,
            cc_Base_R_Ring1,
            cc_Base_R_Ring2,
            cc_Base_R_Ring3,
            cc_Base_R_Mid1,
            cc_Base_R_Mid2,
            cc_Base_R_Mid3,
            cc_Base_R_Thumb1,
            cc_Base_R_Thumb2,
            cc_Base_R_Thumb3,
            cc_Base_R_Index1,
            cc_Base_R_Index2,
            cc_Base_R_Index3,
            cc_Base_R_Pinky1,
            cc_Base_R_Pinky2,
            cc_Base_R_Pinky3,
            cc_Base_R_UpperarmTwist01,
            cc_Base_R_UpperarmTwist02
        ]
        inverseBindPoses: [
            Qt.matrix4x4(100, 0, 0, 0, 0, 0, -100, 0, 0, 100, 0, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0, 0, 0, 0, 100, 0, -107.16, 0, 0, 100, 0, 0, 0, 0, 1),
            Qt.matrix4x4(100, -1.50763e-05, -1.50014e-06, 1.61558e-05, 1.50763e-05, 98.0392, 19.7056, -105.059, -1.50015e-06, -19.7056, 98.0392, 21.1165, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19943, -0.00154083, 7.15862, -2.19935, -99.9738, -0.625483, 104.87, -0.0155098, -0.625462, 99.9971, 1.10913, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.75838, -0.0421809, 7.4091, -1.7563, -99.9396, -2.99681, 56.7001, -0.0950633, -2.99579, 99.9542, 2.45743, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4254, 0.44619, 10.6957, 7.6864, 10.1705, -27.2384, 95.679, 2.96016, 3.3402, 96.2178, 27.0361, -5.07653, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8064, -4.35358, 4.44084, 8.50303, 4.05605, 8.5563, 99.5498, -11.5637, -4.714, 99.5381, -8.36324, -0.491555, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, -4.31662, 4.43681, 8.50295, 4.0552, 8.5548, 99.5499, -11.5636, -4.6768, 99.5398, -8.36343, -0.494889, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4797, -10.1827, 0.321515, 11.6262, 3.3234, -29.4543, 95.5052, -10.6293, -9.6305, 95.0197, 29.6391, -3.94976, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9388, -14.1291, 3.38768, 10.0395, 8.29467, -35.7843, 93.0083, -11.5382, -11.9292, 92.303, 36.5761, -5.2262, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, -11.9903, 6.4032, 8.33146, 8.90352, -21.6488, 97.2208, -13.2905, -10.271, 96.8894, 22.515, -4.04237, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, -12.9598, 6.3167, 6.8974, 9.26771, -23.6197, 96.7267, -13.2502, -11.0437, 96.3024, 24.5737, -4.53582, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, -4.20361, 6.53537, 4.82496, 6.44302, 2.29263, 99.765, -13.8397, -4.34362, 99.8853, -2.015, -1.1624, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.7602, -0.0420473, 7.40808, -1.75813, -99.9395, -2.99824, 56.7002, -0.0950096, -2.99723, 99.9541, 2.45824, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, 1.76061, -0.0444752, 7.40838, -1.75846, -99.9395, -2.99852, 31.2084, -0.0974532, -2.99746, 99.9541, 2.45817, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, 1.85246, -3.25678, 7.32702, -1.75497, -99.9397, -2.99578, 56.7, -3.31055, -2.93671, 99.9012, 2.69389, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.19789, -0.00126959, 7.16024, -2.19782, -99.9739, -0.620892, 104.87, -0.0151281, -0.620878, 99.9972, 1.10429, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, 2.1979, -0.000876542, 7.16006, -2.19783, -99.9739, -0.620904, 80.8223, -0.0147355, -0.620899, 99.9972, 1.10544, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9758, -2.19924, 0.00153699, -7.16575, 2.1992, -99.9739, -0.625714, 104.872, 0.0151791, -0.625438, 99.9985, 1.10604, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75776, 0.0422092, -7.41643, 1.75572, -99.9397, -2.99703, 56.704, 0.0947457, -2.99573, 99.9556, 2.45444, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9298, -1.85182, 3.25683, -7.33445, 1.75438, -99.9397, -2.99601, 56.704, 3.31021, -2.93666, 99.9025, 2.69113, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4253, -0.445641, -10.6957, -7.69344, -10.1708, -27.2377, 95.6805, 2.9584, -3.33968, 96.218, 27.0361, -5.08513, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8082, 4.31673, -4.43678, -8.51101, -4.05543, 8.55508, 99.5513, -11.5765, 4.67691, 99.5398, -8.36358, -0.498814, 0, 0, 0, 1),
            Qt.matrix4x4(-99.6976, 4.20418, -6.53536, -4.83289, -6.44323, 2.29301, 99.7664, -13.8527, 4.34419, 99.8853, -2.01513, -1.16698, 0, 0, 0, 1),
            Qt.matrix4x4(-99.4796, 10.1835, -0.321472, -11.6342, -3.32385, -29.4536, 95.5067, -10.6366, 9.63116, 95.0199, 29.639, -3.95668, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9387, 14.1298, -3.38765, -10.0477, -8.29509, -35.7835, 93.0098, -11.5462, 11.9297, 92.3033, 36.576, -5.23363, 0, 0, 0, 1),
            Qt.matrix4x4(-98.9552, 12.9605, -6.3167, -6.90615, -9.26806, -23.619, 96.7282, -13.2604, 11.0444, 96.3025, 24.5736, -4.5426, 0, 0, 0, 1),
            Qt.matrix4x4(-99.0718, 11.9906, -6.40327, -8.33963, -8.90384, -21.6481, 97.2223, -13.3019, 10.2712, 96.8896, 22.5149, -4.04937, 0, 0, 0, 1),
            Qt.matrix4x4(-99.8065, 4.35429, -4.43993, -8.5112, -4.05542, 8.5551, 99.5513, -11.5765, 4.71457, 99.5382, -8.36192, -0.495601, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75958, 0.0420813, -7.41542, 1.75754, -99.9396, -2.99846, 56.7041, 0.0946975, -2.99715, 99.9555, 2.45525, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9845, -1.75998, 0.0445132, -7.41571, 1.75787, -99.9396, -2.99877, 31.2144, 0.0971455, -2.99742, 99.9555, 2.45518, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.19769, 0.00128364, -7.16738, 2.19765, -99.9739, -0.621137, 104.872, 0.0148155, -0.620868, 99.9986, 1.10122, 0, 0, 0, 1),
            Qt.matrix4x4(-99.9759, -2.1977, 0.000890074, -7.16717, 2.19766, -99.9739, -0.621137, 80.8252, 0.0144221, -0.620877, 99.9986, 1.10237, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0595393, 0.0154999, -0.0669482, -0.0615188, 96.446, 26.423, -110.219, 0.000783055, -26.423, 96.446, 28.2733, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.00372025, 0.000168532, 0.00785771, 0.00372275, 99.9827, -1.86208, -117.476, -9.92306e-05, 1.86208, 99.9827, -5.07925, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0111038, 0.0023672, 0.0174147, 0.0113498, 97.2489, -23.2946, -126.012, 0.000284515, 23.2946, 97.249, -32.914, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0547365, -0.0101122, 0.0848241, 0.0556495, 98.7096, 16.0127, -152.92, 0.00121684, -16.0127, 98.7096, 28.2536, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0401262, -0.0105083, 0.0615821, 0.0414671, 96.0918, 27.6832, -151.999, -0.00101063, -27.6832, 96.0918, 46.7363, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.000265608, 6.35935e-05, -0.00285968, 0.000265636, 100, -0.0357807, -162.25, -6.34991e-05, 0.0357837, 100, 1.83509, 0, 0, 0, 1),
            Qt.matrix4x4(-0.000669168, 100, -0.0360327, -162.25, -6.24571e-05, 0.0360356, 100, 1.83469, 100, 0.000669196, 6.38568e-05, -0.00437637, 0, 0, 0, 1),
            Qt.matrix4x4(-0.00245299, 0.0400948, 100, -0.767438, -0.0145806, -100, 0.0400834, 163.645, 100, -0.0145796, 0.00246047, 0.0205602, 0, 0, 0, 1),
            Qt.matrix4x4(0.112315, -17.6141, 98.4365, 25.0468, -0.0182466, -98.4365, -17.6141, 160.852, 99.9999, 0.001822, -0.113771, -0.00270895, 0, 0, 0, 1),
            Qt.matrix4x4(0.120985, -36.4206, 93.1318, 54.7053, -0.0198629, -93.1319, -36.4206, 153.137, 99.9999, 0.0255649, -0.119909, -0.0410066, 0, 0, 0, 1),
            Qt.matrix4x4(0.121003, -36.42, 93.132, 52.9936, -0.0202164, -93.1321, -36.42, 153.137, 99.9999, 0.0252415, -0.120054, -0.0404762, 0, 0, 0, 1),
            Qt.matrix4x4(0.0169932, 0.0411495, 100, -4.08427, -0.0173491, 100, -0.0411355, -162.538, -100, -0.0173421, 0.0169987, 0.0252892, 0, 0, 0, 1),
            Qt.matrix4x4(100, -0.0131955, -0.0139593, 3.48603, -0.0139637, -0.0207999, -100, 5.17964, 0.0131926, 100, -0.0207988, -168.877, 0, 0, 0, 1),
            Qt.matrix4x4(100, 0.0126715, 0.0153175, -3.49781, 0.0153222, -0.0500856, -100, 5.23196, -0.0126638, 100, -0.0500845, -168.872, 0, 0, 0, 1),
            Qt.matrix4x4(0.00847962, 0.034713, 100, -4.58337, -0.000401467, -100, 0.0347213, 164.58, 100, -0.000404406, -0.00847784, -0.00446657, 0, 0, 0, 1),
            Qt.matrix4x4(0.00138361, 0.0389695, 100, -4.95796, 0.00525116, 100, -0.0389778, -164.247, -100, 0.00525169, 0.00137992, 0.00236788, 0, 0, 0, 1),
            Qt.matrix4x4(-1.88568, -99.8883, 4.33249, 149.837, 97.3862, -2.81603, -22.5387, -0.808774, 22.6356, 3.79424, 97.3305, -4.74137, 0, 0, 0, 1),
            Qt.matrix4x4(-49.807, -86.6412, 3.54302, 137.155, 86.7134, -49.7753, 1.79, 61.5499, 0.212671, 3.96382, 99.9212, -1.52919, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.5239, 136.91, 86.3604, -50.3177, 3.16266, 35.73, -0.95603, 4.63749, 99.8878, -2.00221, 0, 0, 0, 1),
            Qt.matrix4x4(-50.409, -86.2932, 3.52318, 136.91, 86.3598, -50.3188, 3.16266, 35.7316, -0.956336, 4.63688, 99.8879, -2.00127, 0, 0, 0, 1),
            Qt.matrix4x4(-50.408, -86.2938, 3.52317, 136.91, 86.3604, -50.3177, 3.16351, 23.7177, -0.957131, 4.63729, 99.8878, -2.00141, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4649, -86.264, 3.43616, 136.888, 86.3275, -50.3797, 3.07288, 35.8233, -0.91966, 4.51709, 99.8937, -1.85184, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7679, -87.7827, 3.52396, 137.204, 87.3005, -47.8784, -9.28884, 7.72614, 9.84121, -1.36064, 99.5053, -0.92711, 0, 0, 0, 1),
            Qt.matrix4x4(-49.9004, -86.5883, 3.52285, 136.803, 86.6599, -49.8627, 1.94246, 2.44348, 0.0746406, 4.0222, 99.9191, 0.988494, 0, 0, 0, 1),
            Qt.matrix4x4(-52.663, -84.9267, 3.75148, 136.743, 85.0063, -52.648, 1.4555, 4.14878, 0.738971, 3.9555, 99.919, 0.612436, 0, 0, 0, 1),
            Qt.matrix4x4(-44.5186, -89.4714, 3.60109, 136.398, 89.4575, -44.6162, -2.59674, -10.0752, 3.93001, 2.06542, 99.9014, 0.6083, 0, 0, 0, 1),
            Qt.matrix4x4(-49.6224, -86.7491, 3.49327, 137.198, 86.8192, -49.5725, 2.23479, 1.7522, -0.206964, 4.14179, 99.914, -0.821401, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6708, -83.6615, 3.44216, 137.086, 83.7279, -54.6641, 1.21753, 5.93462, 0.863019, 3.54768, 99.9333, -0.868637, 0, 0, 0, 1),
            Qt.matrix4x4(-47.9847, -87.6646, 3.52107, 136.953, 87.7066, -48.0329, -0.627888, -6.90922, 2.24171, 2.78693, 99.936, -0.96638, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5574, -86.1786, 4.14779, 137.418, 86.2745, -50.4515, 3.36886, 2.85757, -0.810612, 5.2817, 99.8571, -3.58848, 0, 0, 0, 1),
            Qt.matrix4x4(-51.6067, -85.587, 3.40699, 137.448, 85.6431, -51.4929, 3.70805, 0.185814, -1.41925, 4.83145, 99.8731, -2.62696, 0, 0, 0, 1),
            Qt.matrix4x4(-48.7135, -87.2623, 3.50497, 137.288, 87.3183, -48.5935, 3.76532, -7.09703, -1.58252, 4.89471, 99.8676, -2.58154, 0, 0, 0, 1),
            Qt.matrix4x4(-50.7218, -86.0765, 4.25742, 137.125, 86.1791, -50.6972, 1.71972, 3.07359, 0.678116, 4.54128, 99.8945, -5.83135, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4655, -85.0736, 3.13906, 137.165, 85.1159, -52.3497, 3.84519, 2.04567, -1.62795, 4.68924, 99.8767, -4.38814, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0827, -87.615, 3.41648, 136.971, 87.574, -47.7943, 6.81865, -7.42734, -4.34128, 6.27054, 99.7087, -4.27729, 0, 0, 0, 1),
            Qt.matrix4x4(-64.961, -73.2123, 20.4945, 129.222, 59.5939, -32.2961, 73.5223, 4.4705, -47.2084, 59.9743, 64.61, -44.6085, 0, 0, 0, 1),
            Qt.matrix4x4(-57.9161, -77.0926, 26.5039, 129.246, 77.6561, -42.2805, 46.7107, 0.294844, -24.8045, 47.6349, 84.3543, -44.5523, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7869, -80.2894, 29.525, 128.919, 81.9393, -36.6397, 44.085, -11.843, -24.5778, 47.0228, 84.7632, -43.9857, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8061, -86.6307, 3.80604, 137.151, 86.7135, -49.775, 1.7906, 61.5495, 0.343252, 4.19218, 99.9115, -1.8906, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8068, -86.6414, 3.54283, 137.155, 86.7135, -49.775, 1.79084, 48.1756, 0.211837, 3.96408, 99.9212, -1.52922, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0121952, -0.0016524, 10.1203, -0.00110477, 4.47696, 99.8997, -19.2259, 0.0122569, 99.8997, -4.47694, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, 10.1202, -0.00114441, 4.47696, 99.8997, -21.2259, 0.0122638, 99.8997, -4.47693, -137.258, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122068, -0.00170066, -10.1238, -0.00115246, 4.47694, 99.8997, -19.2055, 0.0122707, 99.8997, -4.47693, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-100, 0.0122003, -0.00169231, -10.1238, -0.00114441, 4.47695, 99.8997, -21.2055, 0.0122638, 99.8997, -4.47694, -137.264, 0, 0, 0, 1),
            Qt.matrix4x4(-1.85887, 99.8888, -4.33163, -149.836, -97.3861, -2.78984, -22.5425, -0.846488, -22.6383, 3.79937, 97.3297, -4.74888, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7835, 86.6547, -3.54387, -137.187, -86.7269, -49.7519, 1.78613, 61.4895, -0.21537, 3.96269, 99.9212, -1.52094, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3848, 86.3073, -3.52505, -136.942, -86.374, -50.2947, 3.1588, 35.7086, 0.953363, 4.63628, 99.8879, -1.99405, 0, 0, 0, 1),
            Qt.matrix4x4(-50.4418, 86.2775, -3.43736, -136.92, -86.3411, -50.3567, 3.06902, 35.8021, 0.91693, 4.51592, 99.8938, -1.84374, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3858, 86.3067, -3.52427, -136.942, -86.3734, -50.2957, 3.1588, 35.7102, 0.953702, 4.63562, 99.8879, -1.99303, 0, 0, 0, 1),
            Qt.matrix4x4(-50.3847, 86.3073, -3.52431, -136.942, -86.374, -50.2946, 3.15966, 23.7108, 0.954484, 4.63607, 99.8879, -1.99325, 0, 0, 0, 1),
            Qt.matrix4x4(-47.7442, 87.7956, -3.52487, -137.236, -87.313, -47.8549, -9.29271, 7.73164, -9.8454, -1.35906, 99.5049, -0.917997, 0, 0, 0, 1),
            Qt.matrix4x4(-49.5991, 86.7624, -3.49434, -137.229, -86.8325, -49.5493, 2.23093, 1.75948, 0.204188, 4.14074, 99.914, -0.813094, 0, 0, 0, 1),
            Qt.matrix4x4(-54.6474, 83.6768, -3.44239, -137.118, -83.7431, -54.6408, 1.21375, 5.94218, -0.865323, 3.54604, 99.9334, -0.858772, 0, 0, 0, 1),
            Qt.matrix4x4(-47.961, 87.6774, -3.52205, -136.985, -87.7194, -48.0094, -0.63177, -6.9061, -2.24483, 2.78652, 99.936, -0.958057, 0, 0, 0, 1),
            Qt.matrix4x4(-50.5341, 86.1921, -4.14882, -137.449, -86.2882, -50.4284, 3.365, 2.86407, 0.808178, 5.28042, 99.8572, -3.57899, 0, 0, 0, 1),
            Qt.matrix4x4(-51.5833, 85.6011, -3.40781, -137.478, -85.6572, -51.4697, 3.70416, 0.191616, 1.41681, 4.82976, 99.8732, -2.61691, 0, 0, 0, 1),
            Qt.matrix4x4(-48.6899, 87.2755, -3.50582, -137.319, -87.3316, -48.5701, 3.76144, -7.092, 1.58004, 4.89313, 99.8677, -2.5717, 0, 0, 0, 1),
            Qt.matrix4x4(-64.9407, 73.2298, -20.4965, -129.252, -59.6054, -32.281, 73.5196, 4.48364, 47.2218, 59.9611, 64.6124, -44.6136, 0, 0, 0, 1),
            Qt.matrix4x4(-57.8947, 77.1081, -26.5056, -129.278, -77.6691, -42.2604, 46.7073, 0.307031, 24.8138, 47.6277, 84.3557, -44.5532, 0, 0, 0, 1),
            Qt.matrix4x4(-51.7624, 80.3053, -29.5247, -128.953, -81.9515, -36.6168, 44.0813, -11.8357, 24.5886, 47.0134, 84.7652, -43.9827, 0, 0, 0, 1),
            Qt.matrix4x4(-50.6986, 86.0901, -4.25856, -137.155, -86.1927, -50.6742, 1.71586, 3.08145, -0.680797, 4.54049, 99.8945, -5.81861, 0, 0, 0, 1),
            Qt.matrix4x4(-52.4425, 85.0878, -3.14012, -137.195, -85.1302, -52.3269, 3.84136, 2.05416, 1.6254, 4.6877, 99.8769, -4.37503, 0, 0, 0, 1),
            Qt.matrix4x4(-48.0592, 87.6278, -3.41758, -137.002, -87.587, -47.771, 6.81477, -7.42022, 4.33903, 6.26848, 99.709, -4.26478, 0, 0, 0, 1),
            Qt.matrix4x4(-49.8771, 86.6017, -3.52394, -136.835, -86.6733, -49.8395, 1.93857, 2.44804, -0.0774823, 4.02122, 99.9191, 0.995909, 0, 0, 0, 1),
            Qt.matrix4x4(-52.6416, 84.9398, -3.75452, -136.775, -85.0194, -52.6268, 1.45174, 4.15666, -0.742781, 3.95629, 99.919, 0.617262, 0, 0, 0, 1),
            Qt.matrix4x4(-44.4949, 89.4831, -3.60251, -136.43, -89.4691, -44.5927, -2.60061, -10.0723, -3.93356, 2.06599, 99.9013, 0.615095, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7826, 86.644, -3.80768, -137.182, -86.727, -49.7518, 1.78673, 61.4894, -0.346297, 4.19176, 99.9115, -1.88352, 0, 0, 0, 1),
            Qt.matrix4x4(-49.7834, 86.6548, -3.54388, -137.187, -86.727, -49.7518, 1.78696, 48.1346, -0.214659, 3.96311, 99.9212, -1.52125, 0, 0, 0, 1)
        ]
    }
    PrincipledMaterial {
        id: std_Eyelash_material
        objectName: "Std_Eyelash"
        baseColorMap: _10_texture
        roughness: 0.858578622341156
        normalMap: _11_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Blend
    }
    PrincipledMaterial {
        id: std_Nails_material
        objectName: "Std_Nails"
        baseColorMap: _8_texture
        roughness: 0.5527864098548889
        normalMap: _9_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: std_Skin_Leg_material
        objectName: "Std_Skin_Leg"
        baseColorMap: _6_texture
        roughness: 0.5527864098548889
        normalMap: _7_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: std_Skin_Arm_material
        objectName: "Std_Skin_Arm"
        baseColorMap: _4_texture
        roughness: 0.5527864098548889
        normalMap: _5_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: std_Skin_Body_material
        objectName: "Std_Skin_Body"
        baseColorMap: _2_texture
        roughness: 0.5527864098548889
        normalMap: _3_texture
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    MorphTarget {
        id: eye_L_Look_R_morphtarget59
        objectName: "Eye_L_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_L_morphtarget69
        objectName: "Eyelash_Lower_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_R_morphtarget68
        objectName: "Eyelash_Upper_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_R_morphtarget67
        objectName: "Eyelash_Upper_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_L_morphtarget66
        objectName: "Eyelash_Upper_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_L_morphtarget65
        objectName: "Eyelash_Upper_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Down_morphtarget64
        objectName: "Eye_R_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Down_morphtarget63
        objectName: "Eye_L_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Up_morphtarget62
        objectName: "Eye_R_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Up_morphtarget61
        objectName: "Eye_L_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_R_morphtarget60
        objectName: "Eye_R_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_L_morphtarget113
        objectName: "Mouth_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_L_morphtarget58
        objectName: "Eye_R_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_L_morphtarget57
        objectName: "Eye_L_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_R_morphtarget56
        objectName: "Eye_Wide_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_L_morphtarget55
        objectName: "Eye_Wide_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_R_morphtarget54
        objectName: "Eye_Squint_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_L_morphtarget53
        objectName: "Eye_Squint_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_R_morphtarget52
        objectName: "Eye_Blink_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_L_morphtarget51
        objectName: "Eye_Blink_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_R_morphtarget50
        objectName: "Brow_Compress_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Up_morphtarget167
        objectName: "Jaw_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_L_morphtarget177
        objectName: "Head_Tilt_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_R_morphtarget176
        objectName: "Head_Turn_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_L_morphtarget175
        objectName: "Head_Turn_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Down_morphtarget174
        objectName: "Head_Turn_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Up_morphtarget173
        objectName: "Head_Turn_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_R_morphtarget172
        objectName: "Neck_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_L_morphtarget171
        objectName: "Neck_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Down_morphtarget170
        objectName: "Neck_Swallow_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Up_morphtarget169
        objectName: "Neck_Swallow_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Down_morphtarget168
        objectName: "Jaw_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_R_morphtarget178
        objectName: "Head_Tilt_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_R_morphtarget166
        objectName: "Jaw_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_L_morphtarget165
        objectName: "Jaw_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Backward_morphtarget164
        objectName: "Jaw_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Forward_morphtarget163
        objectName: "Jaw_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Open_morphtarget162
        objectName: "Jaw_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_R_morphtarget161
        objectName: "Tongue_Bulge_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_L_morphtarget160
        objectName: "Tongue_Bulge_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Contract_morphtarget159
        objectName: "Mouth_Contract"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Close_morphtarget158
        objectName: "Mouth_Close"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Chin_Up_morphtarget157
        objectName: "Mouth_Chin_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Wide_morphtarget188
        objectName: "V_Wide"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_R_morphtarget198
        objectName: "Brow_Compress_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_L_morphtarget197
        objectName: "Brow_Compress_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_R_morphtarget196
        objectName: "Brow_Drop_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_L_morphtarget195
        objectName: "Brow_Drop_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_R_morphtarget194
        objectName: "Brow_Raise_Outer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_L_morphtarget193
        objectName: "Brow_Raise_Outer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_R_morphtarget192
        objectName: "Brow_Raise_Inner_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_L_morphtarget191
        objectName: "Brow_Raise_Inner_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Lip_Open_morphtarget190
        objectName: "V_Lip_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Affricate_morphtarget189
        objectName: "V_Affricate"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_R_morphtarget156
        objectName: "Mouth_Down_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_morphtarget187
        objectName: "V_Tight"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_O_morphtarget186
        objectName: "V_Tight_O"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Dental_Lip_morphtarget185
        objectName: "V_Dental_Lip"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Explosive_morphtarget184
        objectName: "V_Explosive"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Open_morphtarget183
        objectName: "V_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Backward_morphtarget182
        objectName: "Head_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Forward_morphtarget181
        objectName: "Head_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_R_morphtarget180
        objectName: "Head_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_L_morphtarget179
        objectName: "Head_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_R_morphtarget124
        objectName: "Mouth_Funnel_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_R_morphtarget134
        objectName: "Mouth_Push_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_L_morphtarget133
        objectName: "Mouth_Push_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_R_morphtarget132
        objectName: "Mouth_Roll_Out_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_L_morphtarget131
        objectName: "Mouth_Roll_Out_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_R_morphtarget130
        objectName: "Mouth_Roll_Out_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_L_morphtarget129
        objectName: "Mouth_Roll_Out_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_R_morphtarget128
        objectName: "Mouth_Roll_In_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_L_morphtarget127
        objectName: "Mouth_Roll_In_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_R_morphtarget126
        objectName: "Mouth_Roll_In_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_L_morphtarget125
        objectName: "Mouth_Roll_In_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_L_morphtarget135
        objectName: "Mouth_Push_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_L_morphtarget123
        objectName: "Mouth_Funnel_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_R_morphtarget122
        objectName: "Mouth_Funnel_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_L_morphtarget121
        objectName: "Mouth_Funnel_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_R_morphtarget120
        objectName: "Mouth_Pucker_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_L_morphtarget119
        objectName: "Mouth_Pucker_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_R_morphtarget118
        objectName: "Mouth_Pucker_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_L_morphtarget117
        objectName: "Mouth_Pucker_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_R_morphtarget116
        objectName: "Mouth_Blow_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_L_morphtarget115
        objectName: "Mouth_Blow_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_R_morphtarget114
        objectName: "Mouth_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_L_morphtarget145
        objectName: "Mouth_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_L_morphtarget155
        objectName: "Mouth_Down_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_R_morphtarget154
        objectName: "Mouth_Up_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_L_morphtarget153
        objectName: "Mouth_Up_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Lower_morphtarget152
        objectName: "Mouth_Drop_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Upper_morphtarget151
        objectName: "Mouth_Drop_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Lower_morphtarget150
        objectName: "Mouth_Shrug_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Upper_morphtarget149
        objectName: "Mouth_Shrug_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_R_morphtarget148
        objectName: "Mouth_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_L_morphtarget147
        objectName: "Mouth_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_R_morphtarget146
        objectName: "Mouth_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_L_morphtarget371
        objectName: "Ear_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_R_morphtarget144
        objectName: "Mouth_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_L_morphtarget143
        objectName: "Mouth_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_morphtarget142
        objectName: "Mouth_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_morphtarget141
        objectName: "Mouth_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_R_morphtarget140
        objectName: "Mouth_Pull_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_L_morphtarget139
        objectName: "Mouth_Pull_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_R_morphtarget138
        objectName: "Mouth_Pull_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_L_morphtarget137
        objectName: "Mouth_Pull_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_R_morphtarget136
        objectName: "Mouth_Push_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_L_morphtarget597
        objectName: "Mouth_Up_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Forward_morphtarget607
        objectName: "Jaw_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Open_morphtarget606
        objectName: "Jaw_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_R_morphtarget605
        objectName: "Tongue_Bulge_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_L_morphtarget604
        objectName: "Tongue_Bulge_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Contract_morphtarget603
        objectName: "Mouth_Contract"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Close_morphtarget602
        objectName: "Mouth_Close"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Chin_Up_morphtarget601
        objectName: "Mouth_Chin_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_R_morphtarget600
        objectName: "Mouth_Down_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_L_morphtarget599
        objectName: "Mouth_Down_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_R_morphtarget598
        objectName: "Mouth_Up_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Backward_morphtarget608
        objectName: "Jaw_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Lower_morphtarget596
        objectName: "Mouth_Drop_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Upper_morphtarget595
        objectName: "Mouth_Drop_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Lower_morphtarget594
        objectName: "Mouth_Shrug_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Upper_morphtarget593
        objectName: "Mouth_Shrug_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_R_morphtarget592
        objectName: "Mouth_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_L_morphtarget591
        objectName: "Mouth_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_R_morphtarget590
        objectName: "Mouth_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_L_morphtarget589
        objectName: "Mouth_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_R_morphtarget588
        objectName: "Mouth_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_L_morphtarget587
        objectName: "Mouth_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Down_morphtarget618
        objectName: "Head_Turn_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Explosive_morphtarget628
        objectName: "V_Explosive"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Open_morphtarget627
        objectName: "V_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Backward_morphtarget626
        objectName: "Head_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Forward_morphtarget625
        objectName: "Head_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_R_morphtarget624
        objectName: "Head_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_L_morphtarget623
        objectName: "Head_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_R_morphtarget622
        objectName: "Head_Tilt_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_L_morphtarget621
        objectName: "Head_Tilt_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_R_morphtarget620
        objectName: "Head_Turn_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_L_morphtarget619
        objectName: "Head_Turn_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_morphtarget586
        objectName: "Mouth_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Up_morphtarget617
        objectName: "Head_Turn_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_R_morphtarget616
        objectName: "Neck_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_L_morphtarget615
        objectName: "Neck_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Down_morphtarget614
        objectName: "Neck_Swallow_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Up_morphtarget613
        objectName: "Neck_Swallow_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Down_morphtarget612
        objectName: "Jaw_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Up_morphtarget611
        objectName: "Jaw_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_R_morphtarget610
        objectName: "Jaw_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_L_morphtarget609
        objectName: "Jaw_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_R_morphtarget554
        objectName: "Mouth_Dimple_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_R_morphtarget564
        objectName: "Mouth_Pucker_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_L_morphtarget563
        objectName: "Mouth_Pucker_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_R_morphtarget562
        objectName: "Mouth_Pucker_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_L_morphtarget561
        objectName: "Mouth_Pucker_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_R_morphtarget560
        objectName: "Mouth_Blow_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_L_morphtarget559
        objectName: "Mouth_Blow_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_R_morphtarget558
        objectName: "Mouth_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_L_morphtarget557
        objectName: "Mouth_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_R_morphtarget556
        objectName: "Mouth_Press_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_L_morphtarget555
        objectName: "Mouth_Press_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_L_morphtarget565
        objectName: "Mouth_Funnel_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_L_morphtarget553
        objectName: "Mouth_Dimple_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_R_morphtarget552
        objectName: "Mouth_Stretch_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_L_morphtarget551
        objectName: "Mouth_Stretch_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_R_morphtarget550
        objectName: "Mouth_Frown_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_L_morphtarget549
        objectName: "Mouth_Frown_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_R_morphtarget548
        objectName: "Mouth_Smile_Sharp_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_L_morphtarget547
        objectName: "Mouth_Smile_Sharp_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_R_morphtarget546
        objectName: "Mouth_Smile_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_L_morphtarget545
        objectName: "Mouth_Smile_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_R_morphtarget544
        objectName: "Cheek_Puff_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_L_morphtarget575
        objectName: "Mouth_Roll_Out_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_morphtarget585
        objectName: "Mouth_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_R_morphtarget584
        objectName: "Mouth_Pull_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_L_morphtarget583
        objectName: "Mouth_Pull_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_R_morphtarget582
        objectName: "Mouth_Pull_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_L_morphtarget581
        objectName: "Mouth_Pull_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_R_morphtarget580
        objectName: "Mouth_Push_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_L_morphtarget579
        objectName: "Mouth_Push_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_R_morphtarget578
        objectName: "Mouth_Push_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_L_morphtarget577
        objectName: "Mouth_Push_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_R_morphtarget576
        objectName: "Mouth_Roll_Out_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Dental_Lip_morphtarget629
        objectName: "V_Dental_Lip"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_R_morphtarget574
        objectName: "Mouth_Roll_Out_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_L_morphtarget573
        objectName: "Mouth_Roll_Out_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_R_morphtarget572
        objectName: "Mouth_Roll_In_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_L_morphtarget571
        objectName: "Mouth_Roll_In_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_R_morphtarget570
        objectName: "Mouth_Roll_In_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_L_morphtarget569
        objectName: "Mouth_Roll_In_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_R_morphtarget568
        objectName: "Mouth_Funnel_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_L_morphtarget567
        objectName: "Mouth_Funnel_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_R_morphtarget566
        objectName: "Mouth_Funnel_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_L_morphtarget683
        objectName: "Nose_Tip_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_L_morphtarget693
        objectName: "Mouth_Smile_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_R_morphtarget692
        objectName: "Cheek_Puff_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_L_morphtarget691
        objectName: "Cheek_Puff_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_R_morphtarget690
        objectName: "Cheek_Suck_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_L_morphtarget689
        objectName: "Cheek_Suck_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_R_morphtarget688
        objectName: "Cheek_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_L_morphtarget687
        objectName: "Cheek_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Down_morphtarget686
        objectName: "Nose_Tip_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Up_morphtarget685
        objectName: "Nose_Tip_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_R_morphtarget684
        objectName: "Nose_Tip_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_R_morphtarget694
        objectName: "Mouth_Smile_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_R_morphtarget682
        objectName: "Nose_Nostril_In_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_L_morphtarget681
        objectName: "Nose_Nostril_In_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_R_morphtarget680
        objectName: "Nose_Nostril_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_L_morphtarget679
        objectName: "Nose_Nostril_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_R_morphtarget678
        objectName: "Nose_Crease_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_L_morphtarget677
        objectName: "Nose_Crease_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_R_morphtarget676
        objectName: "Nose_Nostril_Dilate_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_L_morphtarget675
        objectName: "Nose_Nostril_Dilate_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_R_morphtarget674
        objectName: "Nose_Nostril_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_L_morphtarget673
        objectName: "Nose_Nostril_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_R_morphtarget704
        objectName: "Mouth_Press_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_R_morphtarget714
        objectName: "Mouth_Funnel_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_L_morphtarget713
        objectName: "Mouth_Funnel_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_R_morphtarget712
        objectName: "Mouth_Pucker_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_L_morphtarget711
        objectName: "Mouth_Pucker_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_R_morphtarget710
        objectName: "Mouth_Pucker_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_L_morphtarget709
        objectName: "Mouth_Pucker_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_R_morphtarget708
        objectName: "Mouth_Blow_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_L_morphtarget707
        objectName: "Mouth_Blow_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_R_morphtarget706
        objectName: "Mouth_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_L_morphtarget705
        objectName: "Mouth_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_R_morphtarget672
        objectName: "Nose_Sneer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_L_morphtarget703
        objectName: "Mouth_Press_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_R_morphtarget702
        objectName: "Mouth_Dimple_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_L_morphtarget701
        objectName: "Mouth_Dimple_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_R_morphtarget700
        objectName: "Mouth_Stretch_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_L_morphtarget699
        objectName: "Mouth_Stretch_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_R_morphtarget698
        objectName: "Mouth_Frown_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_L_morphtarget697
        objectName: "Mouth_Frown_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_R_morphtarget696
        objectName: "Mouth_Smile_Sharp_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_L_morphtarget695
        objectName: "Mouth_Smile_Sharp_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_R_morphtarget640
        objectName: "Brow_Drop_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_L_morphtarget650
        objectName: "Eye_R_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_L_morphtarget649
        objectName: "Eye_L_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_R_morphtarget648
        objectName: "Eye_Wide_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_L_morphtarget647
        objectName: "Eye_Wide_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_R_morphtarget646
        objectName: "Eye_Squint_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_L_morphtarget645
        objectName: "Eye_Squint_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_R_morphtarget644
        objectName: "Eye_Blink_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_L_morphtarget643
        objectName: "Eye_Blink_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_R_morphtarget642
        objectName: "Brow_Compress_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_L_morphtarget641
        objectName: "Brow_Compress_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_R_morphtarget651
        objectName: "Eye_L_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_L_morphtarget639
        objectName: "Brow_Drop_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_R_morphtarget638
        objectName: "Brow_Raise_Outer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_L_morphtarget637
        objectName: "Brow_Raise_Outer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_R_morphtarget636
        objectName: "Brow_Raise_Inner_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_L_morphtarget635
        objectName: "Brow_Raise_Inner_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Lip_Open_morphtarget634
        objectName: "V_Lip_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Affricate_morphtarget633
        objectName: "V_Affricate"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Wide_morphtarget632
        objectName: "V_Wide"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_morphtarget631
        objectName: "V_Tight"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_O_morphtarget630
        objectName: "V_Tight_O"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_L_morphtarget661
        objectName: "Eyelash_Lower_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_L_morphtarget671
        objectName: "Nose_Sneer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_R_morphtarget670
        objectName: "Ear_Out_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_L_morphtarget669
        objectName: "Ear_Out_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_R_morphtarget668
        objectName: "Ear_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_L_morphtarget667
        objectName: "Ear_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_R_morphtarget666
        objectName: "Ear_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_L_morphtarget665
        objectName: "Ear_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_R_morphtarget664
        objectName: "Eyelash_Lower_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_R_morphtarget663
        objectName: "Eyelash_Lower_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_L_morphtarget662
        objectName: "Eyelash_Lower_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_L_morphtarget543
        objectName: "Cheek_Puff_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_R_morphtarget660
        objectName: "Eyelash_Upper_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_R_morphtarget659
        objectName: "Eyelash_Upper_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_L_morphtarget658
        objectName: "Eyelash_Upper_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_L_morphtarget657
        objectName: "Eyelash_Upper_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Down_morphtarget656
        objectName: "Eye_R_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Down_morphtarget655
        objectName: "Eye_L_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Up_morphtarget654
        objectName: "Eye_R_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Up_morphtarget653
        objectName: "Eye_L_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_R_morphtarget652
        objectName: "Eye_R_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_L_morphtarget425
        objectName: "Mouth_Roll_Out_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_L_morphtarget435
        objectName: "Mouth_Pull_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_R_morphtarget434
        objectName: "Mouth_Pull_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Upper_L_morphtarget433
        objectName: "Mouth_Pull_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_R_morphtarget432
        objectName: "Mouth_Push_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Lower_L_morphtarget431
        objectName: "Mouth_Push_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_R_morphtarget430
        objectName: "Mouth_Push_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Push_Upper_L_morphtarget429
        objectName: "Mouth_Push_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_R_morphtarget428
        objectName: "Mouth_Roll_Out_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Lower_L_morphtarget427
        objectName: "Mouth_Roll_Out_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_Out_Upper_R_morphtarget426
        objectName: "Mouth_Roll_Out_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pull_Lower_R_morphtarget436
        objectName: "Mouth_Pull_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_R_morphtarget424
        objectName: "Mouth_Roll_In_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Lower_L_morphtarget423
        objectName: "Mouth_Roll_In_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_R_morphtarget422
        objectName: "Mouth_Roll_In_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Roll_In_Upper_L_morphtarget421
        objectName: "Mouth_Roll_In_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_R_morphtarget420
        objectName: "Mouth_Funnel_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_L_morphtarget419
        objectName: "Mouth_Funnel_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_R_morphtarget418
        objectName: "Mouth_Funnel_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Up_L_morphtarget417
        objectName: "Mouth_Funnel_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_R_morphtarget416
        objectName: "Mouth_Pucker_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Down_L_morphtarget415
        objectName: "Mouth_Pucker_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Lower_morphtarget446
        objectName: "Mouth_Shrug_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_L_morphtarget456
        objectName: "Tongue_Bulge_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Contract_morphtarget455
        objectName: "Mouth_Contract"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Close_morphtarget454
        objectName: "Mouth_Close"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Chin_Up_morphtarget453
        objectName: "Mouth_Chin_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_R_morphtarget452
        objectName: "Mouth_Down_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_Lower_L_morphtarget451
        objectName: "Mouth_Down_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_R_morphtarget450
        objectName: "Mouth_Up_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_Upper_L_morphtarget449
        objectName: "Mouth_Up_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Lower_morphtarget448
        objectName: "Mouth_Drop_Lower"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Drop_Upper_morphtarget447
        objectName: "Mouth_Drop_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_R_morphtarget414
        objectName: "Mouth_Pucker_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Shrug_Upper_morphtarget445
        objectName: "Mouth_Shrug_Upper"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_R_morphtarget444
        objectName: "Mouth_Lower_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Lower_L_morphtarget443
        objectName: "Mouth_Lower_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_R_morphtarget442
        objectName: "Mouth_Upper_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Upper_L_morphtarget441
        objectName: "Mouth_Upper_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_R_morphtarget440
        objectName: "Mouth_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_L_morphtarget439
        objectName: "Mouth_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Down_morphtarget438
        objectName: "Mouth_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Up_morphtarget437
        objectName: "Mouth_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_R_morphtarget382
        objectName: "Nose_Crease_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_R_morphtarget392
        objectName: "Cheek_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_L_morphtarget391
        objectName: "Cheek_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Down_morphtarget390
        objectName: "Nose_Tip_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Up_morphtarget389
        objectName: "Nose_Tip_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_R_morphtarget388
        objectName: "Nose_Tip_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_L_morphtarget387
        objectName: "Nose_Tip_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_R_morphtarget386
        objectName: "Nose_Nostril_In_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_L_morphtarget385
        objectName: "Nose_Nostril_In_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_R_morphtarget384
        objectName: "Nose_Nostril_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_L_morphtarget383
        objectName: "Nose_Nostril_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_L_morphtarget393
        objectName: "Cheek_Suck_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_L_morphtarget381
        objectName: "Nose_Crease_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_R_morphtarget380
        objectName: "Nose_Nostril_Dilate_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_L_morphtarget379
        objectName: "Nose_Nostril_Dilate_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_R_morphtarget378
        objectName: "Nose_Nostril_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_L_morphtarget377
        objectName: "Nose_Nostril_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_R_morphtarget376
        objectName: "Nose_Sneer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_L_morphtarget375
        objectName: "Nose_Sneer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_R_morphtarget374
        objectName: "Ear_Out_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_L_morphtarget373
        objectName: "Ear_Out_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_R_morphtarget372
        objectName: "Ear_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_L_morphtarget403
        objectName: "Mouth_Stretch_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Pucker_Up_L_morphtarget413
        objectName: "Mouth_Pucker_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_R_morphtarget412
        objectName: "Mouth_Blow_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Blow_L_morphtarget411
        objectName: "Mouth_Blow_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_R_morphtarget410
        objectName: "Mouth_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Tighten_L_morphtarget409
        objectName: "Mouth_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_R_morphtarget408
        objectName: "Mouth_Press_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Press_L_morphtarget407
        objectName: "Mouth_Press_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_R_morphtarget406
        objectName: "Mouth_Dimple_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Dimple_L_morphtarget405
        objectName: "Mouth_Dimple_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Stretch_R_morphtarget404
        objectName: "Mouth_Stretch_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: tongue_Bulge_R_morphtarget457
        objectName: "Tongue_Bulge_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_R_morphtarget402
        objectName: "Mouth_Frown_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Frown_L_morphtarget401
        objectName: "Mouth_Frown_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_R_morphtarget400
        objectName: "Mouth_Smile_Sharp_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_Sharp_L_morphtarget399
        objectName: "Mouth_Smile_Sharp_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_R_morphtarget398
        objectName: "Mouth_Smile_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Smile_L_morphtarget397
        objectName: "Mouth_Smile_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_R_morphtarget396
        objectName: "Cheek_Puff_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Puff_L_morphtarget395
        objectName: "Cheek_Puff_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_R_morphtarget394
        objectName: "Cheek_Suck_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_R_morphtarget511
        objectName: "Eyelash_Upper_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_L_morphtarget521
        objectName: "Ear_Out_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_R_morphtarget520
        objectName: "Ear_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Down_L_morphtarget519
        objectName: "Ear_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_R_morphtarget518
        objectName: "Ear_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Up_L_morphtarget517
        objectName: "Ear_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_R_morphtarget516
        objectName: "Eyelash_Lower_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_R_morphtarget515
        objectName: "Eyelash_Lower_Up_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Down_L_morphtarget514
        objectName: "Eyelash_Lower_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Lower_Up_L_morphtarget513
        objectName: "Eyelash_Lower_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_R_morphtarget512
        objectName: "Eyelash_Upper_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: ear_Out_R_morphtarget522
        objectName: "Ear_Out_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Down_L_morphtarget510
        objectName: "Eyelash_Upper_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eyelash_Upper_Up_L_morphtarget509
        objectName: "Eyelash_Upper_Up_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Down_morphtarget508
        objectName: "Eye_R_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Down_morphtarget507
        objectName: "Eye_L_Look_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_Up_morphtarget506
        objectName: "Eye_R_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_Up_morphtarget505
        objectName: "Eye_L_Look_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_R_morphtarget504
        objectName: "Eye_R_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_R_morphtarget503
        objectName: "Eye_L_Look_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_R_Look_L_morphtarget502
        objectName: "Eye_R_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_L_Look_L_morphtarget501
        objectName: "Eye_L_Look_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_R_morphtarget532
        objectName: "Nose_Nostril_Down_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_R_morphtarget542
        objectName: "Cheek_Suck_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Suck_L_morphtarget541
        objectName: "Cheek_Suck_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_R_morphtarget540
        objectName: "Cheek_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: cheek_Raise_L_morphtarget539
        objectName: "Cheek_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Down_morphtarget538
        objectName: "Nose_Tip_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_Up_morphtarget537
        objectName: "Nose_Tip_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_R_morphtarget536
        objectName: "Nose_Tip_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Tip_L_morphtarget535
        objectName: "Nose_Tip_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_R_morphtarget534
        objectName: "Nose_Nostril_In_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_In_L_morphtarget533
        objectName: "Nose_Nostril_In_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_R_morphtarget500
        objectName: "Eye_Wide_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Down_L_morphtarget531
        objectName: "Nose_Nostril_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_R_morphtarget530
        objectName: "Nose_Crease_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Crease_L_morphtarget529
        objectName: "Nose_Crease_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_R_morphtarget528
        objectName: "Nose_Nostril_Dilate_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Dilate_L_morphtarget527
        objectName: "Nose_Nostril_Dilate_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_R_morphtarget526
        objectName: "Nose_Nostril_Raise_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Nostril_Raise_L_morphtarget525
        objectName: "Nose_Nostril_Raise_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_R_morphtarget524
        objectName: "Nose_Sneer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: nose_Sneer_L_morphtarget523
        objectName: "Nose_Sneer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_R_morphtarget468
        objectName: "Neck_Tighten_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Backward_morphtarget478
        objectName: "Head_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Forward_morphtarget477
        objectName: "Head_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_R_morphtarget476
        objectName: "Head_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_L_morphtarget475
        objectName: "Head_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_R_morphtarget474
        objectName: "Head_Tilt_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Tilt_L_morphtarget473
        objectName: "Head_Tilt_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_R_morphtarget472
        objectName: "Head_Turn_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_L_morphtarget471
        objectName: "Head_Turn_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Down_morphtarget470
        objectName: "Head_Turn_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: head_Turn_Up_morphtarget469
        objectName: "Head_Turn_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Open_morphtarget479
        objectName: "V_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Tighten_L_morphtarget467
        objectName: "Neck_Tighten_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Down_morphtarget466
        objectName: "Neck_Swallow_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: neck_Swallow_Up_morphtarget465
        objectName: "Neck_Swallow_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Down_morphtarget464
        objectName: "Jaw_Down"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Up_morphtarget463
        objectName: "Jaw_Up"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_R_morphtarget462
        objectName: "Jaw_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_L_morphtarget461
        objectName: "Jaw_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Backward_morphtarget460
        objectName: "Jaw_Backward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Forward_morphtarget459
        objectName: "Jaw_Forward"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: jaw_Open_morphtarget458
        objectName: "Jaw_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_L_morphtarget489
        objectName: "Brow_Raise_Outer_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Wide_L_morphtarget499
        objectName: "Eye_Wide_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_R_morphtarget498
        objectName: "Eye_Squint_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Squint_L_morphtarget497
        objectName: "Eye_Squint_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_R_morphtarget496
        objectName: "Eye_Blink_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: eye_Blink_L_morphtarget495
        objectName: "Eye_Blink_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_R_morphtarget494
        objectName: "Brow_Compress_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Compress_L_morphtarget493
        objectName: "Brow_Compress_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_R_morphtarget492
        objectName: "Brow_Drop_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Drop_L_morphtarget491
        objectName: "Brow_Drop_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Outer_R_morphtarget490
        objectName: "Brow_Raise_Outer_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: mouth_Funnel_Down_L_morphtarget715
        objectName: "Mouth_Funnel_Down_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_R_morphtarget488
        objectName: "Brow_Raise_Inner_R"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: brow_Raise_Inner_L_morphtarget487
        objectName: "Brow_Raise_Inner_L"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Lip_Open_morphtarget486
        objectName: "V_Lip_Open"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Affricate_morphtarget485
        objectName: "V_Affricate"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Wide_morphtarget484
        objectName: "V_Wide"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_morphtarget483
        objectName: "V_Tight"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Tight_O_morphtarget482
        objectName: "V_Tight_O"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Dental_Lip_morphtarget481
        objectName: "V_Dental_Lip"
        attributes: MorphTarget.Position
    }
    MorphTarget {
        id: v_Explosive_morphtarget480
        objectName: "V_Explosive"
        attributes: MorphTarget.Position
    }

    // Nodes:
    Node {
        id: armature
        objectName: "Armature"
        scale: Qt.vector3d(0.01, 0.01, 0.01)
        Model {
            id: cc_Base_Body
            objectName: "CC_Base_Body"
            source: "meshes/cc_Base_Body_mesh.mesh"
            skin: skin34
            materials: [
                std_Skin_Head_material,
                std_Skin_Body_material,
                std_Skin_Arm_material,
                std_Skin_Leg_material,
                std_Nails_material,
                std_Eyelash_material
            ]
            morphTargets: [
                v_Open_morphtarget35,
                v_Explosive_morphtarget36,
                v_Dental_Lip_morphtarget37,
                v_Tight_O_morphtarget38,
                v_Tight_morphtarget39,
                v_Wide_morphtarget40,
                v_Affricate_morphtarget41,
                v_Lip_Open_morphtarget42,
                brow_Raise_Inner_L_morphtarget43,
                brow_Raise_Inner_R_morphtarget44,
                brow_Raise_Outer_L_morphtarget45,
                brow_Raise_Outer_R_morphtarget46,
                brow_Drop_L_morphtarget47,
                brow_Drop_R_morphtarget48,
                brow_Compress_L_morphtarget49,
                brow_Compress_R_morphtarget50,
                eye_Blink_L_morphtarget51,
                eye_Blink_R_morphtarget52,
                eye_Squint_L_morphtarget53,
                eye_Squint_R_morphtarget54,
                eye_Wide_L_morphtarget55,
                eye_Wide_R_morphtarget56,
                eye_L_Look_L_morphtarget57,
                eye_R_Look_L_morphtarget58,
                eye_L_Look_R_morphtarget59,
                eye_R_Look_R_morphtarget60,
                eye_L_Look_Up_morphtarget61,
                eye_R_Look_Up_morphtarget62,
                eye_L_Look_Down_morphtarget63,
                eye_R_Look_Down_morphtarget64,
                eyelash_Upper_Up_L_morphtarget65,
                eyelash_Upper_Down_L_morphtarget66,
                eyelash_Upper_Up_R_morphtarget67,
                eyelash_Upper_Down_R_morphtarget68,
                eyelash_Lower_Up_L_morphtarget69,
                eyelash_Lower_Down_L_morphtarget70,
                eyelash_Lower_Up_R_morphtarget71,
                eyelash_Lower_Down_R_morphtarget72,
                ear_Up_L_morphtarget73,
                ear_Up_R_morphtarget74,
                ear_Down_L_morphtarget75,
                ear_Down_R_morphtarget76,
                ear_Out_L_morphtarget77,
                ear_Out_R_morphtarget78,
                nose_Sneer_L_morphtarget79,
                nose_Sneer_R_morphtarget80,
                nose_Nostril_Raise_L_morphtarget81,
                nose_Nostril_Raise_R_morphtarget82,
                nose_Nostril_Dilate_L_morphtarget83,
                nose_Nostril_Dilate_R_morphtarget84,
                nose_Crease_L_morphtarget85,
                nose_Crease_R_morphtarget86,
                nose_Nostril_Down_L_morphtarget87,
                nose_Nostril_Down_R_morphtarget88,
                nose_Nostril_In_L_morphtarget89,
                nose_Nostril_In_R_morphtarget90,
                nose_Tip_L_morphtarget91,
                nose_Tip_R_morphtarget92,
                nose_Tip_Up_morphtarget93,
                nose_Tip_Down_morphtarget94,
                cheek_Raise_L_morphtarget95,
                cheek_Raise_R_morphtarget96,
                cheek_Suck_L_morphtarget97,
                cheek_Suck_R_morphtarget98,
                cheek_Puff_L_morphtarget99,
                cheek_Puff_R_morphtarget100,
                mouth_Smile_L_morphtarget101,
                mouth_Smile_R_morphtarget102,
                mouth_Smile_Sharp_L_morphtarget103,
                mouth_Smile_Sharp_R_morphtarget104,
                mouth_Frown_L_morphtarget105,
                mouth_Frown_R_morphtarget106,
                mouth_Stretch_L_morphtarget107,
                mouth_Stretch_R_morphtarget108,
                mouth_Dimple_L_morphtarget109,
                mouth_Dimple_R_morphtarget110,
                mouth_Press_L_morphtarget111,
                mouth_Press_R_morphtarget112,
                mouth_Tighten_L_morphtarget113,
                mouth_Tighten_R_morphtarget114,
                mouth_Blow_L_morphtarget115,
                mouth_Blow_R_morphtarget116,
                mouth_Pucker_Up_L_morphtarget117,
                mouth_Pucker_Up_R_morphtarget118,
                mouth_Pucker_Down_L_morphtarget119,
                mouth_Pucker_Down_R_morphtarget120,
                mouth_Funnel_Up_L_morphtarget121,
                mouth_Funnel_Up_R_morphtarget122,
                mouth_Funnel_Down_L_morphtarget123,
                mouth_Funnel_Down_R_morphtarget124,
                mouth_Roll_In_Upper_L_morphtarget125,
                mouth_Roll_In_Upper_R_morphtarget126,
                mouth_Roll_In_Lower_L_morphtarget127,
                mouth_Roll_In_Lower_R_morphtarget128,
                mouth_Roll_Out_Upper_L_morphtarget129,
                mouth_Roll_Out_Upper_R_morphtarget130,
                mouth_Roll_Out_Lower_L_morphtarget131,
                mouth_Roll_Out_Lower_R_morphtarget132,
                mouth_Push_Upper_L_morphtarget133,
                mouth_Push_Upper_R_morphtarget134,
                mouth_Push_Lower_L_morphtarget135,
                mouth_Push_Lower_R_morphtarget136,
                mouth_Pull_Upper_L_morphtarget137,
                mouth_Pull_Upper_R_morphtarget138,
                mouth_Pull_Lower_L_morphtarget139,
                mouth_Pull_Lower_R_morphtarget140,
                mouth_Up_morphtarget141,
                mouth_Down_morphtarget142,
                mouth_L_morphtarget143,
                mouth_R_morphtarget144,
                mouth_Upper_L_morphtarget145,
                mouth_Upper_R_morphtarget146,
                mouth_Lower_L_morphtarget147,
                mouth_Lower_R_morphtarget148,
                mouth_Shrug_Upper_morphtarget149,
                mouth_Shrug_Lower_morphtarget150,
                mouth_Drop_Upper_morphtarget151,
                mouth_Drop_Lower_morphtarget152,
                mouth_Up_Upper_L_morphtarget153,
                mouth_Up_Upper_R_morphtarget154,
                mouth_Down_Lower_L_morphtarget155,
                mouth_Down_Lower_R_morphtarget156,
                mouth_Chin_Up_morphtarget157,
                mouth_Close_morphtarget158,
                mouth_Contract_morphtarget159,
                tongue_Bulge_L_morphtarget160,
                tongue_Bulge_R_morphtarget161,
                jaw_Open_morphtarget162,
                jaw_Forward_morphtarget163,
                jaw_Backward_morphtarget164,
                jaw_L_morphtarget165,
                jaw_R_morphtarget166,
                jaw_Up_morphtarget167,
                jaw_Down_morphtarget168,
                neck_Swallow_Up_morphtarget169,
                neck_Swallow_Down_morphtarget170,
                neck_Tighten_L_morphtarget171,
                neck_Tighten_R_morphtarget172,
                head_Turn_Up_morphtarget173,
                head_Turn_Down_morphtarget174,
                head_Turn_L_morphtarget175,
                head_Turn_R_morphtarget176,
                head_Tilt_L_morphtarget177,
                head_Tilt_R_morphtarget178,
                head_L_morphtarget179,
                head_R_morphtarget180,
                head_Forward_morphtarget181,
                head_Backward_morphtarget182,
                v_Open_morphtarget183,
                v_Explosive_morphtarget184,
                v_Dental_Lip_morphtarget185,
                v_Tight_O_morphtarget186,
                v_Tight_morphtarget187,
                v_Wide_morphtarget188,
                v_Affricate_morphtarget189,
                v_Lip_Open_morphtarget190,
                brow_Raise_Inner_L_morphtarget191,
                brow_Raise_Inner_R_morphtarget192,
                brow_Raise_Outer_L_morphtarget193,
                brow_Raise_Outer_R_morphtarget194,
                brow_Drop_L_morphtarget195,
                brow_Drop_R_morphtarget196,
                brow_Compress_L_morphtarget197,
                brow_Compress_R_morphtarget198,
                eye_Blink_L_morphtarget199,
                eye_Blink_R_morphtarget200,
                eye_Squint_L_morphtarget201,
                eye_Squint_R_morphtarget202,
                eye_Wide_L_morphtarget203,
                eye_Wide_R_morphtarget204,
                eye_L_Look_L_morphtarget205,
                eye_R_Look_L_morphtarget206,
                eye_L_Look_R_morphtarget207,
                eye_R_Look_R_morphtarget208,
                eye_L_Look_Up_morphtarget209,
                eye_R_Look_Up_morphtarget210,
                eye_L_Look_Down_morphtarget211,
                eye_R_Look_Down_morphtarget212,
                eyelash_Upper_Up_L_morphtarget213,
                eyelash_Upper_Down_L_morphtarget214,
                eyelash_Upper_Up_R_morphtarget215,
                eyelash_Upper_Down_R_morphtarget216,
                eyelash_Lower_Up_L_morphtarget217,
                eyelash_Lower_Down_L_morphtarget218,
                eyelash_Lower_Up_R_morphtarget219,
                eyelash_Lower_Down_R_morphtarget220,
                ear_Up_L_morphtarget221,
                ear_Up_R_morphtarget222,
                ear_Down_L_morphtarget223,
                ear_Down_R_morphtarget224,
                ear_Out_L_morphtarget225,
                ear_Out_R_morphtarget226,
                nose_Sneer_L_morphtarget227,
                nose_Sneer_R_morphtarget228,
                nose_Nostril_Raise_L_morphtarget229,
                nose_Nostril_Raise_R_morphtarget230,
                nose_Nostril_Dilate_L_morphtarget231,
                nose_Nostril_Dilate_R_morphtarget232,
                nose_Crease_L_morphtarget233,
                nose_Crease_R_morphtarget234,
                nose_Nostril_Down_L_morphtarget235,
                nose_Nostril_Down_R_morphtarget236,
                nose_Nostril_In_L_morphtarget237,
                nose_Nostril_In_R_morphtarget238,
                nose_Tip_L_morphtarget239,
                nose_Tip_R_morphtarget240,
                nose_Tip_Up_morphtarget241,
                nose_Tip_Down_morphtarget242,
                cheek_Raise_L_morphtarget243,
                cheek_Raise_R_morphtarget244,
                cheek_Suck_L_morphtarget245,
                cheek_Suck_R_morphtarget246,
                cheek_Puff_L_morphtarget247,
                cheek_Puff_R_morphtarget248,
                mouth_Smile_L_morphtarget249,
                mouth_Smile_R_morphtarget250,
                mouth_Smile_Sharp_L_morphtarget251,
                mouth_Smile_Sharp_R_morphtarget252,
                mouth_Frown_L_morphtarget253,
                mouth_Frown_R_morphtarget254,
                mouth_Stretch_L_morphtarget255,
                mouth_Stretch_R_morphtarget256,
                mouth_Dimple_L_morphtarget257,
                mouth_Dimple_R_morphtarget258,
                mouth_Press_L_morphtarget259,
                mouth_Press_R_morphtarget260,
                mouth_Tighten_L_morphtarget261,
                mouth_Tighten_R_morphtarget262,
                mouth_Blow_L_morphtarget263,
                mouth_Blow_R_morphtarget264,
                mouth_Pucker_Up_L_morphtarget265,
                mouth_Pucker_Up_R_morphtarget266,
                mouth_Pucker_Down_L_morphtarget267,
                mouth_Pucker_Down_R_morphtarget268,
                mouth_Funnel_Up_L_morphtarget269,
                mouth_Funnel_Up_R_morphtarget270,
                mouth_Funnel_Down_L_morphtarget271,
                mouth_Funnel_Down_R_morphtarget272,
                mouth_Roll_In_Upper_L_morphtarget273,
                mouth_Roll_In_Upper_R_morphtarget274,
                mouth_Roll_In_Lower_L_morphtarget275,
                mouth_Roll_In_Lower_R_morphtarget276,
                mouth_Roll_Out_Upper_L_morphtarget277,
                mouth_Roll_Out_Upper_R_morphtarget278,
                mouth_Roll_Out_Lower_L_morphtarget279,
                mouth_Roll_Out_Lower_R_morphtarget280,
                mouth_Push_Upper_L_morphtarget281,
                mouth_Push_Upper_R_morphtarget282,
                mouth_Push_Lower_L_morphtarget283,
                mouth_Push_Lower_R_morphtarget284,
                mouth_Pull_Upper_L_morphtarget285,
                mouth_Pull_Upper_R_morphtarget286,
                mouth_Pull_Lower_L_morphtarget287,
                mouth_Pull_Lower_R_morphtarget288,
                mouth_Up_morphtarget289,
                mouth_Down_morphtarget290,
                mouth_L_morphtarget291,
                mouth_R_morphtarget292,
                mouth_Upper_L_morphtarget293,
                mouth_Upper_R_morphtarget294,
                mouth_Lower_L_morphtarget295,
                mouth_Lower_R_morphtarget296,
                mouth_Shrug_Upper_morphtarget297,
                mouth_Shrug_Lower_morphtarget298,
                mouth_Drop_Upper_morphtarget299,
                mouth_Drop_Lower_morphtarget300,
                mouth_Up_Upper_L_morphtarget301,
                mouth_Up_Upper_R_morphtarget302,
                mouth_Down_Lower_L_morphtarget303,
                mouth_Down_Lower_R_morphtarget304,
                mouth_Chin_Up_morphtarget305,
                mouth_Close_morphtarget306,
                mouth_Contract_morphtarget307,
                tongue_Bulge_L_morphtarget308,
                tongue_Bulge_R_morphtarget309,
                jaw_Open_morphtarget310,
                jaw_Forward_morphtarget311,
                jaw_Backward_morphtarget312,
                jaw_L_morphtarget313,
                jaw_R_morphtarget314,
                jaw_Up_morphtarget315,
                jaw_Down_morphtarget316,
                neck_Swallow_Up_morphtarget317,
                neck_Swallow_Down_morphtarget318,
                neck_Tighten_L_morphtarget319,
                neck_Tighten_R_morphtarget320,
                head_Turn_Up_morphtarget321,
                head_Turn_Down_morphtarget322,
                head_Turn_L_morphtarget323,
                head_Turn_R_morphtarget324,
                head_Tilt_L_morphtarget325,
                head_Tilt_R_morphtarget326,
                head_L_morphtarget327,
                head_R_morphtarget328,
                head_Forward_morphtarget329,
                head_Backward_morphtarget330,
                v_Open_morphtarget331,
                v_Explosive_morphtarget332,
                v_Dental_Lip_morphtarget333,
                v_Tight_O_morphtarget334,
                v_Tight_morphtarget335,
                v_Wide_morphtarget336,
                v_Affricate_morphtarget337,
                v_Lip_Open_morphtarget338,
                brow_Raise_Inner_L_morphtarget339,
                brow_Raise_Inner_R_morphtarget340,
                brow_Raise_Outer_L_morphtarget341,
                brow_Raise_Outer_R_morphtarget342,
                brow_Drop_L_morphtarget343,
                brow_Drop_R_morphtarget344,
                brow_Compress_L_morphtarget345,
                brow_Compress_R_morphtarget346,
                eye_Blink_L_morphtarget347,
                eye_Blink_R_morphtarget348,
                eye_Squint_L_morphtarget349,
                eye_Squint_R_morphtarget350,
                eye_Wide_L_morphtarget351,
                eye_Wide_R_morphtarget352,
                eye_L_Look_L_morphtarget353,
                eye_R_Look_L_morphtarget354,
                eye_L_Look_R_morphtarget355,
                eye_R_Look_R_morphtarget356,
                eye_L_Look_Up_morphtarget357,
                eye_R_Look_Up_morphtarget358,
                eye_L_Look_Down_morphtarget359,
                eye_R_Look_Down_morphtarget360,
                eyelash_Upper_Up_L_morphtarget361,
                eyelash_Upper_Down_L_morphtarget362,
                eyelash_Upper_Up_R_morphtarget363,
                eyelash_Upper_Down_R_morphtarget364,
                eyelash_Lower_Up_L_morphtarget365,
                eyelash_Lower_Down_L_morphtarget366,
                eyelash_Lower_Up_R_morphtarget367,
                eyelash_Lower_Down_R_morphtarget368,
                ear_Up_L_morphtarget369,
                ear_Up_R_morphtarget370,
                ear_Down_L_morphtarget371,
                ear_Down_R_morphtarget372,
                ear_Out_L_morphtarget373,
                ear_Out_R_morphtarget374,
                nose_Sneer_L_morphtarget375,
                nose_Sneer_R_morphtarget376,
                nose_Nostril_Raise_L_morphtarget377,
                nose_Nostril_Raise_R_morphtarget378,
                nose_Nostril_Dilate_L_morphtarget379,
                nose_Nostril_Dilate_R_morphtarget380,
                nose_Crease_L_morphtarget381,
                nose_Crease_R_morphtarget382,
                nose_Nostril_Down_L_morphtarget383,
                nose_Nostril_Down_R_morphtarget384,
                nose_Nostril_In_L_morphtarget385,
                nose_Nostril_In_R_morphtarget386,
                nose_Tip_L_morphtarget387,
                nose_Tip_R_morphtarget388,
                nose_Tip_Up_morphtarget389,
                nose_Tip_Down_morphtarget390,
                cheek_Raise_L_morphtarget391,
                cheek_Raise_R_morphtarget392,
                cheek_Suck_L_morphtarget393,
                cheek_Suck_R_morphtarget394,
                cheek_Puff_L_morphtarget395,
                cheek_Puff_R_morphtarget396,
                mouth_Smile_L_morphtarget397,
                mouth_Smile_R_morphtarget398,
                mouth_Smile_Sharp_L_morphtarget399,
                mouth_Smile_Sharp_R_morphtarget400,
                mouth_Frown_L_morphtarget401,
                mouth_Frown_R_morphtarget402,
                mouth_Stretch_L_morphtarget403,
                mouth_Stretch_R_morphtarget404,
                mouth_Dimple_L_morphtarget405,
                mouth_Dimple_R_morphtarget406,
                mouth_Press_L_morphtarget407,
                mouth_Press_R_morphtarget408,
                mouth_Tighten_L_morphtarget409,
                mouth_Tighten_R_morphtarget410,
                mouth_Blow_L_morphtarget411,
                mouth_Blow_R_morphtarget412,
                mouth_Pucker_Up_L_morphtarget413,
                mouth_Pucker_Up_R_morphtarget414,
                mouth_Pucker_Down_L_morphtarget415,
                mouth_Pucker_Down_R_morphtarget416,
                mouth_Funnel_Up_L_morphtarget417,
                mouth_Funnel_Up_R_morphtarget418,
                mouth_Funnel_Down_L_morphtarget419,
                mouth_Funnel_Down_R_morphtarget420,
                mouth_Roll_In_Upper_L_morphtarget421,
                mouth_Roll_In_Upper_R_morphtarget422,
                mouth_Roll_In_Lower_L_morphtarget423,
                mouth_Roll_In_Lower_R_morphtarget424,
                mouth_Roll_Out_Upper_L_morphtarget425,
                mouth_Roll_Out_Upper_R_morphtarget426,
                mouth_Roll_Out_Lower_L_morphtarget427,
                mouth_Roll_Out_Lower_R_morphtarget428,
                mouth_Push_Upper_L_morphtarget429,
                mouth_Push_Upper_R_morphtarget430,
                mouth_Push_Lower_L_morphtarget431,
                mouth_Push_Lower_R_morphtarget432,
                mouth_Pull_Upper_L_morphtarget433,
                mouth_Pull_Upper_R_morphtarget434,
                mouth_Pull_Lower_L_morphtarget435,
                mouth_Pull_Lower_R_morphtarget436,
                mouth_Up_morphtarget437,
                mouth_Down_morphtarget438,
                mouth_L_morphtarget439,
                mouth_R_morphtarget440,
                mouth_Upper_L_morphtarget441,
                mouth_Upper_R_morphtarget442,
                mouth_Lower_L_morphtarget443,
                mouth_Lower_R_morphtarget444,
                mouth_Shrug_Upper_morphtarget445,
                mouth_Shrug_Lower_morphtarget446,
                mouth_Drop_Upper_morphtarget447,
                mouth_Drop_Lower_morphtarget448,
                mouth_Up_Upper_L_morphtarget449,
                mouth_Up_Upper_R_morphtarget450,
                mouth_Down_Lower_L_morphtarget451,
                mouth_Down_Lower_R_morphtarget452,
                mouth_Chin_Up_morphtarget453,
                mouth_Close_morphtarget454,
                mouth_Contract_morphtarget455,
                tongue_Bulge_L_morphtarget456,
                tongue_Bulge_R_morphtarget457,
                jaw_Open_morphtarget458,
                jaw_Forward_morphtarget459,
                jaw_Backward_morphtarget460,
                jaw_L_morphtarget461,
                jaw_R_morphtarget462,
                jaw_Up_morphtarget463,
                jaw_Down_morphtarget464,
                neck_Swallow_Up_morphtarget465,
                neck_Swallow_Down_morphtarget466,
                neck_Tighten_L_morphtarget467,
                neck_Tighten_R_morphtarget468,
                head_Turn_Up_morphtarget469,
                head_Turn_Down_morphtarget470,
                head_Turn_L_morphtarget471,
                head_Turn_R_morphtarget472,
                head_Tilt_L_morphtarget473,
                head_Tilt_R_morphtarget474,
                head_L_morphtarget475,
                head_R_morphtarget476,
                head_Forward_morphtarget477,
                head_Backward_morphtarget478,
                v_Open_morphtarget479,
                v_Explosive_morphtarget480,
                v_Dental_Lip_morphtarget481,
                v_Tight_O_morphtarget482,
                v_Tight_morphtarget483,
                v_Wide_morphtarget484,
                v_Affricate_morphtarget485,
                v_Lip_Open_morphtarget486,
                brow_Raise_Inner_L_morphtarget487,
                brow_Raise_Inner_R_morphtarget488,
                brow_Raise_Outer_L_morphtarget489,
                brow_Raise_Outer_R_morphtarget490,
                brow_Drop_L_morphtarget491,
                brow_Drop_R_morphtarget492,
                brow_Compress_L_morphtarget493,
                brow_Compress_R_morphtarget494,
                eye_Blink_L_morphtarget495,
                eye_Blink_R_morphtarget496,
                eye_Squint_L_morphtarget497,
                eye_Squint_R_morphtarget498,
                eye_Wide_L_morphtarget499,
                eye_Wide_R_morphtarget500,
                eye_L_Look_L_morphtarget501,
                eye_R_Look_L_morphtarget502,
                eye_L_Look_R_morphtarget503,
                eye_R_Look_R_morphtarget504,
                eye_L_Look_Up_morphtarget505,
                eye_R_Look_Up_morphtarget506,
                eye_L_Look_Down_morphtarget507,
                eye_R_Look_Down_morphtarget508,
                eyelash_Upper_Up_L_morphtarget509,
                eyelash_Upper_Down_L_morphtarget510,
                eyelash_Upper_Up_R_morphtarget511,
                eyelash_Upper_Down_R_morphtarget512,
                eyelash_Lower_Up_L_morphtarget513,
                eyelash_Lower_Down_L_morphtarget514,
                eyelash_Lower_Up_R_morphtarget515,
                eyelash_Lower_Down_R_morphtarget516,
                ear_Up_L_morphtarget517,
                ear_Up_R_morphtarget518,
                ear_Down_L_morphtarget519,
                ear_Down_R_morphtarget520,
                ear_Out_L_morphtarget521,
                ear_Out_R_morphtarget522,
                nose_Sneer_L_morphtarget523,
                nose_Sneer_R_morphtarget524,
                nose_Nostril_Raise_L_morphtarget525,
                nose_Nostril_Raise_R_morphtarget526,
                nose_Nostril_Dilate_L_morphtarget527,
                nose_Nostril_Dilate_R_morphtarget528,
                nose_Crease_L_morphtarget529,
                nose_Crease_R_morphtarget530,
                nose_Nostril_Down_L_morphtarget531,
                nose_Nostril_Down_R_morphtarget532,
                nose_Nostril_In_L_morphtarget533,
                nose_Nostril_In_R_morphtarget534,
                nose_Tip_L_morphtarget535,
                nose_Tip_R_morphtarget536,
                nose_Tip_Up_morphtarget537,
                nose_Tip_Down_morphtarget538,
                cheek_Raise_L_morphtarget539,
                cheek_Raise_R_morphtarget540,
                cheek_Suck_L_morphtarget541,
                cheek_Suck_R_morphtarget542,
                cheek_Puff_L_morphtarget543,
                cheek_Puff_R_morphtarget544,
                mouth_Smile_L_morphtarget545,
                mouth_Smile_R_morphtarget546,
                mouth_Smile_Sharp_L_morphtarget547,
                mouth_Smile_Sharp_R_morphtarget548,
                mouth_Frown_L_morphtarget549,
                mouth_Frown_R_morphtarget550,
                mouth_Stretch_L_morphtarget551,
                mouth_Stretch_R_morphtarget552,
                mouth_Dimple_L_morphtarget553,
                mouth_Dimple_R_morphtarget554,
                mouth_Press_L_morphtarget555,
                mouth_Press_R_morphtarget556,
                mouth_Tighten_L_morphtarget557,
                mouth_Tighten_R_morphtarget558,
                mouth_Blow_L_morphtarget559,
                mouth_Blow_R_morphtarget560,
                mouth_Pucker_Up_L_morphtarget561,
                mouth_Pucker_Up_R_morphtarget562,
                mouth_Pucker_Down_L_morphtarget563,
                mouth_Pucker_Down_R_morphtarget564,
                mouth_Funnel_Up_L_morphtarget565,
                mouth_Funnel_Up_R_morphtarget566,
                mouth_Funnel_Down_L_morphtarget567,
                mouth_Funnel_Down_R_morphtarget568,
                mouth_Roll_In_Upper_L_morphtarget569,
                mouth_Roll_In_Upper_R_morphtarget570,
                mouth_Roll_In_Lower_L_morphtarget571,
                mouth_Roll_In_Lower_R_morphtarget572,
                mouth_Roll_Out_Upper_L_morphtarget573,
                mouth_Roll_Out_Upper_R_morphtarget574,
                mouth_Roll_Out_Lower_L_morphtarget575,
                mouth_Roll_Out_Lower_R_morphtarget576,
                mouth_Push_Upper_L_morphtarget577,
                mouth_Push_Upper_R_morphtarget578,
                mouth_Push_Lower_L_morphtarget579,
                mouth_Push_Lower_R_morphtarget580,
                mouth_Pull_Upper_L_morphtarget581,
                mouth_Pull_Upper_R_morphtarget582,
                mouth_Pull_Lower_L_morphtarget583,
                mouth_Pull_Lower_R_morphtarget584,
                mouth_Up_morphtarget585,
                mouth_Down_morphtarget586,
                mouth_L_morphtarget587,
                mouth_R_morphtarget588,
                mouth_Upper_L_morphtarget589,
                mouth_Upper_R_morphtarget590,
                mouth_Lower_L_morphtarget591,
                mouth_Lower_R_morphtarget592,
                mouth_Shrug_Upper_morphtarget593,
                mouth_Shrug_Lower_morphtarget594,
                mouth_Drop_Upper_morphtarget595,
                mouth_Drop_Lower_morphtarget596,
                mouth_Up_Upper_L_morphtarget597,
                mouth_Up_Upper_R_morphtarget598,
                mouth_Down_Lower_L_morphtarget599,
                mouth_Down_Lower_R_morphtarget600,
                mouth_Chin_Up_morphtarget601,
                mouth_Close_morphtarget602,
                mouth_Contract_morphtarget603,
                tongue_Bulge_L_morphtarget604,
                tongue_Bulge_R_morphtarget605,
                jaw_Open_morphtarget606,
                jaw_Forward_morphtarget607,
                jaw_Backward_morphtarget608,
                jaw_L_morphtarget609,
                jaw_R_morphtarget610,
                jaw_Up_morphtarget611,
                jaw_Down_morphtarget612,
                neck_Swallow_Up_morphtarget613,
                neck_Swallow_Down_morphtarget614,
                neck_Tighten_L_morphtarget615,
                neck_Tighten_R_morphtarget616,
                head_Turn_Up_morphtarget617,
                head_Turn_Down_morphtarget618,
                head_Turn_L_morphtarget619,
                head_Turn_R_morphtarget620,
                head_Tilt_L_morphtarget621,
                head_Tilt_R_morphtarget622,
                head_L_morphtarget623,
                head_R_morphtarget624,
                head_Forward_morphtarget625,
                head_Backward_morphtarget626,
                v_Open_morphtarget627,
                v_Explosive_morphtarget628,
                v_Dental_Lip_morphtarget629,
                v_Tight_O_morphtarget630,
                v_Tight_morphtarget631,
                v_Wide_morphtarget632,
                v_Affricate_morphtarget633,
                v_Lip_Open_morphtarget634,
                brow_Raise_Inner_L_morphtarget635,
                brow_Raise_Inner_R_morphtarget636,
                brow_Raise_Outer_L_morphtarget637,
                brow_Raise_Outer_R_morphtarget638,
                brow_Drop_L_morphtarget639,
                brow_Drop_R_morphtarget640,
                brow_Compress_L_morphtarget641,
                brow_Compress_R_morphtarget642,
                eye_Blink_L_morphtarget643,
                eye_Blink_R_morphtarget644,
                eye_Squint_L_morphtarget645,
                eye_Squint_R_morphtarget646,
                eye_Wide_L_morphtarget647,
                eye_Wide_R_morphtarget648,
                eye_L_Look_L_morphtarget649,
                eye_R_Look_L_morphtarget650,
                eye_L_Look_R_morphtarget651,
                eye_R_Look_R_morphtarget652,
                eye_L_Look_Up_morphtarget653,
                eye_R_Look_Up_morphtarget654,
                eye_L_Look_Down_morphtarget655,
                eye_R_Look_Down_morphtarget656,
                eyelash_Upper_Up_L_morphtarget657,
                eyelash_Upper_Down_L_morphtarget658,
                eyelash_Upper_Up_R_morphtarget659,
                eyelash_Upper_Down_R_morphtarget660,
                eyelash_Lower_Up_L_morphtarget661,
                eyelash_Lower_Down_L_morphtarget662,
                eyelash_Lower_Up_R_morphtarget663,
                eyelash_Lower_Down_R_morphtarget664,
                ear_Up_L_morphtarget665,
                ear_Up_R_morphtarget666,
                ear_Down_L_morphtarget667,
                ear_Down_R_morphtarget668,
                ear_Out_L_morphtarget669,
                ear_Out_R_morphtarget670,
                nose_Sneer_L_morphtarget671,
                nose_Sneer_R_morphtarget672,
                nose_Nostril_Raise_L_morphtarget673,
                nose_Nostril_Raise_R_morphtarget674,
                nose_Nostril_Dilate_L_morphtarget675,
                nose_Nostril_Dilate_R_morphtarget676,
                nose_Crease_L_morphtarget677,
                nose_Crease_R_morphtarget678,
                nose_Nostril_Down_L_morphtarget679,
                nose_Nostril_Down_R_morphtarget680,
                nose_Nostril_In_L_morphtarget681,
                nose_Nostril_In_R_morphtarget682,
                nose_Tip_L_morphtarget683,
                nose_Tip_R_morphtarget684,
                nose_Tip_Up_morphtarget685,
                nose_Tip_Down_morphtarget686,
                cheek_Raise_L_morphtarget687,
                cheek_Raise_R_morphtarget688,
                cheek_Suck_L_morphtarget689,
                cheek_Suck_R_morphtarget690,
                cheek_Puff_L_morphtarget691,
                cheek_Puff_R_morphtarget692,
                mouth_Smile_L_morphtarget693,
                mouth_Smile_R_morphtarget694,
                mouth_Smile_Sharp_L_morphtarget695,
                mouth_Smile_Sharp_R_morphtarget696,
                mouth_Frown_L_morphtarget697,
                mouth_Frown_R_morphtarget698,
                mouth_Stretch_L_morphtarget699,
                mouth_Stretch_R_morphtarget700,
                mouth_Dimple_L_morphtarget701,
                mouth_Dimple_R_morphtarget702,
                mouth_Press_L_morphtarget703,
                mouth_Press_R_morphtarget704,
                mouth_Tighten_L_morphtarget705,
                mouth_Tighten_R_morphtarget706,
                mouth_Blow_L_morphtarget707,
                mouth_Blow_R_morphtarget708,
                mouth_Pucker_Up_L_morphtarget709,
                mouth_Pucker_Up_R_morphtarget710,
                mouth_Pucker_Down_L_morphtarget711,
                mouth_Pucker_Down_R_morphtarget712,
                mouth_Funnel_Up_L_morphtarget713,
                mouth_Funnel_Up_R_morphtarget714,
                mouth_Funnel_Down_L_morphtarget715,
                mouth_Funnel_Down_R_morphtarget,
                mouth_Roll_In_Upper_L_morphtarget,
                mouth_Roll_In_Upper_R_morphtarget,
                mouth_Roll_In_Lower_L_morphtarget,
                mouth_Roll_In_Lower_R_morphtarget,
                mouth_Roll_Out_Upper_L_morphtarget,
                mouth_Roll_Out_Upper_R_morphtarget,
                mouth_Roll_Out_Lower_L_morphtarget,
                mouth_Roll_Out_Lower_R_morphtarget,
                mouth_Push_Upper_L_morphtarget,
                mouth_Push_Upper_R_morphtarget,
                mouth_Push_Lower_L_morphtarget,
                mouth_Push_Lower_R_morphtarget,
                mouth_Pull_Upper_L_morphtarget,
                mouth_Pull_Upper_R_morphtarget,
                mouth_Pull_Lower_L_morphtarget,
                mouth_Pull_Lower_R_morphtarget,
                mouth_Up_morphtarget,
                mouth_Down_morphtarget,
                mouth_L_morphtarget735,
                mouth_R_morphtarget,
                mouth_Upper_L_morphtarget,
                mouth_Upper_R_morphtarget,
                mouth_Lower_L_morphtarget739,
                mouth_Lower_R_morphtarget740,
                mouth_Shrug_Upper_morphtarget741,
                mouth_Shrug_Lower_morphtarget742,
                mouth_Drop_Upper_morphtarget743,
                mouth_Drop_Lower_morphtarget744,
                mouth_Up_Upper_L_morphtarget745,
                mouth_Up_Upper_R_morphtarget746,
                mouth_Down_Lower_L_morphtarget747,
                mouth_Down_Lower_R_morphtarget748,
                mouth_Chin_Up_morphtarget749,
                mouth_Close_morphtarget750,
                mouth_Contract_morphtarget751,
                tongue_Bulge_L_morphtarget752,
                tongue_Bulge_R_morphtarget753,
                jaw_Open_morphtarget754,
                jaw_Forward_morphtarget755,
                jaw_Backward_morphtarget756,
                jaw_L_morphtarget757,
                jaw_R_morphtarget758,
                jaw_Up_morphtarget759,
                jaw_Down_morphtarget760,
                neck_Swallow_Up_morphtarget761,
                neck_Swallow_Down_morphtarget762,
                neck_Tighten_L_morphtarget763,
                neck_Tighten_R_morphtarget764,
                head_Turn_Up_morphtarget765,
                head_Turn_Down_morphtarget766,
                head_Turn_L_morphtarget767,
                head_Turn_R_morphtarget768,
                head_Tilt_L_morphtarget769,
                head_Tilt_R_morphtarget770,
                head_L_morphtarget771,
                head_R_morphtarget772,
                head_Forward_morphtarget773,
                head_Backward_morphtarget774,
                v_Open_morphtarget775,
                v_Explosive_morphtarget776,
                v_Dental_Lip_morphtarget777,
                v_Tight_O_morphtarget778,
                v_Tight_morphtarget779,
                v_Wide_morphtarget780,
                v_Affricate_morphtarget781,
                v_Lip_Open_morphtarget782,
                brow_Raise_Inner_L_morphtarget783,
                brow_Raise_Inner_R_morphtarget784,
                brow_Raise_Outer_L_morphtarget785,
                brow_Raise_Outer_R_morphtarget786,
                brow_Drop_L_morphtarget787,
                brow_Drop_R_morphtarget788,
                brow_Compress_L_morphtarget789,
                brow_Compress_R_morphtarget790,
                eye_Blink_L_morphtarget791,
                eye_Blink_R_morphtarget792,
                eye_Squint_L_morphtarget793,
                eye_Squint_R_morphtarget794,
                eye_Wide_L_morphtarget795,
                eye_Wide_R_morphtarget796,
                eye_L_Look_L_morphtarget797,
                eye_R_Look_L_morphtarget798,
                eye_L_Look_R_morphtarget799,
                eye_R_Look_R_morphtarget800,
                eye_L_Look_Up_morphtarget801,
                eye_R_Look_Up_morphtarget802,
                eye_L_Look_Down_morphtarget803,
                eye_R_Look_Down_morphtarget804,
                eyelash_Upper_Up_L_morphtarget805,
                eyelash_Upper_Down_L_morphtarget806,
                eyelash_Upper_Up_R_morphtarget807,
                eyelash_Upper_Down_R_morphtarget808,
                eyelash_Lower_Up_L_morphtarget809,
                eyelash_Lower_Down_L_morphtarget810,
                eyelash_Lower_Up_R_morphtarget,
                eyelash_Lower_Down_R_morphtarget,
                ear_Up_L_morphtarget,
                ear_Up_R_morphtarget,
                ear_Down_L_morphtarget,
                ear_Down_R_morphtarget,
                ear_Out_L_morphtarget,
                ear_Out_R_morphtarget,
                nose_Sneer_L_morphtarget,
                nose_Sneer_R_morphtarget,
                nose_Nostril_Raise_L_morphtarget,
                nose_Nostril_Raise_R_morphtarget,
                nose_Nostril_Dilate_L_morphtarget,
                nose_Nostril_Dilate_R_morphtarget,
                nose_Crease_L_morphtarget,
                nose_Crease_R_morphtarget,
                nose_Nostril_Down_L_morphtarget,
                nose_Nostril_Down_R_morphtarget,
                nose_Nostril_In_L_morphtarget,
                nose_Nostril_In_R_morphtarget,
                nose_Tip_L_morphtarget,
                nose_Tip_R_morphtarget,
                nose_Tip_Up_morphtarget,
                nose_Tip_Down_morphtarget,
                cheek_Raise_L_morphtarget,
                cheek_Raise_R_morphtarget,
                cheek_Suck_L_morphtarget,
                cheek_Suck_R_morphtarget,
                cheek_Puff_L_morphtarget,
                cheek_Puff_R_morphtarget,
                mouth_Smile_L_morphtarget,
                mouth_Smile_R_morphtarget,
                mouth_Smile_Sharp_L_morphtarget,
                mouth_Smile_Sharp_R_morphtarget,
                mouth_Frown_L_morphtarget,
                mouth_Frown_R_morphtarget,
                mouth_Stretch_L_morphtarget,
                mouth_Stretch_R_morphtarget,
                mouth_Dimple_L_morphtarget,
                mouth_Dimple_R_morphtarget,
                mouth_Press_L_morphtarget,
                mouth_Press_R_morphtarget,
                mouth_Tighten_L_morphtarget,
                mouth_Tighten_R_morphtarget,
                mouth_Blow_L_morphtarget,
                mouth_Blow_R_morphtarget,
                mouth_Pucker_Up_L_morphtarget,
                mouth_Pucker_Up_R_morphtarget,
                mouth_Pucker_Down_L_morphtarget,
                mouth_Pucker_Down_R_morphtarget,
                mouth_Funnel_Up_L_morphtarget,
                mouth_Funnel_Up_R_morphtarget,
                mouth_Funnel_Down_L_morphtarget,
                mouth_Funnel_Down_R_morphtarget864,
                mouth_Roll_In_Upper_L_morphtarget865,
                mouth_Roll_In_Upper_R_morphtarget866,
                mouth_Roll_In_Lower_L_morphtarget867,
                mouth_Roll_In_Lower_R_morphtarget868,
                mouth_Roll_Out_Upper_L_morphtarget869,
                mouth_Roll_Out_Upper_R_morphtarget870,
                mouth_Roll_Out_Lower_L_morphtarget871,
                mouth_Roll_Out_Lower_R_morphtarget872,
                mouth_Push_Upper_L_morphtarget873,
                mouth_Push_Upper_R_morphtarget874,
                mouth_Push_Lower_L_morphtarget875,
                mouth_Push_Lower_R_morphtarget876,
                mouth_Pull_Upper_L_morphtarget877,
                mouth_Pull_Upper_R_morphtarget878,
                mouth_Pull_Lower_L_morphtarget879,
                mouth_Pull_Lower_R_morphtarget880,
                mouth_Up_morphtarget881,
                mouth_Down_morphtarget882,
                mouth_L_morphtarget883,
                mouth_R_morphtarget884,
                mouth_Upper_L_morphtarget885,
                mouth_Upper_R_morphtarget886,
                mouth_Lower_L_morphtarget,
                mouth_Lower_R_morphtarget,
                mouth_Shrug_Upper_morphtarget,
                mouth_Shrug_Lower_morphtarget,
                mouth_Drop_Upper_morphtarget,
                mouth_Drop_Lower_morphtarget,
                mouth_Up_Upper_L_morphtarget,
                mouth_Up_Upper_R_morphtarget,
                mouth_Down_Lower_L_morphtarget,
                mouth_Down_Lower_R_morphtarget,
                mouth_Chin_Up_morphtarget,
                mouth_Close_morphtarget,
                mouth_Contract_morphtarget899,
                tongue_Bulge_L_morphtarget,
                tongue_Bulge_R_morphtarget,
                jaw_Open_morphtarget,
                jaw_Forward_morphtarget,
                jaw_Backward_morphtarget,
                jaw_L_morphtarget,
                jaw_R_morphtarget,
                jaw_Up_morphtarget,
                jaw_Down_morphtarget,
                neck_Swallow_Up_morphtarget,
                neck_Swallow_Down_morphtarget,
                neck_Tighten_L_morphtarget,
                neck_Tighten_R_morphtarget,
                head_Turn_Up_morphtarget,
                head_Turn_Down_morphtarget,
                head_Turn_L_morphtarget,
                head_Turn_R_morphtarget,
                head_Tilt_L_morphtarget,
                head_Tilt_R_morphtarget,
                head_L_morphtarget,
                head_R_morphtarget,
                head_Forward_morphtarget,
                head_Backward_morphtarget
            ]
        }
        Model {
            id: cc_Base_Eye
            objectName: "CC_Base_Eye"
            source: "meshes/cc_Base_Eye_mesh.mesh"
            skin: skin
            materials: [
                std_Eye_R_material,
                std_Cornea_R_material,
                std_Eye_L_material,
                std_Cornea_L_material
            ]
            morphTargets: [
                v_None_morphtarget,
                v_None_morphtarget947,
                v_None_morphtarget948,
                v_None_morphtarget949
            ]
        }
        Model {
            id: cc_Base_Tongue
            objectName: "CC_Base_Tongue"
            source: "meshes/cc_Base_Tongue_mesh.mesh"
            skin: skin957
            materials: [
                std_Tongue_material
            ]
            morphTargets: [
                v_Tongue_up_morphtarget,
                v_Tongue_Raise_morphtarget,
                v_Tongue_Out_morphtarget,
                v_Tongue_Narrow_morphtarget,
                v_Tongue_Lower_morphtarget,
                v_Tongue_Curl_U_morphtarget,
                v_Tongue_Curl_D_morphtarget,
                mouth_L_morphtarget,
                mouth_Contract_morphtarget,
                tongue_Out_morphtarget,
                tongue_In_morphtarget,
                tongue_Up_morphtarget,
                tongue_Down_morphtarget,
                tongue_Mid_Up_morphtarget,
                tongue_Tip_Up_morphtarget,
                tongue_Tip_Down_morphtarget,
                tongue_Narrow_morphtarget,
                tongue_Wide_morphtarget,
                tongue_Roll_morphtarget,
                tongue_L_morphtarget,
                tongue_R_morphtarget,
                tongue_Tip_L_morphtarget,
                tongue_Tip_R_morphtarget,
                tongue_Twist_L_morphtarget,
                tongue_Twist_R_morphtarget,
                tongue_Bulge_L_morphtarget983,
                tongue_Bulge_R_morphtarget984,
                tongue_Extend_morphtarget,
                tongue_Enlarge_morphtarget,
                jaw_Open_morphtarget987,
                jaw_Forward_morphtarget988,
                jaw_L_morphtarget989,
                jaw_R_morphtarget990,
                jaw_Up_morphtarget991,
                jaw_Down_morphtarget992,
                head_L_morphtarget993,
                head_Backward_morphtarget994
            ]
        }
        Model {
            id: custom_Teeth
            objectName: "Custom_Teeth"
            source: "meshes/custom_Teeth_mesh.mesh"
            skin: skin1003
            materials: [
                teeth_material,
                mouth_material
            ]
            morphTargets: [
                v_None_morphtarget1004,
                v_None_morphtarget1005
            ]
        }
        Model {
            id: female_Angled
            objectName: "Female_Angled"
            source: "meshes/female_Angled_mesh.mesh"
            skin: skin1014
            materials: [
                female_Angled_Transparency_material,
                female_Angled_Base_Transparency_material
            ]
            morphTargets: [
                v_None_morphtarget1015,
                v_Open_morphtarget,
                v_Explosive_morphtarget,
                v_Dental_Lip_morphtarget,
                v_Tight_O_morphtarget,
                v_Tight_morphtarget,
                v_Wide_morphtarget,
                v_Affricate_morphtarget,
                v_Lip_Open_morphtarget,
                v_Tongue_up_morphtarget1024,
                v_Tongue_Raise_morphtarget1025,
                v_Tongue_Out_morphtarget1026,
                v_Tongue_Narrow_morphtarget1027,
                v_Tongue_Lower_morphtarget1028,
                v_Tongue_Curl_U_morphtarget1029,
                v_Tongue_Curl_D_morphtarget1030,
                brow_Raise_Inner_L_morphtarget,
                brow_Raise_Inner_R_morphtarget,
                brow_Raise_Outer_L_morphtarget,
                brow_Raise_Outer_R_morphtarget,
                brow_Drop_L_morphtarget,
                brow_Drop_R_morphtarget,
                brow_Compress_L_morphtarget,
                brow_Compress_R_morphtarget,
                eye_Blink_L_morphtarget,
                eye_Blink_R_morphtarget,
                eye_Squint_L_morphtarget,
                eye_Squint_R_morphtarget,
                eye_Wide_L_morphtarget,
                eye_Wide_R_morphtarget,
                eye_L_Look_L_morphtarget,
                eye_R_Look_L_morphtarget,
                eye_L_Look_R_morphtarget,
                eye_R_Look_R_morphtarget,
                eye_L_Look_Up_morphtarget,
                eye_R_Look_Up_morphtarget,
                eye_L_Look_Down_morphtarget,
                eye_R_Look_Down_morphtarget,
                eye_Pupil_Dilate_morphtarget,
                eye_Pupil_Contract_morphtarget,
                eyelash_Upper_Up_L_morphtarget,
                eyelash_Upper_Down_L_morphtarget,
                eyelash_Upper_Up_R_morphtarget,
                eyelash_Upper_Down_R_morphtarget,
                eyelash_Lower_Up_L_morphtarget,
                eyelash_Lower_Down_L_morphtarget,
                eyelash_Lower_Up_R_morphtarget1061,
                eyelash_Lower_Down_R_morphtarget1062,
                ear_Up_L_morphtarget1063,
                ear_Up_R_morphtarget1064,
                ear_Down_L_morphtarget1065,
                ear_Down_R_morphtarget1066,
                ear_Out_L_morphtarget1067,
                ear_Out_R_morphtarget1068,
                nose_Sneer_L_morphtarget1069,
                nose_Sneer_R_morphtarget1070,
                nose_Nostril_Raise_L_morphtarget1071,
                nose_Nostril_Raise_R_morphtarget1072,
                nose_Nostril_Dilate_L_morphtarget1073,
                nose_Nostril_Dilate_R_morphtarget1074,
                nose_Crease_L_morphtarget1075,
                nose_Crease_R_morphtarget1076,
                nose_Nostril_Down_L_morphtarget1077,
                nose_Nostril_Down_R_morphtarget1078,
                nose_Nostril_In_L_morphtarget1079,
                nose_Nostril_In_R_morphtarget1080,
                nose_Tip_L_morphtarget1081,
                nose_Tip_R_morphtarget1082,
                nose_Tip_Up_morphtarget1083,
                nose_Tip_Down_morphtarget1084,
                cheek_Raise_L_morphtarget1085,
                cheek_Raise_R_morphtarget1086,
                cheek_Suck_L_morphtarget1087,
                cheek_Suck_R_morphtarget1088,
                cheek_Puff_L_morphtarget1089,
                cheek_Puff_R_morphtarget1090,
                mouth_Smile_L_morphtarget1091,
                mouth_Smile_R_morphtarget1092,
                mouth_Smile_Sharp_L_morphtarget1093,
                mouth_Smile_Sharp_R_morphtarget1094,
                mouth_Frown_L_morphtarget1095,
                mouth_Frown_R_morphtarget1096,
                mouth_Stretch_L_morphtarget1097,
                mouth_Stretch_R_morphtarget1098,
                mouth_Dimple_L_morphtarget1099,
                mouth_Dimple_R_morphtarget1100,
                mouth_Press_L_morphtarget1101,
                mouth_Press_R_morphtarget1102,
                mouth_Tighten_L_morphtarget1103,
                mouth_Tighten_R_morphtarget1104,
                mouth_Blow_L_morphtarget1105,
                mouth_Blow_R_morphtarget1106,
                mouth_Pucker_Up_L_morphtarget1107,
                mouth_Pucker_Up_R_morphtarget1108,
                mouth_Pucker_Down_L_morphtarget1109,
                mouth_Pucker_Down_R_morphtarget1110,
                mouth_Funnel_Up_L_morphtarget1111,
                mouth_Funnel_Up_R_morphtarget1112,
                mouth_Funnel_Down_L_morphtarget1113,
                mouth_Funnel_Down_R_morphtarget1114,
                mouth_Roll_In_Upper_L_morphtarget1115,
                mouth_Roll_In_Upper_R_morphtarget1116,
                mouth_Roll_In_Lower_L_morphtarget1117,
                mouth_Roll_In_Lower_R_morphtarget1118,
                mouth_Roll_Out_Upper_L_morphtarget1119,
                mouth_Roll_Out_Upper_R_morphtarget1120,
                mouth_Roll_Out_Lower_L_morphtarget1121,
                mouth_Roll_Out_Lower_R_morphtarget1122,
                mouth_Push_Upper_L_morphtarget1123,
                mouth_Push_Upper_R_morphtarget1124,
                mouth_Push_Lower_L_morphtarget1125,
                mouth_Push_Lower_R_morphtarget1126,
                mouth_Pull_Upper_L_morphtarget1127,
                mouth_Pull_Upper_R_morphtarget1128,
                mouth_Pull_Lower_L_morphtarget1129,
                mouth_Pull_Lower_R_morphtarget1130,
                mouth_Up_morphtarget1131,
                mouth_Down_morphtarget1132,
                mouth_L_morphtarget1133,
                mouth_R_morphtarget1134,
                mouth_Upper_L_morphtarget1135,
                mouth_Upper_R_morphtarget1136,
                mouth_Lower_L_morphtarget1137,
                mouth_Lower_R_morphtarget1138,
                mouth_Shrug_Upper_morphtarget1139,
                mouth_Shrug_Lower_morphtarget1140,
                mouth_Drop_Upper_morphtarget1141,
                mouth_Drop_Lower_morphtarget1142,
                mouth_Up_Upper_L_morphtarget1143,
                mouth_Up_Upper_R_morphtarget1144,
                mouth_Down_Lower_L_morphtarget1145,
                mouth_Down_Lower_R_morphtarget1146,
                mouth_Chin_Up_morphtarget1147,
                mouth_Close_morphtarget1148,
                mouth_Contract_morphtarget1149,
                tongue_Out_morphtarget1150,
                tongue_In_morphtarget1151,
                tongue_Up_morphtarget1152,
                tongue_Down_morphtarget1153,
                tongue_Mid_Up_morphtarget1154,
                tongue_Tip_Up_morphtarget1155,
                tongue_Tip_Down_morphtarget1156,
                tongue_Narrow_morphtarget1157,
                tongue_Wide_morphtarget1158,
                tongue_Roll_morphtarget1159,
                tongue_L_morphtarget1160,
                tongue_R_morphtarget1161,
                tongue_Tip_L_morphtarget1162,
                tongue_Tip_R_morphtarget1163,
                tongue_Twist_L_morphtarget1164,
                tongue_Twist_R_morphtarget1165,
                tongue_Bulge_L_morphtarget1166,
                tongue_Bulge_R_morphtarget1167,
                tongue_Extend_morphtarget1168,
                tongue_Enlarge_morphtarget1169,
                jaw_Open_morphtarget1170,
                jaw_Forward_morphtarget1171,
                jaw_Backward_morphtarget1172,
                jaw_L_morphtarget1173,
                jaw_R_morphtarget1174,
                jaw_Up_morphtarget1175,
                jaw_Down_morphtarget1176,
                neck_Swallow_Up_morphtarget1177,
                neck_Swallow_Down_morphtarget1178,
                neck_Tighten_L_morphtarget1179,
                neck_Tighten_R_morphtarget1180,
                head_Turn_Up_morphtarget1181,
                head_Turn_Down_morphtarget1182,
                head_Turn_L_morphtarget1183,
                head_Turn_R_morphtarget1184,
                head_Tilt_L_morphtarget1185,
                head_Tilt_R_morphtarget1186,
                head_L_morphtarget1187,
                head_R_morphtarget1188,
                head_Forward_morphtarget1189,
                head_Backward_morphtarget1190,
                v_None_morphtarget1191,
                v_Open_morphtarget1192,
                v_Explosive_morphtarget1193,
                v_Dental_Lip_morphtarget1194,
                v_Tight_O_morphtarget1195,
                v_Tight_morphtarget1196,
                v_Wide_morphtarget1197,
                v_Affricate_morphtarget1198,
                v_Lip_Open_morphtarget1199,
                v_Tongue_up_morphtarget1200,
                v_Tongue_Raise_morphtarget1201,
                v_Tongue_Out_morphtarget1202,
                v_Tongue_Narrow_morphtarget1203,
                v_Tongue_Lower_morphtarget1204,
                v_Tongue_Curl_U_morphtarget1205,
                v_Tongue_Curl_D_morphtarget1206,
                brow_Raise_Inner_L_morphtarget1207,
                brow_Raise_Inner_R_morphtarget1208,
                brow_Raise_Outer_L_morphtarget1209,
                brow_Raise_Outer_R_morphtarget1210,
                brow_Drop_L_morphtarget1211,
                brow_Drop_R_morphtarget1212,
                brow_Compress_L_morphtarget1213,
                brow_Compress_R_morphtarget1214,
                eye_Blink_L_morphtarget1215,
                eye_Blink_R_morphtarget1216,
                eye_Squint_L_morphtarget1217,
                eye_Squint_R_morphtarget1218,
                eye_Wide_L_morphtarget1219,
                eye_Wide_R_morphtarget1220,
                eye_L_Look_L_morphtarget1221,
                eye_R_Look_L_morphtarget1222,
                eye_L_Look_R_morphtarget1223,
                eye_R_Look_R_morphtarget1224,
                eye_L_Look_Up_morphtarget1225,
                eye_R_Look_Up_morphtarget1226,
                eye_L_Look_Down_morphtarget1227,
                eye_R_Look_Down_morphtarget1228,
                eye_Pupil_Dilate_morphtarget1229,
                eye_Pupil_Contract_morphtarget1230,
                eyelash_Upper_Up_L_morphtarget1231,
                eyelash_Upper_Down_L_morphtarget1232,
                eyelash_Upper_Up_R_morphtarget1233,
                eyelash_Upper_Down_R_morphtarget1234,
                eyelash_Lower_Up_L_morphtarget1235,
                eyelash_Lower_Down_L_morphtarget1236,
                eyelash_Lower_Up_R_morphtarget1237,
                eyelash_Lower_Down_R_morphtarget1238,
                ear_Up_L_morphtarget1239,
                ear_Up_R_morphtarget1240,
                ear_Down_L_morphtarget1241,
                ear_Down_R_morphtarget1242,
                ear_Out_L_morphtarget1243,
                ear_Out_R_morphtarget1244,
                nose_Sneer_L_morphtarget1245,
                nose_Sneer_R_morphtarget1246,
                nose_Nostril_Raise_L_morphtarget1247,
                nose_Nostril_Raise_R_morphtarget1248,
                nose_Nostril_Dilate_L_morphtarget1249,
                nose_Nostril_Dilate_R_morphtarget1250,
                nose_Crease_L_morphtarget1251,
                nose_Crease_R_morphtarget1252,
                nose_Nostril_Down_L_morphtarget1253,
                nose_Nostril_Down_R_morphtarget1254,
                nose_Nostril_In_L_morphtarget1255,
                nose_Nostril_In_R_morphtarget1256,
                nose_Tip_L_morphtarget1257,
                nose_Tip_R_morphtarget1258,
                nose_Tip_Up_morphtarget1259,
                nose_Tip_Down_morphtarget1260,
                cheek_Raise_L_morphtarget1261,
                cheek_Raise_R_morphtarget1262,
                cheek_Suck_L_morphtarget1263,
                cheek_Suck_R_morphtarget1264,
                cheek_Puff_L_morphtarget1265,
                cheek_Puff_R_morphtarget1266,
                mouth_Smile_L_morphtarget1267,
                mouth_Smile_R_morphtarget1268,
                mouth_Smile_Sharp_L_morphtarget1269,
                mouth_Smile_Sharp_R_morphtarget1270,
                mouth_Frown_L_morphtarget1271,
                mouth_Frown_R_morphtarget1272,
                mouth_Stretch_L_morphtarget1273,
                mouth_Stretch_R_morphtarget1274,
                mouth_Dimple_L_morphtarget1275,
                mouth_Dimple_R_morphtarget1276,
                mouth_Press_L_morphtarget1277,
                mouth_Press_R_morphtarget1278,
                mouth_Tighten_L_morphtarget1279,
                mouth_Tighten_R_morphtarget1280,
                mouth_Blow_L_morphtarget1281,
                mouth_Blow_R_morphtarget1282,
                mouth_Pucker_Up_L_morphtarget1283,
                mouth_Pucker_Up_R_morphtarget1284,
                mouth_Pucker_Down_L_morphtarget1285,
                mouth_Pucker_Down_R_morphtarget1286,
                mouth_Funnel_Up_L_morphtarget1287,
                mouth_Funnel_Up_R_morphtarget1288,
                mouth_Funnel_Down_L_morphtarget1289,
                mouth_Funnel_Down_R_morphtarget1290,
                mouth_Roll_In_Upper_L_morphtarget1291,
                mouth_Roll_In_Upper_R_morphtarget1292,
                mouth_Roll_In_Lower_L_morphtarget1293,
                mouth_Roll_In_Lower_R_morphtarget1294,
                mouth_Roll_Out_Upper_L_morphtarget1295,
                mouth_Roll_Out_Upper_R_morphtarget1296,
                mouth_Roll_Out_Lower_L_morphtarget1297,
                mouth_Roll_Out_Lower_R_morphtarget1298,
                mouth_Push_Upper_L_morphtarget1299,
                mouth_Push_Upper_R_morphtarget1300,
                mouth_Push_Lower_L_morphtarget1301,
                mouth_Push_Lower_R_morphtarget1302,
                mouth_Pull_Upper_L_morphtarget1303,
                mouth_Pull_Upper_R_morphtarget1304,
                mouth_Pull_Lower_L_morphtarget1305,
                mouth_Pull_Lower_R_morphtarget1306,
                mouth_Up_morphtarget1307,
                mouth_Down_morphtarget1308,
                mouth_L_morphtarget1309,
                mouth_R_morphtarget1310,
                mouth_Upper_L_morphtarget1311,
                mouth_Upper_R_morphtarget1312,
                mouth_Lower_L_morphtarget1313,
                mouth_Lower_R_morphtarget1314,
                mouth_Shrug_Upper_morphtarget1315,
                mouth_Shrug_Lower_morphtarget1316,
                mouth_Drop_Upper_morphtarget1317,
                mouth_Drop_Lower_morphtarget1318,
                mouth_Up_Upper_L_morphtarget1319,
                mouth_Up_Upper_R_morphtarget1320,
                mouth_Down_Lower_L_morphtarget1321,
                mouth_Down_Lower_R_morphtarget1322,
                mouth_Chin_Up_morphtarget1323,
                mouth_Close_morphtarget1324,
                mouth_Contract_morphtarget1325,
                tongue_Out_morphtarget1326,
                tongue_In_morphtarget1327,
                tongue_Up_morphtarget1328,
                tongue_Down_morphtarget1329,
                tongue_Mid_Up_morphtarget1330,
                tongue_Tip_Up_morphtarget1331,
                tongue_Tip_Down_morphtarget1332,
                tongue_Narrow_morphtarget1333,
                tongue_Wide_morphtarget1334,
                tongue_Roll_morphtarget1335,
                tongue_L_morphtarget1336,
                tongue_R_morphtarget1337,
                tongue_Tip_L_morphtarget1338,
                tongue_Tip_R_morphtarget1339,
                tongue_Twist_L_morphtarget1340,
                tongue_Twist_R_morphtarget1341,
                tongue_Bulge_L_morphtarget1342,
                tongue_Bulge_R_morphtarget1343,
                tongue_Extend_morphtarget1344,
                tongue_Enlarge_morphtarget1345,
                jaw_Open_morphtarget1346,
                jaw_Forward_morphtarget1347,
                jaw_Backward_morphtarget1348,
                jaw_L_morphtarget1349,
                jaw_R_morphtarget1350,
                jaw_Up_morphtarget1351,
                jaw_Down_morphtarget1352,
                neck_Swallow_Up_morphtarget1353,
                neck_Swallow_Down_morphtarget1354,
                neck_Tighten_L_morphtarget1355,
                neck_Tighten_R_morphtarget1356,
                head_Turn_Up_morphtarget1357,
                head_Turn_Down_morphtarget1358,
                head_Turn_L_morphtarget1359,
                head_Turn_R_morphtarget1360,
                head_Tilt_L_morphtarget1361,
                head_Tilt_R_morphtarget1362,
                head_L_morphtarget1363,
                head_R_morphtarget1364,
                head_Forward_morphtarget1365,
                head_Backward_morphtarget1366
            ]
        }
        Model {
            id: hair
            objectName: "Hair"
            source: "meshes/hair_mesh.mesh"
            skin: skin1378
            materials: [
                hair_Transparency_material,
                scalp_Transparency_material,
                front_Transparency_material
            ]
            morphTargets: [
                frontLeftOut_morphtarget,
                frontLeftBack_morphtarget,
                frontRightOut_morphtarget,
                frontRightBack_morphtarget,
                backBack_morphtarget,
                messy_morphtarget,
                backLeft_morphtarget,
                backRight_morphtarget,
                leftFrontForward_morphtarget,
                rightFrontForward_morphtarget1388,
                frontLeftOut_morphtarget1389,
                frontLeftBack_morphtarget1390,
                frontRightOut_morphtarget1391,
                frontRightBack_morphtarget1392,
                backBack_morphtarget1393,
                messy_morphtarget1394,
                backLeft_morphtarget1395,
                backRight_morphtarget1396,
                leftFrontForward_morphtarget1397,
                rightFrontForward_morphtarget1398,
                frontLeftOut_morphtarget1399,
                frontLeftBack_morphtarget1400,
                frontRightOut_morphtarget1401,
                frontRightBack_morphtarget1402,
                backBack_morphtarget1403,
                messy_morphtarget1404,
                backLeft_morphtarget1405,
                backRight_morphtarget1406,
                leftFrontForward_morphtarget1407,
                rightFrontForward_morphtarget
            ]
        }
        Node {
            id: cc_Base_BoneRoot
            objectName: "CC_Base_BoneRoot"
            rotation: Qt.quaternion(0.707107, -0.707107, 0, 0)
            scale: Qt.vector3d(1, 1, 1)
            Node {
                id: cc_Base_Hip
                objectName: "CC_Base_Hip"
                position: Qt.vector3d(0, 0, 107.16)
                rotation: Qt.quaternion(0.707107, 0.707107, 0, 0)
                scale: Qt.vector3d(1, 1, 1)
                Node {
                    id: cc_Base_Pelvis
                    objectName: "CC_Base_Pelvis"
                    position: Qt.vector3d(-3.55271e-15, 1.52588e-05, 2.1881e-07)
                    rotation: Qt.quaternion(0.995086, 0.0990144, -2.76695e-14, -7.57538e-08)
                    scale: Qt.vector3d(1, 1, 1)
                    Node {
                        id: cc_Base_L_Thigh
                        objectName: "CC_Base_L_Thigh"
                        position: Qt.vector3d(9.46355, -2.5088, 0.0423489)
                        rotation: Qt.quaternion(0.0109393, -0.00113133, 0.0958957, 0.995331)
                        scale: Qt.vector3d(1, 1, 1.00001)
                        Node {
                            id: cc_Base_L_Calf
                            objectName: "CC_Base_L_Calf"
                            position: Qt.vector3d(-0.00037939, 48.0956, -0.000116539)
                            rotation: Qt.quaternion(0.999927, -0.0118591, 0.000163217, 0.00220899)
                            scale: Qt.vector3d(1, 1, 1)
                            Node {
                                id: cc_Base_L_Foot
                                objectName: "CC_Base_L_Foot"
                                position: Qt.vector3d(-4.7061e-05, 50.9834, -1.31591e-05)
                                rotation: Qt.quaternion(0.786968, 0.614612, -0.039491, 0.0370668)
                                scale: Qt.vector3d(1, 1, 1)
                                Node {
                                    id: cc_Base_L_ToeBaseShareBone
                                    objectName: "CC_Base_L_ToeBaseShareBone"
                                    position: Qt.vector3d(2.69897e-05, 13.9788, -2.17855e-05)
                                    rotation: Qt.quaternion(0.982821, 0.18029, 0.0268579, -0.0289196)
                                    scale: Qt.vector3d(1, 1, 1)
                                }
                                Node {
                                    id: cc_Base_L_ToeBase
                                    objectName: "CC_Base_L_ToeBase"
                                    position: Qt.vector3d(2.69897e-05, 13.9788, -2.17855e-05)
                                    rotation: Qt.quaternion(0.982828, 0.180277, 0.0266761, -0.0289574)
                                    Node {
                                        id: cc_Base_L_PinkyToe1
                                        objectName: "CC_Base_L_PinkyToe1"
                                        position: Qt.vector3d(-2.59075, 0.293011, -0.180485)
                                        rotation: Qt.quaternion(0.981057, -0.190372, 0.0314346, -0.0172697)
                                        scale: Qt.vector3d(1, 1, 1)
                                    }
                                    Node {
                                        id: cc_Base_L_RingToe1
                                        objectName: "CC_Base_L_RingToe1"
                                        position: Qt.vector3d(-1.28931, 1.28125, 0.0998829)
                                        rotation: Qt.quaternion(0.973079, -0.225087, 0.0494947, 0.00194996)
                                        scale: Qt.vector3d(1, 1, 1)
                                    }
                                    Node {
                                        id: cc_Base_L_MidToe1
                                        objectName: "CC_Base_L_MidToe1"
                                        position: Qt.vector3d(-2.23368e-05, 2.21479, 8.01682e-06)
                                        rotation: Qt.quaternion(0.987444, -0.152877, 0.0377366, 0.0125818)
                                        scale: Qt.vector3d(1, 1, 1)
                                    }
                                    Node {
                                        id: cc_Base_L_IndexToe1
                                        objectName: "CC_Base_L_IndexToe1"
                                        position: Qt.vector3d(1.47173, 2.35995, 0.145739)
                                        rotation: Qt.quaternion(0.985614, -0.163067, 0.0425021, 0.0129502)
                                        scale: Qt.vector3d(1, 1, 1)
                                    }
                                    Node {
                                        id: cc_Base_L_BigToe1
                                        objectName: "CC_Base_L_BigToe1"
                                        position: Qt.vector3d(3.38719, 2.21748, -0.212174)
                                        rotation: Qt.quaternion(0.999438, -0.031833, 5.98449e-06, 0.0105226)
                                        scale: Qt.vector3d(1, 1, 1)
                                    }
                                }
                            }
                            Node {
                                id: cc_Base_L_CalfTwist01
                                objectName: "CC_Base_L_CalfTwist01"
                                position: Qt.vector3d(-1.01235e-05, -1.37594e-05, -4.84195e-06)
                                rotation: Qt.quaternion(1, -7.17702e-06, -3.94473e-07, -9.12948e-06)
                                Node {
                                    id: cc_Base_L_CalfTwist02
                                    objectName: "CC_Base_L_CalfTwist02"
                                    position: Qt.vector3d(-0.000463848, 25.4918, 0.000342851)
                                    rotation: Qt.quaternion(1, -1.37082e-06, 1.21955e-05, -1.68451e-06)
                                    scale: Qt.vector3d(1, 1, 1)
                                }
                            }
                            Node {
                                id: cc_Base_L_KneeShareBone
                                objectName: "CC_Base_L_KneeShareBone"
                                position: Qt.vector3d(-1.01235e-05, -1.37594e-05, -4.84195e-06)
                                rotation: Qt.quaternion(0.999871, 5.02323e-06, 0.0160823, 6.73613e-06)
                                scale: Qt.vector3d(1, 1, 1)
                            }
                        }
                        Node {
                            id: cc_Base_L_ThighTwist01
                            objectName: "CC_Base_L_ThighTwist01"
                            position: Qt.vector3d(-2.79734e-06, 1.01251e-05, -5.50644e-07)
                            rotation: Qt.quaternion(1, 2.29558e-05, -1.40408e-06, 7.67609e-06)
                            scale: Qt.vector3d(1, 1, 1)
                            Node {
                                id: cc_Base_L_ThighTwist02
                                objectName: "CC_Base_L_ThighTwist02"
                                position: Qt.vector3d(0.000170739, 24.0478, -0.00116523)
                                rotation: Qt.quaternion(1, -6.17502e-08, -1.96491e-06, -6.15394e-08)
                                scale: Qt.vector3d(1, 1, 1)
                            }
                        }
                    }
                    Node {
                        id: cc_Base_R_Thigh
                        objectName: "CC_Base_R_Thigh"
                        position: Qt.vector3d(-9.47052, -2.50646, 0.044987)
                        rotation: Qt.quaternion(-0.0109387, 0.00113044, 0.0958952, 0.995331)
                        scale: Qt.vector3d(1, 1, 0.999995)
                        Node {
                            id: cc_Base_R_Calf
                            objectName: "CC_Base_R_Calf"
                            position: Qt.vector3d(0.000320458, 48.0937, -0.000135971)
                            rotation: Qt.quaternion(0.999927, -0.0118589, -0.000163331, -0.00221115)
                            scale: Qt.vector3d(1, 1, 1)
                            Node {
                                id: cc_Base_R_KneeShareBone
                                objectName: "CC_Base_R_KneeShareBone"
                                position: Qt.vector3d(1.32289e-05, -1.82111e-05, -5.86733e-06)
                                rotation: Qt.quaternion(0.999871, 5.02844e-06, -0.0160822, -6.76484e-06)
                                scale: Qt.vector3d(1, 1, 1)
                            }
                            Node {
                                id: cc_Base_R_Foot
                                objectName: "CC_Base_R_Foot"
                                position: Qt.vector3d(4.21719e-05, 50.9794, -1.63456e-05)
                                rotation: Qt.quaternion(0.786967, 0.614614, 0.0394905, -0.0370663)
                                scale: Qt.vector3d(1, 1, 1)
                                Node {
                                    id: cc_Base_R_ToeBase
                                    objectName: "CC_Base_R_ToeBase"
                                    position: Qt.vector3d(-3.22945e-05, 13.9881, -4.17233e-06)
                                    rotation: Qt.quaternion(0.982828, 0.180275, -0.0266737, 0.0289574)
                                    scale: Qt.vector3d(1, 1, 1)
                                    Node {
                                        id: cc_Base_R_BigToe1
                                        objectName: "CC_Base_R_BigToe1"
                                        position: Qt.vector3d(-3.38706, 2.2177, -0.212317)
                                        rotation: Qt.quaternion(0.999438, -0.0318326, -8.31076e-06, -0.0105224)
                                        scale: Qt.vector3d(1, 1, 1)
                                    }
                                    Node {
                                        id: cc_Base_R_PinkyToe1
                                        objectName: "CC_Base_R_PinkyToe1"
                                        position: Qt.vector3d(2.59005, 0.289957, -0.180211)
                                        rotation: Qt.quaternion(0.981057, -0.19037, -0.0314379, 0.0172692)
                                        scale: Qt.vector3d(1, 1, 1)
                                    }
                                    Node {
                                        id: cc_Base_R_RingToe1
                                        objectName: "CC_Base_R_RingToe1"
                                        position: Qt.vector3d(1.28893, 1.279, 0.100022)
                                        rotation: Qt.quaternion(0.973079, -0.225085, -0.0494975, -0.00195033)
                                        scale: Qt.vector3d(1, 1, 1)
                                    }
                                    Node {
                                        id: cc_Base_R_IndexToe1
                                        objectName: "CC_Base_R_IndexToe1"
                                        position: Qt.vector3d(-1.47122, 2.35891, 0.145791)
                                        rotation: Qt.quaternion(0.985614, -0.163065, -0.0425051, -0.0129503)
                                        scale: Qt.vector3d(1, 1, 1)
                                    }
                                    Node {
                                        id: cc_Base_R_MidToe1
                                        objectName: "CC_Base_R_MidToe1"
                                        position: Qt.vector3d(3.11211e-05, 2.21484, 1.96695e-06)
                                        rotation: Qt.quaternion(0.987445, -0.152875, -0.0377375, -0.0125821)
                                        scale: Qt.vector3d(1, 1, 1)
                                    }
                                }
                                Node {
                                    id: cc_Base_R_ToeBaseShareBone
                                    objectName: "CC_Base_R_ToeBaseShareBone"
                                    position: Qt.vector3d(-3.22945e-05, 13.9881, -4.17233e-06)
                                    rotation: Qt.quaternion(0.982823, 0.18028, -0.0268592, 0.0289234)
                                    scale: Qt.vector3d(1, 1, 1)
                                }
                            }
                            Node {
                                id: cc_Base_R_CalfTwist01
                                objectName: "CC_Base_R_CalfTwist01"
                                position: Qt.vector3d(1.32289e-05, -1.82111e-05, -5.86733e-06)
                                rotation: Qt.quaternion(1, -7.13598e-06, 3.66439e-07, 9.10061e-06)
                                scale: Qt.vector3d(1, 1, 1)
                                Node {
                                    id: cc_Base_R_CalfTwist02
                                    objectName: "CC_Base_R_CalfTwist02"
                                    position: Qt.vector3d(0.000453451, 25.4897, 0.000340752)
                                    rotation: Qt.quaternion(1, -1.54204e-06, -1.22146e-05, 1.66466e-06)
                                    scale: Qt.vector3d(1, 1, 1)
                                }
                            }
                        }
                        Node {
                            id: cc_Base_R_ThighTwist01
                            objectName: "CC_Base_R_ThighTwist01"
                            position: Qt.vector3d(1.90786e-06, 2.17785e-05, -2.85462e-06)
                            rotation: Qt.quaternion(1, 2.28863e-05, 1.31507e-06, -7.74626e-06)
                            Node {
                                id: cc_Base_R_ThighTwist02
                                objectName: "CC_Base_R_ThighTwist02"
                                position: Qt.vector3d(-0.000205355, 24.0468, -0.00117142)
                                rotation: Qt.quaternion(1, -1.30308e-09, 1.9675e-06, 6.10027e-08)
                                scale: Qt.vector3d(1, 1, 1)
                            }
                        }
                    }
                }
                Node {
                    id: cc_Base_Waist
                    objectName: "CC_Base_Waist"
                    position: Qt.vector3d(-0.00107853, 6.61222, 1.85472)
                    rotation: Qt.quaternion(0.991075, 0.133305, -3.71234e-05, 0.000305371)
                    scale: Qt.vector3d(1, 1, 1)
                    Node {
                        id: cc_Base_Spine01
                        objectName: "CC_Base_Spine01"
                        position: Qt.vector3d(-1.13549e-06, 3.91714, 0.00116942)
                        rotation: Qt.quaternion(0.989791, -0.142527, 3.6821e-05, -0.000323365)
                        scale: Qt.vector3d(1, 1, 1)
                        Node {
                            id: cc_Base_Spine02
                            objectName: "CC_Base_Spine02"
                            position: Qt.vector3d(-9.98307e-07, 12.6652, -0.000683305)
                            rotation: Qt.quaternion(0.994148, -0.108031, -6.234e-06, -3.80121e-05)
                            scale: Qt.vector3d(1, 1, 1)
                            Node {
                                id: cc_Base_NeckTwist01
                                objectName: "CC_Base_NeckTwist01"
                                position: Qt.vector3d(2.33325e-06, 25.9741, -0.00629282)
                                rotation: Qt.quaternion(0.980469, 0.196673, 7.04552e-05, -0.000215696)
                                scale: Qt.vector3d(1, 1, 1)
                                Node {
                                    id: cc_Base_NeckTwist02
                                    objectName: "CC_Base_NeckTwist02"
                                    position: Qt.vector3d(8.6095e-07, 3.5714, -0.00114605)
                                    rotation: Qt.quaternion(0.99821, 0.0598023, 1.79215e-05, 7.08467e-05)
                                    scale: Qt.vector3d(1, 1, 1)
                                    Node {
                                        id: cc_Base_Head
                                        objectName: "CC_Base_Head"
                                        position: Qt.vector3d(-3.16436e-05, 3.38534, 0.00133821)
                                        rotation: Qt.quaternion(0.990156, -0.139966, -2.45167e-05, 0.000204731)
                                        scale: Qt.vector3d(1, 1, 1)
                                        Node {
                                            id: cc_Base_FacialBone
                                            objectName: "CC_Base_FacialBone"
                                            position: Qt.vector3d(-1.71891e-08, 2.12662e-05, -1.53838e-05)
                                            rotation: Qt.quaternion(0.499998, 0.499997, 0.500003, 0.500002)
                                            scale: Qt.vector3d(1, 1, 1)
                                            Node {
                                                id: cc_Base_JawRoot
                                                objectName: "CC_Base_JawRoot"
                                                position: Qt.vector3d(1.39458, 2.59549, 3.68302e-07)
                                                rotation: Qt.quaternion(0.707121, -6.23685e-05, -4.54629e-05, 0.707092)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_Tongue01
                                                    objectName: "CC_Base_Tongue01"
                                                    position: Qt.vector3d(2.9753, 0.89721, 0.000850241)
                                                    rotation: Qt.quaternion(0.996066, 3.042e-05, -0.000586127, 0.0886164)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                    Node {
                                                        id: cc_Base_Tongue02
                                                        objectName: "CC_Base_Tongue02"
                                                        position: Qt.vector3d(1.16606, 0.000276206, 1.4219e-06)
                                                        rotation: Qt.quaternion(0.995216, 0.000105926, -6.17618e-05, 0.0977013)
                                                        scale: Qt.vector3d(1, 1, 1)
                                                        Node {
                                                            id: cc_Base_Tongue03
                                                            objectName: "CC_Base_Tongue03"
                                                            position: Qt.vector3d(1.71067, 0.000157811, 2.53459e-06)
                                                            rotation: Qt.quaternion(1, -1.77096e-06, -8.89922e-08, -3.16544e-06)
                                                            scale: Qt.vector3d(1, 1, 1)
                                                        }
                                                    }
                                                }
                                                Node {
                                                    id: cc_Base_Teeth02
                                                    objectName: "CC_Base_Teeth02"
                                                    position: Qt.vector3d(3.31512, 1.10618, -0.00525426)
                                                    rotation: Qt.quaternion(-0.000159648, 1, -5.27213e-06, 9.72311e-05)
                                                }
                                            }
                                            Node {
                                                id: cc_Base_R_Eye
                                                objectName: "CC_Base_R_Eye"
                                                position: Qt.vector3d(6.62624, 7.04054, -3.46627)
                                                rotation: Qt.quaternion(-0.000103457, 0.707058, 4.26991e-06, 0.707156)
                                                scale: Qt.vector3d(1, 1, 1)
                                            }
                                            Node {
                                                id: cc_Base_L_Eye
                                                objectName: "CC_Base_L_Eye"
                                                position: Qt.vector3d(6.62358, 7.04345, 3.47238)
                                                rotation: Qt.quaternion(0.000103626, 0.707149, 4.27047e-06, 0.707064)
                                                scale: Qt.vector3d(1, 1, 1)
                                            }
                                            Node {
                                                id: cc_Base_UpperJaw
                                                objectName: "CC_Base_UpperJaw"
                                                position: Qt.vector3d(2.32984, 6.42024, 0.00224376)
                                                rotation: Qt.quaternion(0.707102, 2.64157e-05, -3.39859e-05, 0.707111)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_Teeth01
                                                    objectName: "CC_Base_Teeth01"
                                                    position: Qt.vector3d(0.367599, 0.332571, 0.00551556)
                                                    rotation: Qt.quaternion(2.42495e-05, 1, -2.12812e-05, -3.54807e-05)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            Node {
                                id: cc_Base_L_Clavicle
                                objectName: "CC_Base_L_Clavicle"
                                position: Qt.vector3d(4.68705, 20.1727, -0.0148819)
                                rotation: Qt.quaternion(0.700331, -0.0128297, 0.148832, -0.698012)
                                Node {
                                    id: cc_Base_L_Upperarm
                                    objectName: "CC_Base_L_Upperarm"
                                    position: Qt.vector3d(-4.51505e-06, 10.5331, 7.15256e-07)
                                    rotation: Qt.quaternion(0.962464, 0.108854, 0.029816, -0.24683)
                                    scale: Qt.vector3d(1, 1, 1)
                                    Node {
                                        id: cc_Base_L_Forearm
                                        objectName: "CC_Base_L_Forearm"
                                        position: Qt.vector3d(-0.000228897, 26.7477, -0.000228673)
                                        rotation: Qt.quaternion(0.999971, 0.00674687, 9.59115e-06, -0.00347194)
                                        scale: Qt.vector3d(1, 1, 1)
                                        Node {
                                            id: cc_Base_L_ForearmTwist01
                                            objectName: "CC_Base_L_ForearmTwist01"
                                            position: Qt.vector3d(1.40816e-05, 1.21295e-05, 5.60284e-06)
                                            rotation: Qt.quaternion(1, -2.26079e-07, 3.42308e-06, -6.12915e-06)
                                            scale: Qt.vector3d(1, 1, 1)
                                            Node {
                                                id: cc_Base_L_ForearmTwist02
                                                objectName: "CC_Base_L_ForearmTwist02"
                                                position: Qt.vector3d(-0.000124484, 12.0123, -2.74181e-06)
                                                rotation: Qt.quaternion(1, 4.45498e-06, 2.5006e-07, 5.92956e-06)
                                                scale: Qt.vector3d(1, 1, 1)
                                            }
                                        }
                                        Node {
                                            id: cc_Base_L_ElbowShareBone
                                            objectName: "CC_Base_L_ElbowShareBone"
                                            position: Qt.vector3d(1.40816e-05, 1.21295e-05, 5.60284e-06)
                                            rotation: Qt.quaternion(1, -0.000461049, 0.000428738, -0.00033452)
                                            scale: Qt.vector3d(1, 1, 1)
                                        }
                                        Node {
                                            id: cc_Base_L_Hand
                                            objectName: "CC_Base_L_Hand"
                                            position: Qt.vector3d(2.53618e-05, 24.0245, 6.55651e-06)
                                            rotation: Qt.quaternion(0.997974, -0.0617851, -0.000465676, 0.0151478)
                                            scale: Qt.vector3d(1, 1, 1)
                                            Node {
                                                id: cc_Base_L_Pinky1
                                                objectName: "CC_Base_L_Pinky1"
                                                position: Qt.vector3d(0.382132, 8.73782, -1.87079)
                                                rotation: Qt.quaternion(0.998367, 0.0557951, 0.000455456, -0.0122127)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_L_Pinky2
                                                    objectName: "CC_Base_L_Pinky2"
                                                    position: Qt.vector3d(-4.03821e-06, 2.69371, 5.02914e-07)
                                                    rotation: Qt.quaternion(0.999865, -0.0030224, -0.00141763, -0.0160969)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                    Node {
                                                        id: cc_Base_L_Pinky3
                                                        objectName: "CC_Base_L_Pinky3"
                                                        position: Qt.vector3d(-1.81794e-06, 1.44688, 3.57628e-07)
                                                        rotation: Qt.quaternion(0.99874, -0.0185378, 0.00048529, 0.0466366)
                                                        scale: Qt.vector3d(1, 1, 1)
                                                    }
                                                }
                                            }
                                            Node {
                                                id: cc_Base_L_Ring1
                                                objectName: "CC_Base_L_Ring1"
                                                position: Qt.vector3d(8.12113e-06, 8.78815, -5.78165e-06)
                                                rotation: Qt.quaternion(0.9983, 0.0573146, 0.000528722, -0.0106036)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_L_Ring2
                                                    objectName: "CC_Base_L_Ring2"
                                                    position: Qt.vector3d(-1.45882e-05, 3.94732, 8.9407e-08)
                                                    rotation: Qt.quaternion(0.999543, -0.00611472, -0.000255505, -0.0295886)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                    Node {
                                                        id: cc_Base_L_Ring3
                                                        objectName: "CC_Base_L_Ring3"
                                                        position: Qt.vector3d(0.0105219, 2.17217, -0.00370961)
                                                        rotation: Qt.quaternion(0.99921, -0.00786831, -0.000279578, 0.0389654)
                                                        scale: Qt.vector3d(1, 1, 1)
                                                    }
                                                }
                                            }
                                            Node {
                                                id: cc_Base_L_Mid1
                                                objectName: "CC_Base_L_Mid1"
                                                position: Qt.vector3d(-0.257526, 8.9251, 1.82926)
                                                rotation: Qt.quaternion(0.997896, 0.0627349, -0.00264226, -0.0161745)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_L_Mid2
                                                    objectName: "CC_Base_L_Mid2"
                                                    position: Qt.vector3d(-1.51321e-05, 4.35272, -4.76837e-07)
                                                    rotation: Qt.quaternion(0.999974, 0.00146561, 0.00349107, -0.00614855)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                    Node {
                                                        id: cc_Base_L_Mid3
                                                        objectName: "CC_Base_L_Mid3"
                                                        position: Qt.vector3d(-1.44318e-05, 2.68343, 2.39611e-05)
                                                        rotation: Qt.quaternion(0.99986, 0.000865383, 0.000135182, 0.0167225)
                                                        scale: Qt.vector3d(1, 1, 1)
                                                    }
                                                }
                                            }
                                            Node {
                                                id: cc_Base_L_Index1
                                                objectName: "CC_Base_L_Index1"
                                                position: Qt.vector3d(0.0123316, 8.78897, 3.96476)
                                                rotation: Qt.quaternion(0.998364, 0.0544476, -0.00302007, -0.0171828)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_L_Index2
                                                    objectName: "CC_Base_L_Index2"
                                                    position: Qt.vector3d(6.86145e-05, 3.72325, -9.79402e-06)
                                                    rotation: Qt.quaternion(0.999881, 0.0102603, 0.00531317, -0.0102077)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                    Node {
                                                        id: cc_Base_L_Index3
                                                        objectName: "CC_Base_L_Index3"
                                                        position: Qt.vector3d(-0.00395439, 2.37871, 0.0019506)
                                                        rotation: Qt.quaternion(0.999554, 0.0157248, -3.38293e-05, 0.0253697)
                                                        scale: Qt.vector3d(1, 1, 1)
                                                    }
                                                }
                                            }
                                            Node {
                                                id: cc_Base_L_Thumb1
                                                objectName: "CC_Base_L_Thumb1"
                                                position: Qt.vector3d(0.603867, 1.59073, 2.3844)
                                                rotation: Qt.quaternion(0.888128, 0.437415, -0.120524, -0.0732907)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_L_Thumb2
                                                    objectName: "CC_Base_L_Thumb2"
                                                    position: Qt.vector3d(-1.12653e-05, 5.62754, 3.57628e-06)
                                                    rotation: Qt.quaternion(0.985586, -0.161556, 0.000753365, 0.0501938)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                    Node {
                                                        id: cc_Base_L_Thumb3
                                                        objectName: "CC_Base_L_Thumb3"
                                                        position: Qt.vector3d(-1.06096e-05, 2.68149, 2.14577e-06)
                                                        rotation: Qt.quaternion(0.999284, -0.00304263, 0.0023606, 0.0376462)
                                                        scale: Qt.vector3d(1, 1, 1)
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Node {
                                        id: cc_Base_L_UpperarmTwist01
                                        objectName: "CC_Base_L_UpperarmTwist01"
                                        position: Qt.vector3d(5.57601e-05, 4.22299e-05, -7.18981e-07)
                                        rotation: Qt.quaternion(0.999999, 3.06013e-06, -0.0013162, 1.45757e-06)
                                        scale: Qt.vector3d(1, 1, 1)
                                        Node {
                                            id: cc_Base_L_UpperarmTwist02
                                            objectName: "CC_Base_L_UpperarmTwist02"
                                            position: Qt.vector3d(-7.45654e-05, 13.3738, -0.000195667)
                                            rotation: Qt.quaternion(0.999999, 1.21218e-06, 0.00131715, 1.08703e-08)
                                            scale: Qt.vector3d(1, 1, 1)
                                        }
                                    }
                                }
                            }
                            Node {
                                id: cc_Base_L_RibsTwist
                                objectName: "CC_Base_L_RibsTwist"
                                position: Qt.vector3d(10.1393, 5.12957, 11.9304)
                                rotation: Qt.quaternion(4.27584e-07, 6.509e-06, 0.63672, 0.771095)
                                scale: Qt.vector3d(1, 1, 1)
                                Node {
                                    id: cc_Base_L_Breast
                                    objectName: "CC_Base_L_Breast"
                                    position: Qt.vector3d(2.36017e-05, 2, -1.87112e-05)
                                    rotation: Qt.quaternion(1, -2.05011e-08, -3.45462e-08, -1.98174e-07)
                                }
                            }
                            Node {
                                id: cc_Base_R_RibsTwist
                                objectName: "CC_Base_R_RibsTwist"
                                position: Qt.vector3d(-10.1048, 5.1396, 11.9116)
                                rotation: Qt.quaternion(6.5529e-07, 6.41032e-06, 0.63672, 0.771095)
                                scale: Qt.vector3d(1, 1, 1)
                                Node {
                                    id: cc_Base_R_Breast
                                    objectName: "CC_Base_R_Breast"
                                    position: Qt.vector3d(-2.25793e-05, 2, 5.89779e-05)
                                    rotation: Qt.quaternion(1, 4.65684e-08, 3.43499e-08, 4.02359e-08)
                                }
                            }
                            Node {
                                id: cc_Base_R_Clavicle
                                objectName: "CC_Base_R_Clavicle"
                                position: Qt.vector3d(-4.68396, 20.1709, -0.0149944)
                                rotation: Qt.quaternion(0.700346, -0.012823, -0.148829, 0.697997)
                                Node {
                                    id: cc_Base_R_Upperarm
                                    objectName: "CC_Base_R_Upperarm"
                                    position: Qt.vector3d(-6.42836e-05, 10.5631, 2.14577e-06)
                                    rotation: Qt.quaternion(0.962464, 0.108854, -0.0298171, 0.246828)
                                    scale: Qt.vector3d(1, 1, 1)
                                    Node {
                                        id: cc_Base_R_Forearm
                                        objectName: "CC_Base_R_Forearm"
                                        position: Qt.vector3d(0.000197798, 26.7094, -0.000227511)
                                        rotation: Qt.quaternion(0.999971, 0.0067468, -8.21002e-06, 0.00347362)
                                        Node {
                                            id: cc_Base_R_ElbowShareBone
                                            objectName: "CC_Base_R_ElbowShareBone"
                                            position: Qt.vector3d(2.20984e-05, 9.46224e-06, 6.19888e-06)
                                            rotation: Qt.quaternion(1, -0.000461076, -0.000428479, 0.000334758)
                                            scale: Qt.vector3d(1, 1, 1)
                                        }
                                        Node {
                                            id: cc_Base_R_ForearmTwist01
                                            objectName: "CC_Base_R_ForearmTwist01"
                                            position: Qt.vector3d(2.20984e-05, 9.46224e-06, 6.19888e-06)
                                            rotation: Qt.quaternion(1, -1.99769e-07, -3.70014e-06, 5.82071e-06)
                                            scale: Qt.vector3d(1, 1, 1)
                                            Node {
                                                id: cc_Base_R_ForearmTwist02
                                                objectName: "CC_Base_R_ForearmTwist02"
                                                position: Qt.vector3d(0.000108257, 11.9977, 6.73532e-06)
                                                rotation: Qt.quaternion(1, 4.52204e-06, -1.62981e-08, -5.95438e-06)
                                                scale: Qt.vector3d(1, 1, 1)
                                            }
                                        }
                                        Node {
                                            id: cc_Base_R_Hand
                                            objectName: "CC_Base_R_Hand"
                                            position: Qt.vector3d(2.53171e-05, 23.9955, 4.52995e-06)
                                            rotation: Qt.quaternion(0.997974, -0.061785, 0.000465086, -0.0151485)
                                            scale: Qt.vector3d(1, 1, 1)
                                            Node {
                                                id: cc_Base_R_Ring1
                                                objectName: "CC_Base_R_Ring1"
                                                position: Qt.vector3d(-2.58386e-05, 8.78816, -5.96046e-06)
                                                rotation: Qt.quaternion(0.9983, 0.0573146, -0.000528331, 0.010604)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_R_Ring2
                                                    objectName: "CC_Base_R_Ring2"
                                                    position: Qt.vector3d(-8.88109e-06, 3.94734, -1.49012e-08)
                                                    rotation: Qt.quaternion(0.999544, -0.00611431, 0.000250093, 0.0295834)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                    Node {
                                                        id: cc_Base_R_Ring3
                                                        objectName: "CC_Base_R_Ring3"
                                                        position: Qt.vector3d(-0.0101716, 2.17543, -0.00355834)
                                                        rotation: Qt.quaternion(0.99921, -0.00786875, 0.000284793, -0.0389602)
                                                        scale: Qt.vector3d(1, 1, 1)
                                                    }
                                                }
                                            }
                                            Node {
                                                id: cc_Base_R_Mid1
                                                objectName: "CC_Base_R_Mid1"
                                                position: Qt.vector3d(0.256554, 8.92637, 1.82804)
                                                rotation: Qt.quaternion(0.997896, 0.0627348, 0.00264227, 0.0161746)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_R_Mid2
                                                    objectName: "CC_Base_R_Mid2"
                                                    position: Qt.vector3d(2.54884e-05, 4.35338, 3.15905e-06)
                                                    rotation: Qt.quaternion(0.999974, 0.00146547, -0.0034924, 0.00614699)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                    Node {
                                                        id: cc_Base_R_Mid3
                                                        objectName: "CC_Base_R_Mid3"
                                                        position: Qt.vector3d(-3.06964e-05, 2.68344, 2.32458e-05)
                                                        rotation: Qt.quaternion(0.99986, 0.000865551, -0.000134379, -0.0167216)
                                                        scale: Qt.vector3d(1, 1, 1)
                                                    }
                                                }
                                            }
                                            Node {
                                                id: cc_Base_R_Thumb1
                                                objectName: "CC_Base_R_Thumb1"
                                                position: Qt.vector3d(-0.604917, 1.59199, 2.3813)
                                                rotation: Qt.quaternion(0.888128, 0.437415, 0.120525, 0.0732917)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_R_Thumb2
                                                    objectName: "CC_Base_R_Thumb2"
                                                    position: Qt.vector3d(-1.07288e-05, 5.62639, 1.16825e-05)
                                                    rotation: Qt.quaternion(0.985586, -0.161555, -0.000752545, -0.0501934)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                    Node {
                                                        id: cc_Base_R_Thumb3
                                                        objectName: "CC_Base_R_Thumb3"
                                                        position: Qt.vector3d(-2.74181e-06, 2.68148, 3.09944e-06)
                                                        rotation: Qt.quaternion(0.999283, -0.00304144, -0.00237515, -0.0376552)
                                                        scale: Qt.vector3d(1, 1, 1)
                                                    }
                                                }
                                            }
                                            Node {
                                                id: cc_Base_R_Index1
                                                objectName: "CC_Base_R_Index1"
                                                position: Qt.vector3d(-0.0136182, 8.78927, 3.96011)
                                                rotation: Qt.quaternion(0.998364, 0.0544476, 0.00302055, 0.0171833)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_R_Index2
                                                    objectName: "CC_Base_R_Index2"
                                                    position: Qt.vector3d(-2.40436e-05, 3.72322, -7.95722e-06)
                                                    rotation: Qt.quaternion(0.999881, 0.0102603, -0.00531397, 0.0102067)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                    Node {
                                                        id: cc_Base_R_Index3
                                                        objectName: "CC_Base_R_Index3"
                                                        position: Qt.vector3d(0.00403702, 2.37935, 0.0019728)
                                                        rotation: Qt.quaternion(0.999555, 0.0157248, 3.50807e-05, -0.0253682)
                                                        scale: Qt.vector3d(1, 1, 1)
                                                    }
                                                }
                                            }
                                            Node {
                                                id: cc_Base_R_Pinky1
                                                objectName: "CC_Base_R_Pinky1"
                                                position: Qt.vector3d(-0.381958, 8.74054, -1.8696)
                                                rotation: Qt.quaternion(0.998367, 0.055795, -0.000455004, 0.0122132)
                                                scale: Qt.vector3d(1, 1, 1)
                                                Node {
                                                    id: cc_Base_R_Pinky2
                                                    objectName: "CC_Base_R_Pinky2"
                                                    position: Qt.vector3d(1.05798e-06, 2.69388, -7.97212e-07)
                                                    rotation: Qt.quaternion(0.999865, -0.0030224, 0.0014269, 0.016106)
                                                    scale: Qt.vector3d(1, 1, 1)
                                                    Node {
                                                        id: cc_Base_R_Pinky3
                                                        objectName: "CC_Base_R_Pinky3"
                                                        position: Qt.vector3d(5.65648e-05, 1.44683, -4.35114e-06)
                                                        rotation: Qt.quaternion(0.99874, -0.0185371, -0.000491607, -0.0466432)
                                                        scale: Qt.vector3d(1, 1, 1)
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Node {
                                        id: cc_Base_R_UpperarmTwist01
                                        objectName: "CC_Base_R_UpperarmTwist01"
                                        position: Qt.vector3d(1.62274e-05, -1.85445e-05, 1.25915e-06)
                                        rotation: Qt.quaternion(0.999999, 2.97421e-06, 0.00132015, -4.84798e-07)
                                        Node {
                                            id: cc_Base_R_UpperarmTwist02
                                            objectName: "CC_Base_R_UpperarmTwist02"
                                            position: Qt.vector3d(0.00010024, 13.3547, -0.000188008)
                                            rotation: Qt.quaternion(0.999999, 1.15924e-06, -0.00132009, -1.86701e-08)
                                            scale: Qt.vector3d(1, 1, 1)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Animations:
    Timeline {
        id: idle_timeline
        objectName: "Idle"
        property real framesPerSecond: 1000
        startFrame: 0
        endFrame: 16634
        currentFrame: 0
        enabled: false
        animations: TimelineAnimation {
            duration: 16634
            from: 0
            to: 16634
            running: false
            loops: Animation.Infinite
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky3_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky1_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index3_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index1_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thumb1_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid3_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid2_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring3_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring2_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring1_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Hand_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Forearm_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Upperarm_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Clavicle_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb3_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb2_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb1_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index3_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_NeckTwist01
            property: "rotation"
            keyframeSource: "animations/cc_Base_NeckTwist01_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thigh_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine02
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine02_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Clavicle_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Foot_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring1_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index2_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Calf_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid1_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky2_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thigh_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index1_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine01
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine01_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_ToeBase_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_Waist
            property: "rotation"
            keyframeSource: "animations/cc_Base_Waist_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Calf_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid1_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_ToeBase_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring3_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "position"
            keyframeSource: "animations/cc_Base_Hip_position_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "rotation"
            keyframeSource: "animations/cc_Base_Hip_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_Head
            property: "rotation"
            keyframeSource: "animations/cc_Base_Head_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Foot_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Upperarm_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Forearm_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Hand_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky1_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky2_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky3_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring2_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid2_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid3_rotation_0.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index2_rotation_0.qad"
        }
            KeyframeGroup {
            target: cc_Base_R_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161555, -0.000752545, -0.0501934) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999283, -0.00304144, -0.00237515, -0.0376552) }
        }
}
    Timeline {
        id: weightShift_timeline
        objectName: "WeightShift"
        property real framesPerSecond: 1000
        startFrame: 0
        endFrame: 9434
        currentFrame: 0
        enabled: false
        animations: TimelineAnimation {
            duration: 9434
            from: 0
            to: 9434
            running: false
            loops: Animation.Infinite
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky3_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky1_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index3_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index1_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thumb1_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid3_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid2_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring3_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring2_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring1_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Hand_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Forearm_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Upperarm_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Clavicle_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb1_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index3_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_NeckTwist01
            property: "rotation"
            keyframeSource: "animations/cc_Base_NeckTwist01_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thigh_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine02
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine02_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Clavicle_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Foot_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring1_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index2_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Calf_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid1_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky2_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thigh_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index1_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine01
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine01_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_ToeBase_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_Waist
            property: "rotation"
            keyframeSource: "animations/cc_Base_Waist_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Calf_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid1_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_ToeBase_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring3_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "position"
            keyframeSource: "animations/cc_Base_Hip_position_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "rotation"
            keyframeSource: "animations/cc_Base_Hip_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_Head
            property: "rotation"
            keyframeSource: "animations/cc_Base_Head_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Foot_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Upperarm_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Forearm_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Hand_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky1_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky2_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky3_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring2_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid2_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid3_rotation_1.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index2_rotation_1.qad"
        }
            KeyframeGroup {
            target: cc_Base_L_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161556, 0.000753365, 0.0501938) }
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999284, -0.00304263, 0.0023606, 0.0376462) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161555, -0.000752545, -0.0501934) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999283, -0.00304144, -0.00237515, -0.0376552) }
        }
}
    Timeline {
        id: v2_BreathingIdle_timeline
        objectName: "v2_BreathingIdle"
        property real framesPerSecond: 1000
        startFrame: 0
        endFrame: 9934
        currentFrame: 0
        enabled: false
        animations: TimelineAnimation {
            duration: 9934
            from: 0
            to: 9934
            running: false
            loops: Animation.Infinite
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky3_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky1_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index3_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index1_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thumb1_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid3_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid2_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring3_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring2_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring1_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Hand_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Forearm_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Upperarm_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Clavicle_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb1_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index3_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_NeckTwist01
            property: "rotation"
            keyframeSource: "animations/cc_Base_NeckTwist01_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thigh_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine02
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine02_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Clavicle_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Foot_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring1_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index2_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Calf_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid1_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky2_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thigh_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index1_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine01
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine01_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_ToeBase_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_Waist
            property: "rotation"
            keyframeSource: "animations/cc_Base_Waist_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Calf_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid1_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_ToeBase_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring3_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "position"
            keyframeSource: "animations/cc_Base_Hip_position_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "rotation"
            keyframeSource: "animations/cc_Base_Hip_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_Head
            property: "rotation"
            keyframeSource: "animations/cc_Base_Head_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Foot_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Upperarm_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Forearm_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Hand_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky1_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky2_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky3_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring2_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid2_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid3_rotation_2.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index2_rotation_2.qad"
        }
            KeyframeGroup {
            target: cc_Base_L_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161556, 0.000753365, 0.0501938) }
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999284, -0.00304263, 0.0023606, 0.0376462) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161555, -0.000752545, -0.0501934) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999283, -0.00304144, -0.00237515, -0.0376552) }
        }
}
    Timeline {
        id: v2_HappyIdle_timeline
        objectName: "v2_HappyIdle"
        property real framesPerSecond: 1000
        startFrame: 0
        endFrame: 2000
        currentFrame: 0
        enabled: false
        animations: TimelineAnimation {
            duration: 2000
            from: 0
            to: 2000
            running: false
            loops: Animation.Infinite
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky3_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky1_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index3_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index1_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thumb1_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid3_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid2_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring3_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring2_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring1_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Hand_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Forearm_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Upperarm_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Clavicle_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb1_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index3_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_NeckTwist01
            property: "rotation"
            keyframeSource: "animations/cc_Base_NeckTwist01_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thigh_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine02
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine02_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Clavicle_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Foot_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring1_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index2_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Calf_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid1_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky2_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thigh_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index1_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine01
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine01_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_ToeBase_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_Waist
            property: "rotation"
            keyframeSource: "animations/cc_Base_Waist_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Calf_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid1_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_ToeBase_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring3_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "position"
            keyframeSource: "animations/cc_Base_Hip_position_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "rotation"
            keyframeSource: "animations/cc_Base_Hip_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_Head
            property: "rotation"
            keyframeSource: "animations/cc_Base_Head_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Foot_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Upperarm_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Forearm_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Hand_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky1_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky2_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky3_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring2_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid2_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid3_rotation_3.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index2_rotation_3.qad"
        }
            KeyframeGroup {
            target: cc_Base_L_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161556, 0.000753365, 0.0501938) }
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999284, -0.00304263, 0.0023606, 0.0376462) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161555, -0.000752545, -0.0501934) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999283, -0.00304144, -0.00237515, -0.0376552) }
        }
}
    Timeline {
        id: talking_timeline
        objectName: "Talking"
        property real framesPerSecond: 1000
        startFrame: 0
        endFrame: 5934
        currentFrame: 0
        enabled: false
        animations: TimelineAnimation {
            duration: 5934
            from: 0
            to: 5934
            running: false
            loops: Animation.Infinite
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky3_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky1_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index3_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index1_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thumb3_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thumb1_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid3_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid2_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring3_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring2_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring1_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Hand_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Forearm_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Upperarm_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Clavicle_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb3_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb2_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb1_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index3_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_NeckTwist01
            property: "rotation"
            keyframeSource: "animations/cc_Base_NeckTwist01_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thigh_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine02
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine02_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Clavicle_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thumb2_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Foot_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring1_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index2_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Calf_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid1_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky2_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thigh_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index1_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine01
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine01_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_ToeBase_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_Waist
            property: "rotation"
            keyframeSource: "animations/cc_Base_Waist_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Calf_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid1_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_ToeBase_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring3_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "position"
            keyframeSource: "animations/cc_Base_Hip_position_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "rotation"
            keyframeSource: "animations/cc_Base_Hip_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_Head
            property: "rotation"
            keyframeSource: "animations/cc_Base_Head_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Foot_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Upperarm_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Forearm_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Hand_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky1_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky2_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky3_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring2_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid2_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid3_rotation_4.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index2_rotation_4.qad"
        }
    }
    Timeline {
        id: agreeing_timeline
        objectName: "Agreeing"
        property real framesPerSecond: 1000
        startFrame: 0
        endFrame: 1834
        currentFrame: 0
        enabled: false
        animations: TimelineAnimation {
            duration: 1834
            from: 0
            to: 1834
            running: false
            loops: Animation.Infinite
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky3_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky1_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index3_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index1_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thumb1_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid3_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid2_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring3_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring2_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring1_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Hand_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Forearm_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Upperarm_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Clavicle_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb1_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index3_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_NeckTwist01
            property: "rotation"
            keyframeSource: "animations/cc_Base_NeckTwist01_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thigh_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine02
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine02_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Clavicle_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Foot_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring1_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index2_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Calf_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid1_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky2_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thigh_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index1_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine01
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine01_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_ToeBase
            property: "rotation"
            Keyframe {
                frame: 0
                value: Qt.quaternion(-0.974218, -0.222292, -0.0238052, 0.0303176)
            }
        }
        KeyframeGroup {
            target: cc_Base_Waist
            property: "rotation"
            keyframeSource: "animations/cc_Base_Waist_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Calf_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid1_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_ToeBase
            property: "rotation"
            Keyframe {
                frame: 0
                value: Qt.quaternion(0.969501, 0.242167, -0.0215952, 0.0309218)
            }
        }
        KeyframeGroup {
            target: cc_Base_L_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring3_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "position"
            keyframeSource: "animations/cc_Base_Hip_position_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "rotation"
            keyframeSource: "animations/cc_Base_Hip_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_Head
            property: "rotation"
            keyframeSource: "animations/cc_Base_Head_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Foot_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Upperarm_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Forearm_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Hand_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky1_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky2_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky3_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring2_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid2_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid3_rotation_5.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index2_rotation_5.qad"
        }
            KeyframeGroup {
            target: cc_Base_L_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161556, 0.000753365, 0.0501938) }
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999284, -0.00304263, 0.0023606, 0.0376462) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161555, -0.000752545, -0.0501934) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999283, -0.00304144, -0.00237515, -0.0376552) }
        }
}
    Timeline {
        id: v2_ThoughtfulHeadNod_timeline
        objectName: "v2_ThoughtfulHeadNod"
        property real framesPerSecond: 1000
        startFrame: 0
        endFrame: 2934
        currentFrame: 0
        enabled: false
        animations: TimelineAnimation {
            duration: 2934
            from: 0
            to: 2934
            running: false
            loops: Animation.Infinite
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky3_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky1_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index3_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index1_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thumb1_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid3_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid2_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring3_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring2_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring1_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Hand_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Forearm_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Upperarm_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Clavicle_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb1_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index3_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_NeckTwist01
            property: "rotation"
            keyframeSource: "animations/cc_Base_NeckTwist01_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thigh_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine02
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine02_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Clavicle_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Foot_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring1_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index2_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Calf_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid1_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky2_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thigh_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index1_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine01
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine01_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_ToeBase_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_Waist
            property: "rotation"
            keyframeSource: "animations/cc_Base_Waist_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Calf_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid1_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_ToeBase_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring3_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "position"
            keyframeSource: "animations/cc_Base_Hip_position_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "rotation"
            keyframeSource: "animations/cc_Base_Hip_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_Head
            property: "rotation"
            keyframeSource: "animations/cc_Base_Head_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Foot_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Upperarm_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Forearm_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Hand_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky1_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky2_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky3_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring2_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid2_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid3_rotation_6.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index2_rotation_6.qad"
        }
            KeyframeGroup {
            target: cc_Base_L_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161556, 0.000753365, 0.0501938) }
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999284, -0.00304263, 0.0023606, 0.0376462) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161555, -0.000752545, -0.0501934) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999283, -0.00304144, -0.00237515, -0.0376552) }
        }
}
    Timeline {
        id: listening_timeline
        objectName: "Listening"
        property real framesPerSecond: 1000
        startFrame: 0
        endFrame: 9934
        currentFrame: 0
        enabled: false
        animations: TimelineAnimation {
            duration: 9934
            from: 0
            to: 9934
            running: false
            loops: Animation.Infinite
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky3_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky1_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index3_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index1_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thumb1_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid3_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid2_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring3_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring2_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Ring1_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Hand_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Forearm_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Upperarm_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Clavicle_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thumb1_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index3_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_NeckTwist01
            property: "rotation"
            keyframeSource: "animations/cc_Base_NeckTwist01_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Thigh_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine02
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine02_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Clavicle
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Clavicle_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Foot_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring1_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Index2_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Calf_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid1_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Pinky2_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Thigh
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Thigh_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index1_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_Spine01
            property: "rotation"
            keyframeSource: "animations/cc_Base_Spine01_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_ToeBase_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_Waist
            property: "rotation"
            keyframeSource: "animations/cc_Base_Waist_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Calf
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Calf_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_Mid1
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_Mid1_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_R_ToeBase
            property: "rotation"
            keyframeSource: "animations/cc_Base_R_ToeBase_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring3_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "position"
            keyframeSource: "animations/cc_Base_Hip_position_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_Hip
            property: "rotation"
            keyframeSource: "animations/cc_Base_Hip_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_Head
            property: "rotation"
            keyframeSource: "animations/cc_Base_Head_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Foot
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Foot_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Upperarm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Upperarm_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Forearm
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Forearm_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Hand
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Hand_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky1
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky1_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky2_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Pinky3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Pinky3_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Ring2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Ring2_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid2_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Mid3
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Mid3_rotation_7.qad"
        }
        KeyframeGroup {
            target: cc_Base_L_Index2
            property: "rotation"
            keyframeSource: "animations/cc_Base_L_Index2_rotation_7.qad"
        }
            KeyframeGroup {
            target: cc_Base_L_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161556, 0.000753365, 0.0501938) }
        }
        KeyframeGroup {
            target: cc_Base_L_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999284, -0.00304263, 0.0023606, 0.0376462) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb2
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.985586, -0.161555, -0.000752545, -0.0501934) }
        }
        KeyframeGroup {
            target: cc_Base_R_Thumb3
            property: "rotation"
            Keyframe { frame: 0; value: Qt.quaternion(0.999283, -0.00304144, -0.00237515, -0.0376552) }
        }
}
}

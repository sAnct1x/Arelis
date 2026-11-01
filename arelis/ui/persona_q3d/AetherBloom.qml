// Written from three's UnrealBloomPass (the v14k post chain: aether.js "post",
// config.js LOOK.bloom). Bright pass on luma, 5 half-size mips with 3/5/7/9/11 tap Gaussians,
// weighted sum added onto the scene. Runs on the linear HDR frame before tonemapping, like
// three's composer before OutputPass.
import QtQuick
import QtQuick3D

Effect {
    property real strength: 0.85
    property real radius: 0.5
    property real threshold: 0.55
    property real kr: 3
    property real scale: 1
    property vector2d dir: Qt.vector2d(1, 0)
    // sampler names for the composite pass; BufferInput binds the mips onto them
    property TextureInput m1: TextureInput {}
    property TextureInput m2: TextureInput {}
    property TextureInput m3: TextureInput {}
    property TextureInput m4: TextureInput {}
    property TextureInput m5: TextureInput {}
    Shader { id: brightFs; stage: Shader.Fragment; shader: Qt.resolvedUrl("bloom/bright.frag") }
    Shader { id: blurFs; stage: Shader.Fragment; shader: Qt.resolvedUrl("bloom/blur.frag") }
    Shader { id: compositeFs; stage: Shader.Fragment; shader: Qt.resolvedUrl("bloom/composite.frag") }
    Buffer { id: bright; name: "bright"; format: Buffer.RGBA16F; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.5 }
    Buffer { id: h0; name: "h0"; format: Buffer.RGBA16F; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.5 }
    Buffer { id: v0; name: "v0"; format: Buffer.RGBA16F; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.5 }
    Buffer { id: h1; name: "h1"; format: Buffer.RGBA16F; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.25 }
    Buffer { id: v1; name: "v1"; format: Buffer.RGBA16F; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.25 }
    Buffer { id: h2; name: "h2"; format: Buffer.RGBA16F; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.125 }
    Buffer { id: v2; name: "v2"; format: Buffer.RGBA16F; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.125 }
    Buffer { id: h3; name: "h3"; format: Buffer.RGBA16F; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.0625 }
    Buffer { id: v3; name: "v3"; format: Buffer.RGBA16F; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.0625 }
    Buffer { id: h4; name: "h4"; format: Buffer.RGBA16F; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.03125 }
    Buffer { id: v4; name: "v4"; format: Buffer.RGBA16F; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.03125 }
    passes: [
        Pass { shaders: [brightFs]; output: bright },
        Pass { shaders: [blurFs]; output: h0; commands: [BufferInput { buffer: bright }, SetUniformValue { target: "kr"; value: 3.0 }, SetUniformValue { target: "scale"; value: 1.0 }, SetUniformValue { target: "dir"; value: Qt.vector2d(1, 0) }] },
        Pass { shaders: [blurFs]; output: v0; commands: [BufferInput { buffer: h0 }, SetUniformValue { target: "kr"; value: 3.0 }, SetUniformValue { target: "scale"; value: 1.0 }, SetUniformValue { target: "dir"; value: Qt.vector2d(0, 1) }] },
        Pass { shaders: [blurFs]; output: h1; commands: [BufferInput { buffer: v0 }, SetUniformValue { target: "kr"; value: 5.0 }, SetUniformValue { target: "scale"; value: 0.5 }, SetUniformValue { target: "dir"; value: Qt.vector2d(1, 0) }] },
        Pass { shaders: [blurFs]; output: v1; commands: [BufferInput { buffer: h1 }, SetUniformValue { target: "kr"; value: 5.0 }, SetUniformValue { target: "scale"; value: 1.0 }, SetUniformValue { target: "dir"; value: Qt.vector2d(0, 1) }] },
        Pass { shaders: [blurFs]; output: h2; commands: [BufferInput { buffer: v1 }, SetUniformValue { target: "kr"; value: 7.0 }, SetUniformValue { target: "scale"; value: 0.5 }, SetUniformValue { target: "dir"; value: Qt.vector2d(1, 0) }] },
        Pass { shaders: [blurFs]; output: v2; commands: [BufferInput { buffer: h2 }, SetUniformValue { target: "kr"; value: 7.0 }, SetUniformValue { target: "scale"; value: 1.0 }, SetUniformValue { target: "dir"; value: Qt.vector2d(0, 1) }] },
        Pass { shaders: [blurFs]; output: h3; commands: [BufferInput { buffer: v2 }, SetUniformValue { target: "kr"; value: 9.0 }, SetUniformValue { target: "scale"; value: 0.5 }, SetUniformValue { target: "dir"; value: Qt.vector2d(1, 0) }] },
        Pass { shaders: [blurFs]; output: v3; commands: [BufferInput { buffer: h3 }, SetUniformValue { target: "kr"; value: 9.0 }, SetUniformValue { target: "scale"; value: 1.0 }, SetUniformValue { target: "dir"; value: Qt.vector2d(0, 1) }] },
        Pass { shaders: [blurFs]; output: h4; commands: [BufferInput { buffer: v3 }, SetUniformValue { target: "kr"; value: 11.0 }, SetUniformValue { target: "scale"; value: 0.5 }, SetUniformValue { target: "dir"; value: Qt.vector2d(1, 0) }] },
        Pass { shaders: [blurFs]; output: v4; commands: [BufferInput { buffer: h4 }, SetUniformValue { target: "kr"; value: 11.0 }, SetUniformValue { target: "scale"; value: 1.0 }, SetUniformValue { target: "dir"; value: Qt.vector2d(0, 1) }] },
        Pass { shaders: [compositeFs]; commands: [BufferInput { buffer: v0; sampler: "m1" }, BufferInput { buffer: v1; sampler: "m2" }, BufferInput { buffer: v2; sampler: "m3" }, BufferInput { buffer: v3; sampler: "m4" }, BufferInput { buffer: v4; sampler: "m5" }] }
    ]
}

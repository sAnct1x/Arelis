import QtQuick
import QtQuick3D

// Bloom with exactly `levels` blur levels (0 to 3). The scene is boxed down
// to quarter size once (threshold applied there), then each level is a
// horizontal and a vertical Gaussian at 1/4, 1/8 and 1/16 size. A quarter-size
// pass sums and tonemaps the levels; the last, full-size pass tonemaps the
// scene and adds them. ExtendedSceneEnvironment glow always runs 14 blur
// passes from half size whatever its glowLevel; on the box (llvmpipe) that
// cost about 20 ms p95 at 128 units, this about 3 (passA/RESULT.md).
Effect {
    id: bloom
    property int levels: 3
    property real uThreshold: 1.0
    property real uStrength: 1.2
    property real uIntensity: 1.4
    property real uLevels: levels
    // Samplers the sum and add passes read; a BufferInput binds a buffer to one.
    readonly property TextureInput glow2: TextureInput {}
    readonly property TextureInput glow3: TextureInput {}
    readonly property TextureInput glowSum: TextureInput {}

    Shader { id: downShader; stage: Shader.Fragment; shader: "shaders/bloom_down.frag" }
    Shader { id: blurH; stage: Shader.Fragment; shader: "shaders/bloom_h.frag" }
    Shader { id: blurV; stage: Shader.Fragment; shader: "shaders/bloom_v.frag" }
    Shader { id: sumGlow; stage: Shader.Fragment; shader: "shaders/bloom_sum.frag" }
    Shader { id: addGlow; stage: Shader.Fragment; shader: "shaders/bloom_out.frag" }

    component Level: Buffer {
        format: Buffer.RGBA16F
        textureFilterOperation: Buffer.Linear
        textureCoordOperation: Buffer.ClampToEdge
    }
    Level { id: down; name: "bloomDown"; sizeMultiplier: 0.25 }
    Level { id: tmp1; name: "bloomTmp1"; sizeMultiplier: 0.25 }
    Level { id: lvl1; name: "bloomLvl1"; sizeMultiplier: 0.25 }
    Level { id: tmp2; name: "bloomTmp2"; sizeMultiplier: 0.125 }
    Level { id: lvl2; name: "bloomLvl2"; sizeMultiplier: 0.125 }
    Level { id: tmp3; name: "bloomTmp3"; sizeMultiplier: 0.0625 }
    Level { id: lvl3; name: "bloomLvl3"; sizeMultiplier: 0.0625 }
    Buffer { id: sum; name: "bloomSum"; format: Buffer.RGBA8; textureFilterOperation: Buffer.Linear; textureCoordOperation: Buffer.ClampToEdge; sizeMultiplier: 0.25 }

    Pass { id: downPass; shaders: [downShader]; output: down }
    Pass {
        id: h1
        shaders: [blurH]
        commands: [BufferInput { buffer: down }]
        output: tmp1
    }
    Pass {
        id: v1
        shaders: [blurV]
        commands: [BufferInput { buffer: tmp1 }]
        output: lvl1
    }
    Pass {
        id: h2
        shaders: [blurH]
        commands: [BufferInput { buffer: lvl1 }]
        output: tmp2
    }
    Pass {
        id: v2
        shaders: [blurV]
        commands: [BufferInput { buffer: tmp2 }]
        output: lvl2
    }
    Pass {
        id: h3
        shaders: [blurH]
        commands: [BufferInput { buffer: lvl2 }]
        output: tmp3
    }
    Pass {
        id: v3
        shaders: [blurV]
        commands: [BufferInput { buffer: tmp3 }]
        output: lvl3
    }
    Pass {
        id: sumPass
        shaders: [sumGlow]
        commands: [
            BufferInput { buffer: lvl1 },
            BufferInput { buffer: bloom.levels > 1 ? lvl2 : lvl1; sampler: "glow2" },
            BufferInput { buffer: bloom.levels > 2 ? lvl3 : lvl1; sampler: "glow3" }
        ]
        output: sum
    }
    Pass {
        id: out
        shaders: [addGlow]
        commands: [BufferInput { buffer: sum; sampler: "glowSum" }]
    }
    passes: levels > 0
            ? [downPass].concat([h1, v1, h2, v2, h3, v3].slice(0, 2 * Math.min(3, levels)), [sumPass, out])
            : [out]
}

// _paint_orb_direct at glow 1 (the stamp), drawn at opacity glow, added (CompositionMode_Plus).
layout(location = 0) in vec2 vQ;
layout(location = 1) in vec4 vRgbGlow;
layout(location = 2) in vec3 vOrb;
layout(location = 0) out vec4 fragColor;

float haloA(float x) {  // stops 0: .38, .28: .209, .62: .0608, 1: 0
    if (x >= 1.0) return 0.0;
    if (x < 0.28) return mix(0.38, 0.209, x / 0.28);
    if (x < 0.62) return mix(0.209, 0.0608, (x - 0.28) / 0.34);
    return mix(0.0608, 0.0, (x - 0.62) / 0.38);
}

void main() {
    float r = length(vQ);
    vec3 rgb = vRgbGlow.rgb;
    float edge = clamp(vOrb.x + 0.5 - r, 0.0, 1.0);
    vec4 c = vec4(rgb, 1.0) * haloA(r / vOrb.x) * edge;
    if (vOrb.y > 0.35) {
        float x = r / vOrb.y;
        vec4 a = vec4(coreColor.rgb, 1.0);
        vec4 b = vec4(rgb, 1.0) * 0.62;
        vec4 body = x < 0.4 ? mix(a, b, x / 0.4) : mix(b, vec4(0.0), min(1.0, (x - 0.4) / 0.6));
        body *= clamp(vOrb.y + 0.5 - r, 0.0, 1.0);
        c = body + c * (1.0 - body.a);
    }
    if (vOrb.z > 0.2) {
        float pa = clamp(vOrb.z + 0.5 - r, 0.0, 1.0);
        c = vec4(coreColor.rgb, 1.0) * pa + c * (1.0 - pa);
    }
    fragColor = vec4(c.rgb * vRgbGlow.a, 0.0) * qt_Opacity;
}

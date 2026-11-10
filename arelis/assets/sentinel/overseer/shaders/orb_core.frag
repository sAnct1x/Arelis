// Soft core. Unshaded, additive One/One, NeverDepthDraw, back faces culled.
// Vertex shader: orb_shell.vert (vN, vW). Peak = coreGain * (coreFloor +
// (1 - coreFloor) * energy): 0.68 at 38 tok/s, 0.78 at 60 tok/s.
VARYING vec3 vN;
VARYING vec3 vW;

void MAIN() {
    vec3 V = normalize(CAMERA_POSITION - vW);
    float nv = clamp(abs(dot(normalize(vN), V)), 0.0, 1.0);
    float f = (1.0 - coreTightMix) * pow(nv, coreSoftPow) + coreTightMix * pow(nv, coreTightPow);
    float e = coreGain * (coreFloor + (1.0 - coreFloor) * energy);
    FRAGCOLOR = vec4(mix(coreEdge, coreCentre, f) * f * e, 1.0);
}

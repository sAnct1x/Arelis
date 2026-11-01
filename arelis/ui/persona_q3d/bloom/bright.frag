// UnrealBloomPass step 1 (three LuminosityHighPassShader): keep pixels whose Rec.709 luma
// passes the threshold. Luma, not the max channel Quick 3D glow uses, so violet and blue
// (low green) stay under it and the whiter rim goes over.
// The scene is additive glow in a half-float target: dense overlaps (her legs, the threads) can
// overflow to Inf, and a linearly filtered Inf texel is NaN. One NaN here spreads through the
// blur chain into a whole block of the 1/32 mip, and the composite turns every pixel that samples
// it black: her body vanished below a cut on d3d11 (cuts land on that mip's texel centres).
// So the bloom only ever sees finite light.
const float BRIGHT_MAX = 64.0;
void MAIN() {
    vec4 t = texture(INPUT, INPUT_UV);
    if (any(isnan(t.rgb))) t.rgb = vec3(0.0);
    t.rgb = clamp(t.rgb, vec3(0.0), vec3(BRIGHT_MAX));
    float v = dot(t.rgb, vec3(0.2126729, 0.7151522, 0.0721750));
    FRAGCOLOR = vec4(t.rgb * smoothstep(threshold, threshold + 0.01, v), 1.0);
}

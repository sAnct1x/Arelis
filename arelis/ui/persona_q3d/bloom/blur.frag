// UnrealBloomPass step 2: separable Gaussian, sigma = radius = kr, texel step of the output mip.
// The step comes from the input's own size (scale 0.5 when the input is the mip above, twice
// as big), not OUTPUT_SIZE, which is the view's size in every pass.
void MAIN() {
    vec2 inv = 1.0 / (vec2(textureSize(INPUT, 0)) * scale);
    float w0 = 0.39894 / kr;
    float ws = w0;
    vec3 s = texture(INPUT, INPUT_UV).rgb * w0;
    for (int i = 1; i < 11; i++) {
        if (float(i) >= kr) break;
        float x = float(i);
        float w = 0.39894 * exp(-0.5 * x * x / (kr * kr)) / kr;
        vec2 o = dir * inv * x;
        s += (texture(INPUT, INPUT_UV + o).rgb + texture(INPUT, INPUT_UV - o).rgb) * w;
        ws += 2.0 * w;
    }
    FRAGCOLOR = vec4(s / ws, 1.0);
}

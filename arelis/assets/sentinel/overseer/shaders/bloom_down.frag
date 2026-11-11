// Bloom input at quarter size: a 4x4 box of the scene (four bilinear taps, so
// no pixel is skipped and a small eye never flickers as it moves), keeping
// only HDR values over the glow threshold.
void MAIN() {
    vec2 px = 1.0 / INPUT_SIZE;
    vec4 c = texture(INPUT, INPUT_UV + vec2(-px.x, -px.y));
    c += texture(INPUT, INPUT_UV + vec2(px.x, -px.y));
    c += texture(INPUT, INPUT_UV + vec2(-px.x, px.y));
    c += texture(INPUT, INPUT_UV + vec2(px.x, px.y));
    c *= 0.25;
    float lum = max(c.r, max(c.g, c.b));
    FRAGCOLOR = min(c * smoothstep(uThreshold, uThreshold + 2.0, lum), vec4(12.0));
}

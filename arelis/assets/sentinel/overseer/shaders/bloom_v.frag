// Bloom level, vertical half: the same 7-tap Gaussian, times the strength
// (once per level, so each wider level is a little brighter, as in
// ExtendedSceneEnvironment).
void MAIN() {
    vec2 px = vec2(0.0, 1.0 / INPUT_SIZE.y);
    vec4 c = texture(INPUT, INPUT_UV) * 0.2161;
    c += (texture(INPUT, INPUT_UV + px) + texture(INPUT, INPUT_UV - px)) * 0.1907;
    c += (texture(INPUT, INPUT_UV + 2.0 * px) + texture(INPUT, INPUT_UV - 2.0 * px)) * 0.1311;
    c += (texture(INPUT, INPUT_UV + 3.0 * px) + texture(INPUT, INPUT_UV - 3.0 * px)) * 0.0702;
    FRAGCOLOR = c * uStrength;
}

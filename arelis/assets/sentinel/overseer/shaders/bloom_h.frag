// Bloom level, horizontal half: a 7-tap Gaussian (sigma 2 texels).
void MAIN() {
    vec2 px = vec2(1.0 / INPUT_SIZE.x, 0.0);
    vec4 c = texture(INPUT, INPUT_UV) * 0.2161;
    c += (texture(INPUT, INPUT_UV + px) + texture(INPUT, INPUT_UV - px)) * 0.1907;
    c += (texture(INPUT, INPUT_UV + 2.0 * px) + texture(INPUT, INPUT_UV - 2.0 * px)) * 0.1311;
    c += (texture(INPUT, INPUT_UV + 3.0 * px) + texture(INPUT, INPUT_UV - 3.0 * px)) * 0.0702;
    FRAGCOLOR = c;
}
